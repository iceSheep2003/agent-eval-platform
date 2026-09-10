"""portal 用例：账号、门户、成员、Agent 挂载、按通道对话。

两套服务分开是因为它们的**鉴权主体不同**：
`PortalAuthService` 处理「谁能登录」，`PortalService` 处理「登录后能看/能做什么」。
后者所有方法都以 `hub_id` 为一等参数——门户是展示平台的可见性边界。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, AsyncIterator, Mapping, Sequence

from ....contracts.asset import AssetQueryPort
from ....contracts.common import Channel, Id
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.execution import (
    ChannelInvocation,
    InvokeEvent,
    InvokePort,
    InvokeResult,
)
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ....shared.passwords import hash_password, verify_password
from ....shared.secrets import hash_secret, new_secret
from ..domain.models import (
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    AuditActorKind,
    AuditEntry,
    PortalAgentChannel,
    PortalHub,
    PortalUser,
    HubAgent,
    HubMember,
    HubRole,
)
from ..infrastructure.repositories import (
    AuditRepository,
    PortalAgentChannelRepository,
    PortalHubRepository,
    PortalSessionRepository,
    PortalUserRepository,
    HubAgentRepository,
    HubMemberRepository,
    RateLimitRepository,
)

#: 门户角色的合法取值，用于在应用层挡住拼错的角色名。
_ROLES: frozenset[str] = frozenset({"owner", "member"})

logger = logging.getLogger(__name__)

#: 展示平台开放的通道。**不含 LIVESH**：影子通道是「复制生产流量给候选版本、
#: 输出不返回给用户」的验证手段，让外部访客跟它对话在语义上就不成立。
#: 影子验证仍然存在，只是留在平台侧做晋级比对，不对展示平台开放。
PORTAL_CHANNELS: tuple[Channel, ...] = (Channel.TEST, Channel.LIVE)

#: 展示文案。顺序即前端切换器的顺序。
CHANNEL_LABELS: Mapping[Channel, str] = {
    Channel.TEST: "测试",
    Channel.LIVE: "生产",
}


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user: PortalUser
    token: str


@dataclass(frozen=True, slots=True)
class HubView:
    """门户 + 当前用户在该门户里的角色。"""

    hub: PortalHub
    role: HubRole


@dataclass(frozen=True, slots=True)
class ChannelView:
    """展示平台看到的单个通道状态。`bound=False` 时前端把切换器置灰。"""

    channel: Channel
    label: str
    bound: bool
    version_id: Id | None
    version_label: str | None


@dataclass(frozen=True, slots=True)
class AgentView:
    id: Id
    asset_id: Id
    name: str
    display_name: str
    description: str
    lifecycle: str
    channels: tuple[ChannelView, ...]


class PortalAuthService:
    def __init__(self, database: Database, clock: Clock, *, session_hours: int = 24) -> None:
        self._db = database
        self._clock = clock
        self._ttl = timedelta(hours=session_hours)

    async def create_user(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        email: str | None = None,
    ) -> PortalUser:
        """按用户名幂等：重复创建返回既有账号，不覆盖密码。"""
        async with UnitOfWork(self._db) as uow:
            users = PortalUserRepository(uow.session)
            existing = await users.find_by_username(username)
            if existing is not None:
                return existing
            user = PortalUser(
                id=new_id("portal_user"),
                username=username,
                email=email,
                display_name=display_name or username,
                password_hash=hash_password(password),
                status="active",
                created_at=self._clock.now(),
            )
            users.add(user)
            await uow.commit()
        return user

    async def list_users(self, limit: int = 100, offset: int = 0) -> Sequence[PortalUser]:
        async with UnitOfWork(self._db) as uow:
            return list(await PortalUserRepository(uow.session).list_all(limit, offset))

    async def login(self, identifier: str, password: str) -> IssuedSession | None:
        """密码 + 锁定检查。

        **失败一律返回 None**，不区分「用户不存在」「密码错」「已锁定」——
        否则接口就成了账号枚举器。锁定计数只对已存在的账号累加。
        """
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            users = PortalUserRepository(uow.session)
            user = await users.find_by_username(identifier)
            if user is None or user.status != "active":
                return None
            if user.is_locked(now):
                return None
            if not verify_password(user.password_hash, password):
                attempts = user.failed_attempts + 1
                locked_until = (
                    now + timedelta(minutes=LOCKOUT_MINUTES)
                    if attempts >= MAX_FAILED_ATTEMPTS
                    else user.locked_until
                )
                await users.record_failure(user.id, attempts, locked_until)
                await uow.commit()
                return None
            await users.reset_failures(user.id)
            token = new_secret()
            PortalSessionRepository(uow.session).add(
                _session_row(new_id("portal_session"), user.id, token, now, self._ttl)
            )
            await uow.commit()
        return IssuedSession(user=user, token=token)

    async def revoke_sessions(self, portal_user_id: str) -> int:
        """吊销某用户全部会话。禁用账号时必须调用，否则旧 cookie 仍然能用到过期。"""
        async with UnitOfWork(self._db) as uow:
            count = await PortalSessionRepository(uow.session).delete_for_user(portal_user_id)
            await uow.commit()
        return count

    async def set_user_status(self, portal_user_id: str, status: str) -> PortalUser:
        """启用/禁用账号。禁用时**连带吊销全部会话**。"""
        async with UnitOfWork(self._db) as uow:
            users = PortalUserRepository(uow.session)
            user = await users.get(portal_user_id)
            if user is None:
                raise NotFound("账号", portal_user_id)
            await users.set_status(portal_user_id, status)
            if status != "active":
                await PortalSessionRepository(uow.session).delete_for_user(portal_user_id)
            await uow.commit()
        return await self.get_user(portal_user_id)

    async def get_user(self, portal_user_id: str) -> PortalUser:
        async with UnitOfWork(self._db) as uow:
            user = await PortalUserRepository(uow.session).get(portal_user_id)
        if user is None:
            raise NotFound("账号", portal_user_id)
        return user

    async def resolve(self, raw_token: str) -> PortalUser | None:
        if not raw_token:
            return None
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            sessions = PortalSessionRepository(uow.session)
            session = await sessions.get_by_token_hash(hash_secret(raw_token))
            if session is None:
                return None
            if session.is_expired(now):
                await sessions.delete(session.id)
                await uow.commit()
                return None
            user = await PortalUserRepository(uow.session).get(session.portal_user_id)
            if user is None or user.status != "active":
                return None
            await sessions.touch(session.id, now)
            await uow.commit()
        return user

    async def logout(self, raw_token: str) -> None:
        if not raw_token:
            return
        async with UnitOfWork(self._db) as uow:
            sessions = PortalSessionRepository(uow.session)
            session = await sessions.get_by_token_hash(hash_secret(raw_token))
            if session is not None:
                await sessions.delete(session.id)
                await uow.commit()

    async def membership(self, hub_id: str, portal_user_id: str) -> HubMember | None:
        async with UnitOfWork(self._db) as uow:
            return await HubMemberRepository(uow.session).get(hub_id, portal_user_id)


#: 对话频率上限：每个 portal 用户每分钟多少次。对话是对 RuntimePort 的无界扇出，
#: 没有这条限制，一个用户就能把执行面打满。
CHAT_LIMIT_PER_MINUTE = 20


class AuditService:
    """审计：谁、什么时候、对什么做了什么。

    **写入失败不能影响业务**——审计是旁路，不是事务的一部分（否则审计表故障
    会变成业务故障）。代价是极端情况下可能丢一条记录，比丢一次登录安全。
    """

    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    async def record(
        self,
        *,
        action: str,
        actor_kind: AuditActorKind,
        actor_id: str,
        workspace_id: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
        ip: str | None = None,
    ) -> None:
        entry = AuditEntry(
            id=new_id("audit"),
            workspace_id=workspace_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            detail=dict(detail or {}),
            ip=ip,
            created_at=self._clock.now(),
        )
        try:
            async with UnitOfWork(self._db) as uow:
                AuditRepository(uow.session).add(entry)
                await uow.commit()
        except Exception:  # noqa: BLE001 - 审计失败不该拖垮业务
            logger.warning("写审计失败 action=%s", action, exc_info=True)

    async def list_recent(
        self, *, workspace_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[AuditEntry]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await AuditRepository(uow.session).list_recent(
                    workspace_id=workspace_id, limit=limit, offset=offset
                )
            )


class PortalRateLimiter:
    """固定窗口限流。计数落库——多进程、重启都不失效。"""

    def __init__(self, database: Database, clock: Clock) -> None:
        self._db = database
        self._clock = clock

    async def consume(
        self, *, scope: str, subject_id: str, limit: int, window_seconds: int = 60
    ) -> bool:
        """消耗一次配额。返回 False 表示超限（**不抛异常**，由调用方决定怎么呈现）。"""
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            repo = RateLimitRepository(uow.session)
            window = await repo.get(scope, subject_id)
            if window is None or window.is_expired(now, window_seconds):
                await repo.reset(scope, subject_id, now)
                await uow.commit()
                return True
            if window.count >= limit:
                return False
            await repo.bump(scope, subject_id)
            await uow.commit()
            return True

    async def remaining(
        self, *, scope: str, subject_id: str, limit: int, window_seconds: int = 60
    ) -> int:
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            window = await RateLimitRepository(uow.session).get(scope, subject_id)
        if window is None or window.is_expired(now, window_seconds):
            return limit
        return max(0, limit - window.count)


class PortalService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        assets: AssetQueryPort,
        invoke: InvokePort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._assets = assets
        self._invoke = invoke

    # -- 门户 ----------------------------------------------------------------

    async def create_hub(
        self,
        *,
        workspace_id: str,
        slug: str,
        name: str,
        description: str = "",
        created_by: str,
    ) -> PortalHub:
        async with UnitOfWork(self._db) as uow:
            hubs = PortalHubRepository(uow.session)
            existing = await hubs.find_by_slug(workspace_id, slug)
            if existing is not None:
                return existing
            hub = PortalHub(
                id=new_id("portal_hub"),
                workspace_id=workspace_id,
                slug=slug,
                name=name,
                description=description,
                status="active",
                created_by=created_by,
                created_at=self._clock.now(),
            )
            hubs.add(hub)
            await uow.commit()
        return hub

    async def get_hub(self, hub_id: str, workspace_id: str) -> PortalHub:
        async with UnitOfWork(self._db) as uow:
            hub = await PortalHubRepository(uow.session).get(hub_id, workspace_id)
        if hub is None:
            raise NotFound("门户", hub_id)
        return hub

    async def get_hub_unscoped(self, hub_id: str) -> PortalHub:
        """按 ID 取门户，**不限定工作区**。

        只给 portal 侧用：那里还没有 workspace_id（它由门户自身决定），
        而调用方已经过了成员校验——成员资格才是那条链上的授权依据。
        """
        async with UnitOfWork(self._db) as uow:
            hub = await PortalHubRepository(uow.session).get_any(hub_id)
        if hub is None:
            raise NotFound("门户", hub_id)
        return hub

    async def list_hubs_for_user(self, portal_user_id: str) -> Sequence[HubView]:
        async with UnitOfWork(self._db) as uow:
            rows = await PortalHubRepository(uow.session).list_for_user(portal_user_id)
        return [HubView(hub=item, role=role) for item, role in rows]

    # -- 成员 ----------------------------------------------------------------

    async def add_member(
        self, *, hub_id: str, portal_user_id: str, role: HubRole = "member"
    ) -> HubMember:
        if role not in _ROLES:
            raise DomainError(Errors.VALIDATION_FAILED, f"未知门户角色 {role!r}")
        async with UnitOfWork(self._db) as uow:
            members = HubMemberRepository(uow.session)
            existing = await members.get(hub_id, portal_user_id)
            if existing is not None:
                return existing
            member = HubMember(
                id=new_id("portal_hub_member"),
                hub_id=hub_id,
                portal_user_id=portal_user_id,
                role=role,
                created_at=self._clock.now(),
            )
            members.add(member)
            await uow.commit()
        return member

    async def list_members(self, hub_id: str) -> Sequence[HubMember]:
        async with UnitOfWork(self._db) as uow:
            return list(await HubMemberRepository(uow.session).list_for_hub(hub_id))

    async def remove_member(self, member_id: str) -> None:
        async with UnitOfWork(self._db) as uow:
            await HubMemberRepository(uow.session).remove(member_id)
            await uow.commit()

    # -- Agent 挂载 ----------------------------------------------------------

    async def attach_agent(
        self,
        *,
        hub_id: str,
        workspace_id: str,
        asset_id: str,
        display_name: str = "",
    ) -> HubAgent:
        """把一个平台资产挂进门户。**先确认它在本工作区存在**，避免挂上别人的 Agent。"""
        asset = await self._assets.get_asset(asset_id, workspace_id)
        if asset is None:
            raise NotFound("Agent", asset_id)
        async with UnitOfWork(self._db) as uow:
            agents = HubAgentRepository(uow.session)
            existing = await agents.find(hub_id, asset_id)
            if existing is not None:
                return existing
            hub_agent = HubAgent(
                id=new_id("portal_agent"),
                hub_id=hub_id,
                asset_id=asset_id,
                display_name=display_name or asset.name,
                sort_order=0,
                created_at=self._clock.now(),
            )
            agents.add(hub_agent)
            await uow.commit()
        return hub_agent

    async def bind_channel(
        self,
        *,
        hub_agent_id: str,
        channel: Channel,
        deployment_credential_id: str,
    ) -> PortalAgentChannel:
        binding = PortalAgentChannel(
            id=new_id("portal_channel"),
            hub_agent_id=hub_agent_id,
            channel=channel,
            deployment_credential_id=deployment_credential_id,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            await PortalAgentChannelRepository(uow.session).upsert(binding)
            await uow.commit()
        return binding

    async def list_hub_agents(
        self, hub_id: str, workspace_id: str
    ) -> Sequence[AgentView]:
        async with UnitOfWork(self._db) as uow:
            rows = await HubAgentRepository(uow.session).list_for_hub(hub_id)
            channels = {
                row.id: await PortalAgentChannelRepository(uow.session).list_for_agent(row.id)
                for row in rows
            }
        return [
            await self._agent_view(row, workspace_id, channels.get(row.id, []))
            for row in rows
        ]

    async def get_hub_agent(
        self, hub_agent_id: str, hub_id: str, workspace_id: str
    ) -> AgentView:
        async with UnitOfWork(self._db) as uow:
            row = await HubAgentRepository(uow.session).get(hub_agent_id)
            if row is None or row.hub_id != hub_id:
                raise NotFound("门户 Agent", hub_agent_id)
            bindings = list(
                await PortalAgentChannelRepository(uow.session).list_for_agent(row.id)
            )
        return await self._agent_view(row, workspace_id, bindings)

    async def _agent_view(
        self,
        row: HubAgent,
        workspace_id: str,
        bindings: Sequence[PortalAgentChannel],
    ) -> AgentView:
        asset = await self._assets.get_asset(row.asset_id, workspace_id)
        by_channel = {item.channel: item for item in bindings}
        views: list[ChannelView] = []
        for channel in PORTAL_CHANNELS:
            version = await self._assets.version_of_channel(
                row.asset_id, channel, workspace_id
            )
            views.append(
                ChannelView(
                    channel=channel,
                    label=CHANNEL_LABELS[channel],
                    bound=version is not None,
                    version_id=version.id if version else None,
                    version_label=version.version_label if version else None,
                )
            )
        return AgentView(
            id=row.id,
            asset_id=row.asset_id,
            name=asset.name if asset else row.asset_id,
            display_name=row.display_name or (asset.name if asset else row.asset_id),
            description=asset.description if asset else "",
            lifecycle=asset.lifecycle if asset else "unknown",
            channels=tuple(views),
        )

    # -- 对话 ----------------------------------------------------------------

    async def chat(
        self,
        *,
        hub_agent_id: str,
        hub_id: str,
        workspace_id: str,
        channel: Channel,
        message: str,
        messages: Sequence[Mapping[str, object]] = (),
        timeout_seconds: float = 60.0,
    ) -> InvokeResult:
        """按通道打一次（非流式）。**版本由通道解析**，调用方给不了版本号。"""
        request = await self._authorize(
            hub_agent_id=hub_agent_id,
            hub_id=hub_id,
            workspace_id=workspace_id,
            channel=channel,
            message=message,
            messages=messages,
            timeout_seconds=timeout_seconds,
        )
        return await self._invoke.invoke_channel(request)

    async def chat_stream(
        self,
        *,
        hub_agent_id: str,
        hub_id: str,
        workspace_id: str,
        channel: Channel,
        message: str,
        messages: Sequence[Mapping[str, object]] = (),
        timeout_seconds: float = 60.0,
    ) -> AsyncIterator[InvokeEvent]:
        """按通道流式打一次。

        **鉴权与参数解析在返回迭代器之前完成**——它们抛的是普通 HTTP 错误，
        调用方还能正常回 4xx；一旦开始产出事件，失败就只能走 `error` 事件了。
        """
        request = await self._authorize(
            hub_agent_id=hub_agent_id,
            hub_id=hub_id,
            workspace_id=workspace_id,
            channel=channel,
            message=message,
            messages=messages,
            timeout_seconds=timeout_seconds,
        )
        async for event in self._invoke.stream_channel(request):
            yield event

    async def _authorize(
        self,
        *,
        hub_agent_id: str,
        hub_id: str,
        workspace_id: str,
        channel: Channel,
        message: str,
        messages: Sequence[Mapping[str, object]],
        timeout_seconds: float,
    ) -> ChannelInvocation:
        """把「这次调用合不合法」全部查完，返回可执行的请求。"""
        if channel not in PORTAL_CHANNELS:
            raise DomainError(
                Errors.NOT_FOUND,
                f"展示平台不开放 {channel.value} 通道",
                channel=channel.value,
            )
        async with UnitOfWork(self._db) as uow:
            row = await HubAgentRepository(uow.session).get(hub_agent_id)
            if row is None or row.hub_id != hub_id:
                raise NotFound("门户 Agent", hub_agent_id)
            binding = await PortalAgentChannelRepository(uow.session).get(row.id, channel)
        if binding is None or binding.deployment_credential_id is None:
            raise DomainError(
                Errors.CHANNEL_UNBOUND,
                f"该门户尚未为 {channel.value} 通道配置调用密钥",
                channel=channel.value,
            )
        # **引用有效 ≠ 钥匙有效**：撤销/过期必须当场挡住，不能等网关报错。
        credential = await self._assets.get_credential_context(
            binding.deployment_credential_id, workspace_id
        )
        if credential is None:
            raise DomainError(
                Errors.CREDENTIAL_EXPIRED,
                f"{channel.value} 通道的调用密钥已失效",
            )
        if credential.channel is not None and credential.channel is not channel:
            raise DomainError(
                Errors.CREDENTIAL_SCOPE_VIOLATION,
                f"该密钥只允许调用 {credential.channel.value} 通道",
            )
        return ChannelInvocation(
            workspace_id=workspace_id,
            asset_id=row.asset_id,
            channel=channel,
            input=message,
            messages=tuple(messages),
            timeout_seconds=timeout_seconds,
            credential_id=binding.deployment_credential_id,
        )


def _session_row(
    session_id: Id, user_id: Id, raw_token: str, now, ttl: timedelta
) -> "PortalSession":
    from ..domain.models import PortalSession

    return PortalSession(
        id=session_id,
        portal_user_id=user_id,
        token_hash=hash_secret(raw_token),
        expires_at=now + ttl,
        last_seen_at=now,
        created_at=now,
    )


__all__ = [
    "AgentView",
    "AuditService",
    "CHANNEL_LABELS",
    "CHAT_LIMIT_PER_MINUTE",
    "ChannelView",
    "IssuedSession",
    "PortalAuthService",
    "PortalRateLimiter",
    "PortalService",
    "HubView",
    "PORTAL_CHANNELS",
]

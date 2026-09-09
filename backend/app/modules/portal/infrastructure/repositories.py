"""portal 仓储：ORM 行 ↔ 领域实体。"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import Channel
from ....shared.clock import ensure_aware
from ..domain.models import (
    AuditEntry,
    PortalAgentChannel,
    PortalHub,
    PortalSession,
    PortalUser,
    HubAgent,
    HubMember,
    RateLimitWindow,
)
from .tables import (
    AuditRow,
    PortalAgentChannelRow,
    PortalHubRow,
    PortalSessionRow,
    PortalUserRow,
    HubAgentRow,
    HubMemberRow,
    RateLimitRow,
)


def _user(row: PortalUserRow) -> PortalUser:
    return PortalUser(
        id=row.id,
        username=row.username,
        email=row.email,
        display_name=row.display_name,
        password_hash=row.password_hash,
        status=row.status,  # type: ignore[arg-type]
        created_at=ensure_aware(row.created_at),
        failed_attempts=row.failed_attempts,
        locked_until=ensure_aware(row.locked_until) if row.locked_until else None,
    )


def _session(row: PortalSessionRow) -> PortalSession:
    return PortalSession(
        id=row.id,
        portal_user_id=row.portal_user_id,
        token_hash=row.token_hash,
        expires_at=ensure_aware(row.expires_at),
        last_seen_at=ensure_aware(row.last_seen_at),
        created_at=ensure_aware(row.created_at),
    )


def _hub(row: PortalHubRow) -> PortalHub:
    return PortalHub(
        id=row.id,
        workspace_id=row.workspace_id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        status=row.status,  # type: ignore[arg-type]
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
    )


def _member(row: HubMemberRow) -> HubMember:
    return HubMember(
        id=row.id,
        hub_id=row.hub_id,
        portal_user_id=row.portal_user_id,
        role=row.role,  # type: ignore[arg-type]
        created_at=ensure_aware(row.created_at),
    )


def _hub_agent(row: HubAgentRow) -> HubAgent:
    return HubAgent(
        id=row.id,
        hub_id=row.hub_id,
        asset_id=row.asset_id,
        display_name=row.display_name,
        sort_order=row.sort_order,
        created_at=ensure_aware(row.created_at),
    )


def _channel(row: PortalAgentChannelRow) -> PortalAgentChannel:
    return PortalAgentChannel(
        id=row.id,
        hub_agent_id=row.hub_agent_id,
        channel=Channel(row.channel),
        deployment_credential_id=row.deployment_credential_id,
        created_at=ensure_aware(row.created_at),
    )


class PortalUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: str) -> PortalUser | None:
        row = await self._session.get(PortalUserRow, user_id)
        return _user(row) if row else None

    async def find_by_username(self, username: str) -> PortalUser | None:
        stmt = select(PortalUserRow).where(PortalUserRow.username == username)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _user(row) if row else None

    async def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[PortalUser]:
        stmt = (
            select(PortalUserRow)
            .order_by(PortalUserRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_user(row) for row in (await self._session.execute(stmt)).scalars().all()]

    def add(self, user: PortalUser) -> None:
        self._session.add(
            PortalUserRow(
                id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                password_hash=user.password_hash,
                status=user.status,
                failed_attempts=user.failed_attempts,
                locked_until=user.locked_until,
            )
        )

    async def record_failure(self, user_id: str, attempts: int, locked_until: datetime | None) -> None:
        await self._session.execute(
            update(PortalUserRow)
            .where(PortalUserRow.id == user_id)
            .values(failed_attempts=attempts, locked_until=locked_until)
        )

    async def reset_failures(self, user_id: str) -> None:
        await self._session.execute(
            update(PortalUserRow)
            .where(PortalUserRow.id == user_id)
            .values(failed_attempts=0, locked_until=None)
        )

    async def set_status(self, user_id: str, status: str) -> None:
        await self._session.execute(
            update(PortalUserRow).where(PortalUserRow.id == user_id).values(status=status)
        )


class PortalSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> PortalSession | None:
        stmt = select(PortalSessionRow).where(PortalSessionRow.token_hash == token_hash)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _session(row) if row else None

    def add(self, session: PortalSession) -> None:
        self._session.add(
            PortalSessionRow(
                id=session.id,
                portal_user_id=session.portal_user_id,
                token_hash=session.token_hash,
                expires_at=session.expires_at,
                last_seen_at=session.last_seen_at,
            )
        )

    async def touch(self, session_id: str, now: datetime) -> None:
        await self._session.execute(
            update(PortalSessionRow)
            .where(PortalSessionRow.id == session_id)
            .values(last_seen_at=now)
        )

    async def delete(self, session_id: str) -> None:
        row = await self._session.get(PortalSessionRow, session_id)
        if row is not None:
            await self._session.delete(row)

    async def delete_for_user(self, portal_user_id: str) -> int:
        """吊销某用户的**全部**会话。禁用账号、改密码时必须调用。"""
        rows = (
            await self._session.execute(
                select(PortalSessionRow).where(
                    PortalSessionRow.portal_user_id == portal_user_id
                )
            )
        ).scalars().all()
        for row in rows:
            await self._session.delete(row)
        return len(rows)


class PortalHubRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, hub_id: str, workspace_id: str) -> PortalHub | None:
        stmt = select(PortalHubRow).where(
            PortalHubRow.id == hub_id,
            PortalHubRow.workspace_id == workspace_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _hub(row) if row else None

    async def get_any(self, hub_id: str) -> PortalHub | None:
        """按 ID 取，不限定工作区。调用方必须自己保证授权（portal 侧靠成员校验）。"""
        row = await self._session.get(PortalHubRow, hub_id)
        return _hub(row) if row else None

    async def find_by_slug(self, workspace_id: str, slug: str) -> PortalHub | None:
        stmt = select(PortalHubRow).where(
            PortalHubRow.workspace_id == workspace_id, PortalHubRow.slug == slug
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _hub(row) if row else None

    async def list_for_workspace(self, workspace_id: str) -> Sequence[PortalHub]:
        stmt = (
            select(PortalHubRow)
            .where(PortalHubRow.workspace_id == workspace_id)
            .order_by(PortalHubRow.created_at.desc())
        )
        return [_hub(row) for row in (await self._session.execute(stmt)).scalars().all()]

    async def list_for_user(
        self, portal_user_id: str
    ) -> Sequence[tuple[PortalHub, str]]:
        """只返回该用户是成员的门户——展示平台的可见性边界。

        连同**门户角色**一起返回：前端要按角色决定是否显示管理入口，
        分开查会变成 N+1。
        """
        stmt = (
            select(PortalHubRow, HubMemberRow.role)
            .join(HubMemberRow, HubMemberRow.hub_id == PortalHubRow.id)
            .where(HubMemberRow.portal_user_id == portal_user_id)
            .order_by(PortalHubRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(_hub(row[0]), str(row[1])) for row in rows]

    def add(self, hub: PortalHub) -> None:
        self._session.add(
            PortalHubRow(
                id=hub.id,
                workspace_id=hub.workspace_id,
                slug=hub.slug,
                name=hub.name,
                description=hub.description,
                status=hub.status,
                created_by=hub.created_by,
            )
        )


class HubMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, hub_id: str, portal_user_id: str) -> HubMember | None:
        stmt = select(HubMemberRow).where(
            HubMemberRow.hub_id == hub_id,
            HubMemberRow.portal_user_id == portal_user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _member(row) if row else None

    async def list_for_hub(self, hub_id: str) -> Sequence[HubMember]:
        stmt = select(HubMemberRow).where(HubMemberRow.hub_id == hub_id)
        return [_member(row) for row in (await self._session.execute(stmt)).scalars().all()]

    def add(self, member: HubMember) -> None:
        self._session.add(
            HubMemberRow(
                id=member.id,
                hub_id=member.hub_id,
                portal_user_id=member.portal_user_id,
                role=member.role,
            )
        )

    async def remove(self, member_id: str) -> None:
        row = await self._session.get(HubMemberRow, member_id)
        if row is not None:
            await self._session.delete(row)


class HubAgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, hub_agent_id: str) -> HubAgent | None:
        row = await self._session.get(HubAgentRow, hub_agent_id)
        return _hub_agent(row) if row else None

    async def list_for_hub(self, hub_id: str) -> Sequence[HubAgent]:
        stmt = (
            select(HubAgentRow)
            .where(HubAgentRow.hub_id == hub_id)
            .order_by(HubAgentRow.sort_order, HubAgentRow.created_at)
        )
        return [
            _hub_agent(row)
            for row in (await self._session.execute(stmt)).scalars().all()
        ]

    async def find(self, hub_id: str, asset_id: str) -> HubAgent | None:
        stmt = select(HubAgentRow).where(
            HubAgentRow.hub_id == hub_id,
            HubAgentRow.asset_id == asset_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _hub_agent(row) if row else None

    def add(self, hub_agent: HubAgent) -> None:
        self._session.add(
            HubAgentRow(
                id=hub_agent.id,
                hub_id=hub_agent.hub_id,
                asset_id=hub_agent.asset_id,
                display_name=hub_agent.display_name,
                sort_order=hub_agent.sort_order,
            )
        )


class PortalAgentChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, hub_agent_id: str, channel: Channel) -> PortalAgentChannel | None:
        stmt = select(PortalAgentChannelRow).where(
            PortalAgentChannelRow.hub_agent_id == hub_agent_id,
            PortalAgentChannelRow.channel == channel.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _channel(row) if row else None

    async def list_for_agent(self, hub_agent_id: str) -> Sequence[PortalAgentChannel]:
        stmt = select(PortalAgentChannelRow).where(
            PortalAgentChannelRow.hub_agent_id == hub_agent_id
        )
        return [
            _channel(row) for row in (await self._session.execute(stmt)).scalars().all()
        ]

    async def upsert(self, binding: PortalAgentChannel) -> None:
        existing = await self.get(binding.hub_agent_id, binding.channel)
        if existing is None:
            self._session.add(
                PortalAgentChannelRow(
                    id=binding.id,
                    hub_agent_id=binding.hub_agent_id,
                    channel=binding.channel.value,
                    deployment_credential_id=binding.deployment_credential_id,
                )
            )
            return
        row = await self._session.get(PortalAgentChannelRow, existing.id)
        if row is not None:
            row.deployment_credential_id = binding.deployment_credential_id


def _rate_limit(row: RateLimitRow) -> RateLimitWindow:
    return RateLimitWindow(
        scope=row.scope,
        subject_id=row.subject_id,
        window_started_at=ensure_aware(row.window_started_at),
        count=row.count,
    )


class RateLimitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, scope: str, subject_id: str) -> RateLimitWindow | None:
        stmt = select(RateLimitRow).where(
            RateLimitRow.scope == scope, RateLimitRow.subject_id == subject_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _rate_limit(row) if row else None

    async def reset(self, scope: str, subject_id: str, now: datetime) -> None:
        """开新窗口。已存在则原地重置——避免窗口表无限增长。"""
        stmt = select(RateLimitRow).where(
            RateLimitRow.scope == scope, RateLimitRow.subject_id == subject_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            self._session.add(
                RateLimitRow(
                    id=f"{scope}:{subject_id}",
                    scope=scope,
                    subject_id=subject_id,
                    window_started_at=now,
                    count=1,
                )
            )
            return
        row.window_started_at = now
        row.count = 1

    async def bump(self, scope: str, subject_id: str) -> None:
        await self._session.execute(
            update(RateLimitRow)
            .where(RateLimitRow.scope == scope, RateLimitRow.subject_id == subject_id)
            .values(count=RateLimitRow.count + 1)
        )


def _audit(row: AuditRow) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        workspace_id=row.workspace_id,
        actor_kind=row.actor_kind,  # type: ignore[arg-type]
        actor_id=row.actor_id,
        action=row.action,
        target_kind=row.target_kind,
        target_id=row.target_id,
        detail=dict(row.detail or {}),
        ip=row.ip,
        created_at=ensure_aware(row.created_at),
    )


class AuditRepository:
    """审计仓储。**只有 add 和 list**——已写入的记录不可改、不可删。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditRow(
                id=entry.id,
                workspace_id=entry.workspace_id,
                actor_kind=entry.actor_kind,
                actor_id=entry.actor_id,
                action=entry.action,
                target_kind=entry.target_kind,
                target_id=entry.target_id,
                detail=dict(entry.detail),
                ip=entry.ip,
            )
        )

    async def list_recent(
        self, *, workspace_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[AuditEntry]:
        """按工作区读流水。

        **登录这类跨工作区的事件 `workspace_id` 为空，一并返回**——否则运营者
        在任一工作区视图里都看不到认证事件，而那恰恰是最该看的一类。
        """
        stmt = select(AuditRow).order_by(AuditRow.created_at.desc())
        if workspace_id is not None:
            stmt = stmt.where(
                or_(AuditRow.workspace_id == workspace_id, AuditRow.workspace_id.is_(None))
            )
        stmt = stmt.limit(limit).offset(offset)
        return [_audit(row) for row in (await self._session.execute(stmt)).scalars().all()]

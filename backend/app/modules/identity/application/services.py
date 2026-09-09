"""identity 用例。

会话是**服务端状态**：Cookie 里只有随机 token，库里只存 sha256。
工作区由请求头 `x-workspace-id` 选择，解析会话时一并校验成员资格。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from ....contracts.common import Id, OrgRole, WorkspaceRole
from ....contracts.errors import DomainError, Errors, NotFound, WorkspaceMismatch
from ....contracts.identity import ActorContext, MemberRef, Subject
from ....persistence import Database, UnitOfWork
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.models import (
    Membership,
    Organization,
    OrganizationMembership,
    Session,
    Tenant,
    User,
    Workspace,
)
from ..domain.authorizer import Authorizer
from ..infrastructure.repositories import (
    MembershipRepository,
    OrganizationMembershipRepository,
    OrganizationRepository,
    SessionRepository,
    TenantRepository,
    UserRepository,
    WorkspaceRepository,
)
from ..infrastructure.security import hash_token, new_session_token, verify_password

#: 登录失败一律返回同一句话，避免枚举出哪些账号存在。
_BAD_CREDENTIALS = "用户名或密码错误"


class IdentityService:
    """实现 `contracts.identity.AuthContextPort` 与 `TenantProvisioningPort`。"""
    def __init__(
        self,
        database: Database,
        clock: Clock,
        authorizer: Authorizer,
        *,
        session_idle_hours: int = 4,
        session_absolute_hours: int = 24,
    ) -> None:
        self._db = database
        self._clock = clock
        self._authorizer = authorizer
        self._idle = timedelta(hours=session_idle_hours)
        self._absolute = timedelta(hours=session_absolute_hours)

    # -- 认证 ----------------------------------------------------------------

    async def login_local(
        self,
        identifier: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[User, str]:
        """返回 (用户, 会话明文 token)。明文只在此刻存在一次。"""
        now = self._clock.now()
        raw_token = new_session_token()
        async with UnitOfWork(self._db) as uow:
            users = UserRepository(uow.session)
            user = await users.find_by_identifier(identifier)
            if user is None or not user.can_login_with_password():
                raise DomainError(Errors.UNAUTHENTICATED, _BAD_CREDENTIALS)
            if not verify_password(user.password_hash, password):
                raise DomainError(Errors.UNAUTHENTICATED, _BAD_CREDENTIALS)

            SessionRepository(uow.session).add(
                Session(
                    id=new_id("session"),
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    auth_method="password",
                    provider_id=None,
                    created_at=now,
                    expires_at=now + self._absolute,
                    last_seen_at=now,
                    user_agent=user_agent,
                    ip=ip,
                )
            )
            await uow.commit()
        return user, raw_token

    async def resolve(
        self, raw_token: str, workspace_ref: str | None
    ) -> ActorContext | None:
        """校验会话 + 工作区成员资格。任一步不通过都返回 None / 抛错。"""
        if not raw_token:
            return None
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            sessions = SessionRepository(uow.session)
            session = await sessions.get_by_token_hash(hash_token(raw_token))
            if session is None:
                return None
            if session.is_expired(now, self._idle):
                await sessions.revoke(session.id, now)
                await uow.commit()
                return None

            user = await UserRepository(uow.session).get(session.user_id)
            if user is None or not user.is_active:
                return None

            workspaces = WorkspaceRepository(uow.session)
            workspace = await self._resolve_workspace(workspaces, user.id, workspace_ref)
            membership = await MembershipRepository(uow.session).get(workspace.id, user.id)
            if membership is None:
                raise WorkspaceMismatch("工作区", workspace.id)

            await sessions.touch(session.id, now)
            await uow.commit()

        subject = Subject(
            kind="user",
            id=user.id,
            workspace_id=workspace.id,
            role=membership.role,
            tenant_scope=membership.tenant_scope,
        )
        return ActorContext(
            user_id=user.id,
            display_name=user.display_name,
            email=user.email,
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            role=membership.role,
            subject=subject,
        )

    async def logout(self, raw_token: str) -> None:
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            sessions = SessionRepository(uow.session)
            session = await sessions.get_by_token_hash(hash_token(raw_token))
            if session is not None:
                await sessions.revoke(session.id, now)
                await uow.commit()

    async def revoke_user_sessions(self, user_id: Id, reason: str) -> int:
        """成员被移除 / 角色变更 / 用户停用时调用（架构文档 §5.1.3）。"""
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            count = await SessionRepository(uow.session).revoke_user_sessions(user_id, now)
            await uow.commit()
        return count

    # -- 查询 ----------------------------------------------------------------

    async def list_workspaces(self, user_id: Id) -> list[Workspace]:
        async with UnitOfWork(self._db) as uow:
            return list(await WorkspaceRepository(uow.session).list_for_user(user_id))

    # -- 租户 ----------------------------------------------------------------

    async def ensure_tenant(self, workspace_id: Id, external_key: str, name: str) -> Id:
        """按 `(workspace_id, external_key)` 幂等取用租户，返回租户 ID。

        M1 只有签发 SDK 密钥时会用到，自动建一个默认租户；
        完整租户同步接口（`PUT /v1/tenants`）到 M4。
        """
        async with UnitOfWork(self._db) as uow:
            tenants = TenantRepository(uow.session)
            tenant = await tenants.get_by_external_key(workspace_id, external_key)
            if tenant is None:
                tenant = Tenant(
                    id=new_id("tenant"),
                    workspace_id=workspace_id,
                    external_key=external_key,
                    name=name,
                    status="active",
                    created_at=self._clock.now(),
                )
                tenants.add(tenant)
                await uow.commit()
        return tenant.id

    async def get_user(self, user_id: Id) -> User | None:
        async with UnitOfWork(self._db) as uow:
            return await UserRepository(uow.session).get(user_id)

    async def role_map(self, user_id: Id) -> dict[str, str]:
        """workspace_id → 角色，供登录响应一次性带上。"""
        async with UnitOfWork(self._db) as uow:
            memberships = await MembershipRepository(uow.session).list_for_user(user_id)
        return {m.workspace_id: m.role.value for m in memberships}

    def permissions_of(self, subject: Subject):
        return self._authorizer.permissions_of(subject)

    # -- 组织 ----------------------------------------------------------------

    async def list_organizations(self, user_id: Id) -> Sequence[Organization]:
        async with UnitOfWork(self._db) as uow:
            return list(await OrganizationRepository(uow.session).list_for_user(user_id))

    async def org_role_of(self, organization_id: Id, user_id: Id) -> OrgRole | None:
        async with UnitOfWork(self._db) as uow:
            membership = await OrganizationMembershipRepository(uow.session).get(
                organization_id, user_id
            )
        return membership.role if membership else None

    async def list_org_members(
        self, organization_id: Id
    ) -> Sequence[tuple[OrganizationMembership, User]]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await OrganizationMembershipRepository(uow.session).list_members(
                    organization_id
                )
            )

    async def add_org_member(
        self, organization_id: Id, identifier: str, role: OrgRole
    ) -> OrganizationMembership:
        """按用户名或邮箱把已有账号加进组织。"""
        async with UnitOfWork(self._db) as uow:
            users = UserRepository(uow.session)
            user = await users.find_by_identifier(identifier)
            if user is None:
                raise NotFound("用户", identifier)
            memberships = OrganizationMembershipRepository(uow.session)
            if await memberships.get(organization_id, user.id) is not None:
                raise DomainError(
                    Errors.VALIDATION_FAILED, f"{identifier} 已经是该组织成员"
                )
            membership = OrganizationMembership(
                organization_id=organization_id,
                user_id=user.id,
                role=role,
                created_at=self._clock.now(),
            )
            memberships.add(membership)
            await uow.commit()
        return membership

    async def set_org_member_role(
        self, organization_id: Id, user_id: Id, role: OrgRole
    ) -> None:
        async with UnitOfWork(self._db) as uow:
            await OrganizationMembershipRepository(uow.session).set_role(
                organization_id, user_id, role
            )
            await uow.commit()

    async def remove_org_member(self, organization_id: Id, user_id: Id) -> None:
        async with UnitOfWork(self._db) as uow:
            await OrganizationMembershipRepository(uow.session).remove(
                organization_id, user_id
            )
            await uow.commit()

    async def create_workspace(
        self, *, organization_id: Id, owner_id: Id, slug: str, name: str
    ) -> Workspace:
        """建项目，并把创建者设为项目 owner。"""
        async with UnitOfWork(self._db) as uow:
            workspaces = WorkspaceRepository(uow.session)
            if await workspaces.get_by_slug(slug) is not None:
                raise DomainError(Errors.VALIDATION_FAILED, f"项目标识 {slug} 已存在")
            workspace = Workspace(
                id=new_id("workspace"),
                organization_id=organization_id,
                slug=slug,
                name=name,
                created_at=self._clock.now(),
            )
            workspaces.add(workspace)
            await uow.session.flush()
            MembershipRepository(uow.session).add(
                Membership(
                    workspace_id=workspace.id,
                    user_id=owner_id,
                    role=WorkspaceRole.OWNER,
                    tenant_scope="all",
                    created_at=self._clock.now(),
                )
            )
            await uow.commit()
        return workspace

    # -- 工作区成员（实现 contracts.identity.MembershipQueryPort）---------------

    async def is_member(self, user_id: Id, workspace_id: Id) -> bool:
        async with UnitOfWork(self._db) as uow:
            return (
                await MembershipRepository(uow.session).get(workspace_id, user_id)
            ) is not None

    async def list_members(self, workspace_id: Id) -> Sequence[MemberRef]:
        async with UnitOfWork(self._db) as uow:
            rows = await MembershipRepository(uow.session).list_members(workspace_id)
        return [
            MemberRef(
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
                role=membership.role,
            )
            for membership, user in rows
        ]

    async def add_workspace_member(
        self, workspace_id: Id, identifier: str, role: WorkspaceRole
    ) -> MemberRef:
        async with UnitOfWork(self._db) as uow:
            user = await UserRepository(uow.session).find_by_identifier(identifier)
            if user is None:
                raise NotFound("用户", identifier)
            memberships = MembershipRepository(uow.session)
            if await memberships.get(workspace_id, user.id) is not None:
                raise DomainError(Errors.VALIDATION_FAILED, f"{identifier} 已是本项目成员")
            memberships.add(
                Membership(
                    workspace_id=workspace_id,
                    user_id=user.id,
                    role=role,
                    tenant_scope="all",
                    created_at=self._clock.now(),
                )
            )
            await uow.commit()
        return MemberRef(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=role,
        )

    async def set_workspace_member_role(
        self, workspace_id: Id, user_id: Id, role: WorkspaceRole
    ) -> None:
        async with UnitOfWork(self._db) as uow:
            await MembershipRepository(uow.session).set_role(workspace_id, user_id, role)
            await uow.commit()
        # 角色变了，旧会话里的权限快照作废
        await self.revoke_user_sessions(user_id, "role changed")

    async def remove_workspace_member(self, workspace_id: Id, user_id: Id) -> None:
        async with UnitOfWork(self._db) as uow:
            await MembershipRepository(uow.session).remove(workspace_id, user_id)
            await uow.commit()
        await self.revoke_user_sessions(user_id, "removed from workspace")

    async def _resolve_workspace(
        self, workspaces: WorkspaceRepository, user_id: Id, ref: str | None
    ) -> Workspace:
        """`x-workspace-id` 允许传 ID 或 slug；缺省时回退到用户的第一个工作区。"""
        if ref:
            workspace = await workspaces.get(ref) or await workspaces.get_by_slug(ref)
            if workspace is None:
                raise NotFound("工作区", ref)
            return workspace
        owned = await workspaces.list_for_user(user_id)
        if not owned:
            raise NotFound("工作区", "(该用户没有任何工作区)")
        return owned[0]

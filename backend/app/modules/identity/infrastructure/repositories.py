"""仓储：ORM 行 ↔ 领域实体。

仓储只碰本模块前缀的表；跨模块读一律走 `contracts/` 里的 Port。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import WorkspaceRole
from ....shared.clock import ensure_aware
from ..domain.models import (
    Membership,
    Session,
    Tenant,
    TenantScope,
    User,
    UserStatus,
    Workspace,
)
from .tables import MembershipRow, SessionRow, TenantRow, UserRow, WorkspaceRow


def _scope_from_json(raw: Any) -> TenantScope:
    if raw == "all" or raw is None:
        return "all"
    return tuple(str(item) for item in raw)


def _scope_to_json(scope: TenantScope) -> Any:
    return "all" if scope == "all" else list(scope)


# --------------------------------------------------------------------------- #
# 映射
# --------------------------------------------------------------------------- #


def _user(row: UserRow) -> User:
    return User(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        email=row.email,
        password_hash=row.password_hash,
        status=row.status,  # type: ignore[arg-type]
        created_at=ensure_aware(row.created_at),
    )


def _workspace(row: WorkspaceRow) -> Workspace:
    return Workspace(
        id=row.id, slug=row.slug, name=row.name, created_at=ensure_aware(row.created_at)
    )


def _membership(row: MembershipRow) -> Membership:
    return Membership(
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        role=WorkspaceRole(row.role),
        tenant_scope=_scope_from_json(row.tenant_scope),
        created_at=ensure_aware(row.created_at),
    )


def _tenant(row: TenantRow) -> Tenant:
    return Tenant(
        id=row.id,
        workspace_id=row.workspace_id,
        external_key=row.external_key,
        name=row.name,
        status=row.status,  # type: ignore[arg-type]
        created_at=ensure_aware(row.created_at),
    )


def _session(row: SessionRow) -> Session:
    # SQLite 不保存时区，读回来是 naive——不补 UTC 会与 Clock 的 aware 时间比较时报 TypeError。
    return Session(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        auth_method=row.auth_method,  # type: ignore[arg-type]
        provider_id=row.provider_id,
        created_at=ensure_aware(row.created_at),
        expires_at=ensure_aware(row.expires_at),
        last_seen_at=ensure_aware(row.last_seen_at),
        user_agent=row.user_agent,
        ip=row.ip,
    )


# --------------------------------------------------------------------------- #
# 仓储
# --------------------------------------------------------------------------- #


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: str) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return _user(row) if row else None

    async def find_by_identifier(self, identifier: str) -> User | None:
        """identifier 支持用户名或邮箱——`register.py` 与前端登录页都用这个。"""
        stmt = select(UserRow).where(
            (UserRow.username == identifier) | (UserRow.email == identifier)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _user(row) if row else None

    def add(self, user: User) -> None:
        self._session.add(
            UserRow(
                id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                password_hash=user.password_hash,
                status=user.status,
            )
        )

    async def update_password(self, user_id: str, password_hash: str) -> None:
        await self._session.execute(
            update(UserRow).where(UserRow.id == user_id).values(password_hash=password_hash)
        )

    async def set_status(self, user_id: str, status: UserStatus) -> None:
        await self._session.execute(
            update(UserRow).where(UserRow.id == user_id).values(status=status)
        )


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, workspace_id: str) -> Workspace | None:
        row = await self._session.get(WorkspaceRow, workspace_id)
        return _workspace(row) if row else None

    async def get_by_slug(self, slug: str) -> Workspace | None:
        stmt = select(WorkspaceRow).where(WorkspaceRow.slug == slug)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _workspace(row) if row else None

    async def list_for_user(self, user_id: str) -> Sequence[Workspace]:
        stmt = (
            select(WorkspaceRow)
            .join(MembershipRow, MembershipRow.workspace_id == WorkspaceRow.id)
            .where(MembershipRow.user_id == user_id)
            .order_by(WorkspaceRow.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_workspace(row) for row in rows]

    def add(self, workspace: Workspace) -> None:
        self._session.add(
            WorkspaceRow(id=workspace.id, slug=workspace.slug, name=workspace.name)
        )


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, workspace_id: str, user_id: str) -> Membership | None:
        stmt = select(MembershipRow).where(
            MembershipRow.workspace_id == workspace_id,
            MembershipRow.user_id == user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _membership(row) if row else None

    async def list_for_user(self, user_id: str) -> Sequence[Membership]:
        stmt = select(MembershipRow).where(MembershipRow.user_id == user_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_membership(row) for row in rows]

    def add(self, membership: Membership) -> None:
        self._session.add(
            MembershipRow(
                id=f"{membership.workspace_id}:{membership.user_id}",
                workspace_id=membership.workspace_id,
                user_id=membership.user_id,
                role=membership.role.value,
                tenant_scope=_scope_to_json(membership.tenant_scope),
            )
        )


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: str) -> Tenant | None:
        row = await self._session.get(TenantRow, tenant_id)
        return _tenant(row) if row else None

    async def get_by_external_key(self, workspace_id: str, external_key: str) -> Tenant | None:
        stmt = select(TenantRow).where(
            TenantRow.workspace_id == workspace_id, TenantRow.external_key == external_key
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _tenant(row) if row else None

    async def list_for_workspace(self, workspace_id: str) -> Sequence[Tenant]:
        stmt = select(TenantRow).where(TenantRow.workspace_id == workspace_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_tenant(row) for row in rows]

    def add(self, tenant: Tenant) -> None:
        self._session.add(
            TenantRow(
                id=tenant.id,
                workspace_id=tenant.workspace_id,
                external_key=tenant.external_key,
                name=tenant.name,
                status=tenant.status,
            )
        )


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, session: Session) -> None:
        self._session.add(
            SessionRow(
                id=session.id,
                user_id=session.user_id,
                token_hash=session.token_hash,
                auth_method=session.auth_method,
                provider_id=session.provider_id,
                expires_at=session.expires_at,
                last_seen_at=session.last_seen_at,
                user_agent=session.user_agent,
                ip=session.ip,
            )
        )

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        stmt = select(SessionRow).where(
            SessionRow.token_hash == token_hash, SessionRow.revoked_at.is_(None)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _session(row) if row else None

    async def touch(self, session_id: str, now: datetime) -> None:
        await self._session.execute(
            update(SessionRow).where(SessionRow.id == session_id).values(last_seen_at=now)
        )

    async def revoke(self, session_id: str, now: datetime) -> None:
        await self._session.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_user_sessions(self, user_id: str, now: datetime) -> int:
        result = await self._session.execute(
            update(SessionRow)
            .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return int(result.rowcount or 0)

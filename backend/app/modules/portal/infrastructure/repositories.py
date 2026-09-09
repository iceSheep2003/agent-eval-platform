"""portal 仓储：ORM 行 ↔ 领域实体。"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import Channel
from ....shared.clock import ensure_aware
from ..domain.models import (
    PortalAgentChannel,
    PortalProject,
    PortalSession,
    PortalUser,
    ProjectAgent,
    ProjectMember,
)
from .tables import (
    PortalAgentChannelRow,
    PortalProjectRow,
    PortalSessionRow,
    PortalUserRow,
    ProjectAgentRow,
    ProjectMemberRow,
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


def _project(row: PortalProjectRow) -> PortalProject:
    return PortalProject(
        id=row.id,
        workspace_id=row.workspace_id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        status=row.status,  # type: ignore[arg-type]
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
    )


def _member(row: ProjectMemberRow) -> ProjectMember:
    return ProjectMember(
        id=row.id,
        project_id=row.project_id,
        portal_user_id=row.portal_user_id,
        role=row.role,  # type: ignore[arg-type]
        created_at=ensure_aware(row.created_at),
    )


def _project_agent(row: ProjectAgentRow) -> ProjectAgent:
    return ProjectAgent(
        id=row.id,
        project_id=row.project_id,
        asset_id=row.asset_id,
        display_name=row.display_name,
        sort_order=row.sort_order,
        created_at=ensure_aware(row.created_at),
    )


def _channel(row: PortalAgentChannelRow) -> PortalAgentChannel:
    return PortalAgentChannel(
        id=row.id,
        project_agent_id=row.project_agent_id,
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


class PortalProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: str, workspace_id: str) -> PortalProject | None:
        stmt = select(PortalProjectRow).where(
            PortalProjectRow.id == project_id,
            PortalProjectRow.workspace_id == workspace_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _project(row) if row else None

    async def get_any(self, project_id: str) -> PortalProject | None:
        """按 ID 取，不限定工作区。调用方必须自己保证授权（portal 侧靠成员校验）。"""
        row = await self._session.get(PortalProjectRow, project_id)
        return _project(row) if row else None

    async def find_by_slug(self, workspace_id: str, slug: str) -> PortalProject | None:
        stmt = select(PortalProjectRow).where(
            PortalProjectRow.workspace_id == workspace_id, PortalProjectRow.slug == slug
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _project(row) if row else None

    async def list_for_workspace(self, workspace_id: str) -> Sequence[PortalProject]:
        stmt = (
            select(PortalProjectRow)
            .where(PortalProjectRow.workspace_id == workspace_id)
            .order_by(PortalProjectRow.created_at.desc())
        )
        return [_project(row) for row in (await self._session.execute(stmt)).scalars().all()]

    async def list_for_user(
        self, portal_user_id: str
    ) -> Sequence[tuple[PortalProject, str]]:
        """只返回该用户是成员的项目——展示平台的可见性边界。

        连同**项目角色**一起返回：前端要按角色决定是否显示管理入口，
        分开查会变成 N+1。
        """
        stmt = (
            select(PortalProjectRow, ProjectMemberRow.role)
            .join(ProjectMemberRow, ProjectMemberRow.project_id == PortalProjectRow.id)
            .where(ProjectMemberRow.portal_user_id == portal_user_id)
            .order_by(PortalProjectRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(_project(row[0]), str(row[1])) for row in rows]

    def add(self, project: PortalProject) -> None:
        self._session.add(
            PortalProjectRow(
                id=project.id,
                workspace_id=project.workspace_id,
                slug=project.slug,
                name=project.name,
                description=project.description,
                status=project.status,
                created_by=project.created_by,
            )
        )


class ProjectMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: str, portal_user_id: str) -> ProjectMember | None:
        stmt = select(ProjectMemberRow).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.portal_user_id == portal_user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _member(row) if row else None

    async def list_for_project(self, project_id: str) -> Sequence[ProjectMember]:
        stmt = select(ProjectMemberRow).where(ProjectMemberRow.project_id == project_id)
        return [_member(row) for row in (await self._session.execute(stmt)).scalars().all()]

    def add(self, member: ProjectMember) -> None:
        self._session.add(
            ProjectMemberRow(
                id=member.id,
                project_id=member.project_id,
                portal_user_id=member.portal_user_id,
                role=member.role,
            )
        )

    async def remove(self, member_id: str) -> None:
        row = await self._session.get(ProjectMemberRow, member_id)
        if row is not None:
            await self._session.delete(row)


class ProjectAgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_agent_id: str) -> ProjectAgent | None:
        row = await self._session.get(ProjectAgentRow, project_agent_id)
        return _project_agent(row) if row else None

    async def list_for_project(self, project_id: str) -> Sequence[ProjectAgent]:
        stmt = (
            select(ProjectAgentRow)
            .where(ProjectAgentRow.project_id == project_id)
            .order_by(ProjectAgentRow.sort_order, ProjectAgentRow.created_at)
        )
        return [
            _project_agent(row)
            for row in (await self._session.execute(stmt)).scalars().all()
        ]

    async def find(self, project_id: str, asset_id: str) -> ProjectAgent | None:
        stmt = select(ProjectAgentRow).where(
            ProjectAgentRow.project_id == project_id,
            ProjectAgentRow.asset_id == asset_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _project_agent(row) if row else None

    def add(self, project_agent: ProjectAgent) -> None:
        self._session.add(
            ProjectAgentRow(
                id=project_agent.id,
                project_id=project_agent.project_id,
                asset_id=project_agent.asset_id,
                display_name=project_agent.display_name,
                sort_order=project_agent.sort_order,
            )
        )


class PortalAgentChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_agent_id: str, channel: Channel) -> PortalAgentChannel | None:
        stmt = select(PortalAgentChannelRow).where(
            PortalAgentChannelRow.project_agent_id == project_agent_id,
            PortalAgentChannelRow.channel == channel.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _channel(row) if row else None

    async def list_for_agent(self, project_agent_id: str) -> Sequence[PortalAgentChannel]:
        stmt = select(PortalAgentChannelRow).where(
            PortalAgentChannelRow.project_agent_id == project_agent_id
        )
        return [
            _channel(row) for row in (await self._session.execute(stmt)).scalars().all()
        ]

    async def upsert(self, binding: PortalAgentChannel) -> None:
        existing = await self.get(binding.project_agent_id, binding.channel)
        if existing is None:
            self._session.add(
                PortalAgentChannelRow(
                    id=binding.id,
                    project_agent_id=binding.project_agent_id,
                    channel=binding.channel.value,
                    deployment_credential_id=binding.deployment_credential_id,
                )
            )
            return
        row = await self._session.get(PortalAgentChannelRow, existing.id)
        if row is not None:
            row.deployment_credential_id = binding.deployment_credential_id

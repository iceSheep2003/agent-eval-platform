"""组织 → 项目 → 成员：两层角色、成员管理与负责人校验。

对齐 Langfuse 的三层：组织管成员与项目，项目管评测资产。
两套角色职责不同，不做跨层级的大小比较。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.container import Container
from backend.app.contracts.common import OrgRole, WorkspaceRole
from backend.app.contracts.errors import DomainError
from backend.app.seed import DEMO_ORG_SLUG, DEMO_WORKSPACE_SLUG, seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'org.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'org.db'}",
            master_key="test",
        ),
        clock=clock,
    )
    await container.startup()
    try:
        seeded = await seed(container)
        identity = container.identity
        admin_id = seeded["admin"]
        demo_id = seeded["demo"]
        workspace_id = seeded["workspace_id"]

        # 组织层
        organizations = await identity.list_organizations(admin_id)
        assert [item.slug for item in organizations] == [DEMO_ORG_SLUG]
        organization = organizations[0]
        assert await identity.org_role_of(organization.id, admin_id) is OrgRole.OWNER
        assert await identity.org_role_of(organization.id, demo_id) is OrgRole.MEMBER

        # 组织成员列表带用户信息
        org_members = await identity.list_org_members(organization.id)
        assert {user.username for _, user in org_members} == {"admin", "demo"}

        # 组织角色可改
        await identity.set_org_member_role(organization.id, demo_id, OrgRole.ADMIN)
        assert await identity.org_role_of(organization.id, demo_id) is OrgRole.ADMIN

        # 建项目：创建者自动成为项目 owner
        workspace = await identity.create_workspace(
            organization_id=organization.id,
            owner_id=admin_id,
            slug="team-b",
            name="Team B",
        )
        assert workspace.organization_id == organization.id
        members = await identity.list_members(workspace.id)
        assert [(m.username, m.role) for m in members] == [("admin", WorkspaceRole.OWNER)]

        # 项目成员管理
        added = await identity.add_workspace_member(
            workspace.id, "demo", WorkspaceRole.EVALUATOR
        )
        assert added.user_id == demo_id and added.role is WorkspaceRole.EVALUATOR
        assert await identity.is_member(demo_id, workspace.id)

        # 重复添加被拒
        with pytest.raises(DomainError):
            await identity.add_workspace_member(workspace.id, "demo", WorkspaceRole.VIEWER)

        # 不存在的账号被拒
        with pytest.raises(Exception):
            await identity.add_workspace_member(workspace.id, "ghost", WorkspaceRole.VIEWER)

        # 负责人必须是本工作区成员
        agent = await container.assets.register_agent(
            workspace_id=workspace.id,
            owner_id=demo_id,
            name="refund-agent",
            connect_type="sdk",
        )
        assert agent.owner_id == demo_id
        with pytest.raises(DomainError) as rejected:
            await container.assets.register_agent(
                workspace_id=workspace.id,
                owner_id="usr_nobody",
                name="bad-agent",
                connect_type="sdk",
            )
        assert rejected.value.code == "validation_failed"

        # 改角色会吊销该成员会话（权限快照作废）
        _, token = await identity.login_local("demo", "demo123")
        await identity.set_workspace_member_role(
            workspace.id, demo_id, WorkspaceRole.VIEWER
        )
        assert await identity.resolve(token, DEMO_WORKSPACE_SLUG) is None

        # 移除成员
        await identity.remove_workspace_member(workspace.id, demo_id)
        assert not await identity.is_member(demo_id, workspace.id)
    finally:
        await container.shutdown()


def test_org_member_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

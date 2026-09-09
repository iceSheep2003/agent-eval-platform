"""开发种子数据。

只用于本地：`python -m backend.app.seed`。幂等，可重复执行。
生产环境由管理员通过控制台创建，**不跑这个脚本**。
"""

from __future__ import annotations

import asyncio
import sys

from .container import Container
from .contracts.common import OrgRole, WorkspaceRole
from .modules.identity.domain.models import (
    Membership,
    Organization,
    OrganizationMembership,
    User,
    Workspace,
)
from .modules.identity.infrastructure.repositories import (
    MembershipRepository,
    OrganizationMembershipRepository,
    OrganizationRepository,
    UserRepository,
    WorkspaceRepository,
)
from .modules.identity.infrastructure.security import hash_password
from .persistence import UnitOfWork
from .shared.ids import new_id

DEMO_ORG_SLUG = "eval-loom"
DEMO_ORG_NAME = "Eval Loom"
DEMO_WORKSPACE_SLUG = "eval-dev"
DEMO_WORKSPACE_NAME = "Eval Dev"
DEMO_USERS = (
    ("admin", "admin123", "管理员", WorkspaceRole.OWNER),
    ("demo", "demo123", "演示账号", WorkspaceRole.EVALUATOR),
)


async def seed(container: Container) -> dict[str, str]:
    created: dict[str, str] = {}
    async with UnitOfWork(container.database) as uow:
        organizations = OrganizationRepository(uow.session)
        org_memberships = OrganizationMembershipRepository(uow.session)
        workspaces = WorkspaceRepository(uow.session)
        users = UserRepository(uow.session)
        memberships = MembershipRepository(uow.session)

        organization = await organizations.get_by_slug(DEMO_ORG_SLUG)
        if organization is None:
            organization = Organization(
                id=new_id("organization"),
                slug=DEMO_ORG_SLUG,
                name=DEMO_ORG_NAME,
                created_at=container.clock.now(),
            )
            organizations.add(organization)
        created["organization_id"] = organization.id

        workspace = await workspaces.get_by_slug(DEMO_WORKSPACE_SLUG)
        if workspace is None:
            workspace = Workspace(
                id=new_id("workspace"),
                organization_id=organization.id,
                slug=DEMO_WORKSPACE_SLUG,
                name=DEMO_WORKSPACE_NAME,
                created_at=container.clock.now(),
            )
            workspaces.add(workspace)
        created["workspace_id"] = workspace.id

        for username, password, display_name, role in DEMO_USERS:
            user = await users.find_by_identifier(username)
            if user is None:
                user = User(
                    id=new_id("user"),
                    username=username,
                    display_name=display_name,
                    email=f"{username}@eval-loom.local",
                    password_hash=hash_password(password),
                    status="active",
                    created_at=container.clock.now(),
                )
                users.add(user)
            if await org_memberships.get(organization.id, user.id) is None:
                org_memberships.add(
                    OrganizationMembership(
                        organization_id=organization.id,
                        user_id=user.id,
                        role=OrgRole.OWNER if role is WorkspaceRole.OWNER else OrgRole.MEMBER,
                        created_at=container.clock.now(),
                    )
                )
            if await memberships.get(workspace.id, user.id) is None:
                memberships.add(
                    Membership(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        role=role,
                        tenant_scope="all",
                        created_at=container.clock.now(),
                    )
                )
            created[username] = user.id

        await uow.commit()
    await _seed_evaluation(container, workspace)
    return created


#: 能力 → 维度（weight / threshold / 评估器），供前端目录页展示
DEMO_CAPABILITIES = (
    (
        "回答质量",
        "最终答案是否准确、完整、可读",
        (
            ("答案相关性", 0.6, 0.85, ("answer_exact_match", "llm_judge")),
            ("答案完整性", 0.4, 0.80, ("task_completion",)),
        ),
    ),
    (
        "工具使用",
        "是否调用了正确的工具、参数是否符合 Schema",
        (
            ("工具正确率", 0.7, 0.95, ("tool_name_correctness",)),
            ("参数合规率", 0.3, 0.95, ("tool_argument_schema",)),
        ),
    ),
)


async def _seed_evaluation(container: Container, workspace: Workspace) -> None:
    from .contracts.common import Determinism
    from .modules.evaluation.domain.models import Capability, ScoreDimension
    from .modules.evaluation.infrastructure.repositories import CapabilityRepository

    async with UnitOfWork(container.database) as uow:
        repo = CapabilityRepository(uow.session)
        existing = {item.name for item in await repo.list_for_workspace(workspace.id)}
        now = container.clock.now()
        for name, description, dimensions in DEMO_CAPABILITIES:
            if name in existing:
                continue
            capability = Capability(
                id=new_id("capability"),
                workspace_id=workspace.id,
                name=name,
                description=description,
                enabled=True,
                created_at=now,
            )
            repo.add(capability)
            for dim_name, weight, threshold, evaluators in dimensions:
                repo.add_dimension(
                    ScoreDimension(
                        id=new_id("dimension"),
                        capability_id=capability.id,
                        workspace_id=workspace.id,
                        name=dim_name,
                        weight=weight,
                        threshold=threshold,
                        evaluator_names=evaluators,
                        score=None,
                        created_at=now,
                    )
                )
        await uow.commit()


async def main() -> int:
    container = Container.build()
    await container.startup()
    try:
        created = await seed(container)
    finally:
        await container.shutdown()
    print(f"组织: {DEMO_ORG_SLUG} ({created['organization_id']})")
    print(f"工作区: {DEMO_WORKSPACE_SLUG} ({created['workspace_id']})")
    for username, password, _, role in DEMO_USERS:
        print(f"  {username} / {password}  role={role.value}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

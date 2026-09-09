"""开发种子数据。

只用于本地：`python -m backend.app.seed`。幂等，可重复执行。
生产环境由管理员通过控制台创建，**不跑这个脚本**。
"""

from __future__ import annotations

import asyncio
import sys

from .container import Container
from .contracts.common import WorkspaceRole
from .modules.identity.domain.models import Membership, User, Workspace
from .modules.identity.infrastructure.repositories import (
    MembershipRepository,
    UserRepository,
    WorkspaceRepository,
)
from .modules.identity.infrastructure.security import hash_password
from .persistence import UnitOfWork
from .shared.ids import new_id

DEMO_WORKSPACE_SLUG = "eval-dev"
DEMO_WORKSPACE_NAME = "Eval Dev"
DEMO_USERS = (
    ("admin", "admin123", "管理员", WorkspaceRole.OWNER),
    ("demo", "demo123", "演示账号", WorkspaceRole.EVALUATOR),
)


async def seed(container: Container) -> dict[str, str]:
    created: dict[str, str] = {}
    async with UnitOfWork(container.database) as uow:
        workspaces = WorkspaceRepository(uow.session)
        users = UserRepository(uow.session)
        memberships = MembershipRepository(uow.session)

        workspace = await workspaces.get_by_slug(DEMO_WORKSPACE_SLUG)
        if workspace is None:
            workspace = Workspace(
                id=new_id("workspace"),
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
    return created


async def main() -> int:
    container = Container.build()
    await container.startup()
    try:
        created = await seed(container)
    finally:
        await container.shutdown()
    print(f"工作区: {DEMO_WORKSPACE_SLUG} ({created['workspace_id']})")
    for username, password, _, role in DEMO_USERS:
        print(f"  {username} / {password}  role={role.value}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

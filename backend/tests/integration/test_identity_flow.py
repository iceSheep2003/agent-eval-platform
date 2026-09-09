"""M0 验收：登录 → 会话解析 → 权限，跑真实 SQLite。

覆盖两个容易回归的点：
1. SQLite 不存时区，会话时间读回来是 naive，与 Clock 的 aware 时间比较会 TypeError；
2. 工作区隔离——未知工作区必须报错，而不是静默回退到别的租户数据。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.container import Container
from backend.app.contracts.common import WorkspaceRole
from backend.app.contracts.errors import DomainError, NotFound
from backend.app.contracts.identity import Permission
from backend.app.modules.identity.domain.authorizer import Authorizer
from backend.app.seed import DEMO_WORKSPACE_SLUG, seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def _settings(tmp_path) -> Settings:
    return Settings(
        env="development",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        master_key="test-master-key",
    )


async def _scenario(tmp_path) -> None:
    container = Container.build(_settings(tmp_path), clock=FixedClock())
    await container.startup()
    try:
        await seed(container)
        identity = container.identity

        # 登录
        user, token = await identity.login_local("admin", "admin123")
        assert user.username == "admin"
        assert token

        # 会话解析 + 工作区选择（用 slug，不是 ID）
        context = await identity.resolve(token, DEMO_WORKSPACE_SLUG)
        assert context is not None
        assert context.user_id == user.id
        assert context.role is WorkspaceRole.OWNER
        assert context.subject.workspace_id == context.workspace_id

        # 权限点
        permissions = identity.permissions_of(context.subject)
        assert Permission.VERSION_PROMOTE_LIVE in permissions
        assert Permission.TENANT_PURGE in permissions

        # 错误密码不区分「用户不存在」与「密码错」
        with pytest.raises(DomainError) as wrong:
            await identity.login_local("admin", "nope")
        with pytest.raises(DomainError) as missing:
            await identity.login_local("ghost", "nope")
        assert str(wrong.value) == str(missing.value)

        # 未知工作区必须报错，不能回退
        with pytest.raises(NotFound):
            await identity.resolve(token, "does-not-exist")

        # 登出后会话失效
        await identity.logout(token)
        assert await identity.resolve(token, DEMO_WORKSPACE_SLUG) is None

        # 无效 token 直接返回 None
        assert await identity.resolve("garbage", DEMO_WORKSPACE_SLUG) is None

        # 权限判定与工作区隔离
        authorizer = Authorizer()
        decision = authorizer.decide(
            context.subject, Permission.ASSET_READ, None
        )
        assert decision.allowed
    finally:
        await container.shutdown()


def test_identity_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

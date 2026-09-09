"""展示平台的账号安全：登录锁定、禁用即踢、吊销全部会话。

这三条是「多用户隔离」里最容易被忽略的一环——**隔离不只是看不到别人的数据，
还包括别人的账号被攻破/被停用时能立刻止损**。
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.container import Container
from backend.app.main import create_app
from backend.app.modules.portal.domain.models import MAX_FAILED_ATTEMPTS
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

PASSWORD = "portal-pass-123"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'iso.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _login(client: httpx.AsyncClient, username: str, password: str):
    return await client.post(
        "/api/portal/auth/login", json={"identifier": username, "password": password}
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        app = create_app(container)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/auth/login", json={"identifier": "admin", "password": "admin123"}
            )
            created = await client.post(
                "/api/portal-admin/users",
                json={"username": "carol", "display_name": "Carol", "password": PASSWORD},
            )
            carol_id = created.json()["data"]["id"]

        # -- 1. 连续失败锁定，正确密码也进不去 -----------------------------
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(MAX_FAILED_ATTEMPTS):
                wrong = await _login(client, "carol", "not-the-password")
                assert wrong.status_code == 401
            blocked = await _login(client, "carol", PASSWORD)
            assert blocked.status_code == 401, "锁定期间正确密码也必须被拒"

            # -- 2. 锁到期后恢复 ------------------------------------------
            clock.advance(minutes=16)
            recovered = await _login(client, "carol", PASSWORD)
            assert recovered.status_code == 200, recovered.text

            # 成功登录清零计数
            stored = await container.portal_auth.get_user(carol_id)
            assert stored.failed_attempts == 0

        # -- 3. 禁用账号 → 已有会话立刻失效 --------------------------------
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await _login(client, "carol", PASSWORD)
            assert (await client.get("/api/portal/me")).status_code == 200

            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as operator:
                await operator.post(
                    "/api/auth/login",
                    json={"identifier": "admin", "password": "admin123"},
                )
                disabled = await operator.post(
                    f"/api/portal-admin/users/{carol_id}/status",
                    json={"status": "disabled"},
                )
                assert disabled.status_code == 200, disabled.text

            # carol 的 cookie 还在，但服务端会话已被删 + 账号已停用
            assert (await client.get("/api/portal/me")).status_code == 401

        # -- 4. 重新启用后可再登录，但旧会话不会复活 ------------------------
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as operator:
            await operator.post(
                "/api/auth/login", json={"identifier": "admin", "password": "admin123"}
            )
            await operator.post(
                f"/api/portal-admin/users/{carol_id}/status", json={"status": "active"}
            )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await _login(client, "carol", PASSWORD)).status_code == 200
            assert (await client.get("/api/portal/me")).status_code == 200
    finally:
        await container.shutdown()


def test_portal_account_safety(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

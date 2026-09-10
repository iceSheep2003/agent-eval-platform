"""Agent 开发规范验收。

三道关口，任何一道都不能形同虚设：
1. **冻结版本前**：明文密钥、缺 memory 声明 → 直接拒绝建版本；
2. **验收接口**：真的 import entrypoint 看签名，报出不符合协议的形参；
3. **`sdk` 接入**：Agent 自己跑、自己管记忆，不该被平台托管规范卡住。
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.container import Container
from backend.app.contracts.errors import DomainError
from backend.app.main import create_app
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def compliant_agent(input: str, messages: object = None) -> str:  # noqa: A002
    """合规：接受 input 与 messages。"""
    return f"ok:{input}"


def legacy_agent(query: str) -> str:
    """不合规：形参叫 query，平台按 `input` 传值会 TypeError。"""
    return f"legacy:{query}"


COMPLIANT = f"{__name__}:compliant_agent"
LEGACY = f"{__name__}:legacy_agent"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'conf.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]

        # -- 1. 明文密钥被拒：版本不可变，冻结就换不掉了 -------------------
        with_error: DomainError | None = None
        try:
            await container.assets.register_agent(
                workspace_id=workspace_id,
                owner_id=owner,
                name="plaintext-secret-agent",
                connect_type="package",
                source={
                    "artifact_id": "x",
                    "entrypoint": COMPLIANT,
                    "memory": {"scope": "stateless"},
                    "mcp_servers": [
                        {"endpoint": "https://x", "authentication": {"api_key": "sk-live-123"}}
                    ],
                },
            )
        except DomainError as exc:
            with_error = exc
        assert with_error is not None, "明文密钥应当被拒"
        assert "secret_ref" in str(with_error), str(with_error)

        # -- 2. 缺 memory 声明被拒（平台托管类）----------------------------
        missing_memory: DomainError | None = None
        try:
            await container.assets.register_agent(
                workspace_id=workspace_id,
                owner_id=owner,
                name="no-memory-agent",
                connect_type="package",
                source={"artifact_id": "x", "entrypoint": COMPLIANT},
            )
        except DomainError as exc:
            missing_memory = exc
        assert missing_memory is not None, "缺 memory 声明应当被拒"
        assert "memory" in str(missing_memory)

        # -- 3. 合规 Agent 建得出来 ----------------------------------------
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="good-agent",
            connect_type="package",
            source={
                "artifact_id": "x",
                "entrypoint": COMPLIANT,
                "memory": {"scope": "thread"},
            },
        )
        version = (await container.assets.list_versions(agent.id, workspace_id))[0]

        # -- 4. 验收接口：合规通过 -----------------------------------------
        app = create_app(container)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/login", json={"identifier": "admin", "password": "admin123"}
            )
            good = await client.get(
                f"/api/agents/{agent.id}/versions/{version.id}/conformance"
            )
            assert good.status_code == 200, good.text
            assert good.json()["data"]["passed"] is True, good.text

            # -- 5. 验收接口：不合规报出具体字段 ---------------------------
            legacy = await container.assets.create_version(
                asset_id=agent.id,
                workspace_id=workspace_id,
                created_by=owner,
                spec={
                    "kind": "agent",
                    "connect_type": "package",
                    "artifact_id": "y",
                    "entrypoint": LEGACY,
                    "memory": {"scope": "thread"},
                },
            )
            bad = await client.get(
                f"/api/agents/{agent.id}/versions/{legacy.id}/conformance"
            )
            assert bad.status_code == 200, bad.text
            payload = bad.json()["data"]
            assert payload["passed"] is False
            fields = {item["field"] for item in payload["issues"]}
            assert "entrypoint.input" in fields, payload
            assert "entrypoint.messages" in fields, payload

        # -- 6. sdk 接入不受托管规范约束 -----------------------------------
        sdk_agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="sdk-agent",
            connect_type="sdk",
        )
        sdk_version = (await container.assets.list_versions(sdk_agent.id, workspace_id))[0]
        assert await container.assets.check_conformance(sdk_version.id, workspace_id)
    finally:
        await container.shutdown()


def test_agent_conformance(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

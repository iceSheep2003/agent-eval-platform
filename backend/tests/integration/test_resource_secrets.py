"""资源密钥：加密存储、按通道绑定、运行时注入。

四条硬约束：
1. 库里存的是密文——`fingerprint` 之外看不到明文；
2. 按「版本 × 通道」解析，**同名密钥在不同通道可以是不同的值**（测试/生产分离）；
3. `required` 的密钥没绑 → 调用**直接失败**，不静默少给；
4. 明文真的注入到了 Agent 的 `secrets` 形参里。
"""

from __future__ import annotations

import asyncio

from backend.app.container import Container
from backend.app.contracts.common import Channel
from backend.app.contracts.errors import DomainError, Errors
from backend.app.contracts.execution import ChannelInvocation
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

RECEIVED: dict[str, object] = {}

ENTRYPOINT = f"{__name__}:secret_agent"


def secret_agent(input: str, secrets: dict = None) -> str:  # noqa: A002
    RECEIVED.clear()
    RECEIVED.update(secrets or {})
    return f"key={((secrets or {}).get('llm_api_key') or '')[:8]}"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sec.db'}",
            master_key="test-master-key",
        ),
        clock=clock,
    )


async def _register(container: Container, workspace_id: str, owner: str):
    return await container.assets.register_agent(
        workspace_id=workspace_id,
        owner_id=owner,
        name="secret-agent",
        connect_type="package",
        source={
            "artifact_id": "a-1",
            "entrypoint": ENTRYPOINT,
            "memory": {"scope": "stateless"},
            "secrets": [{"name": "llm_api_key", "required": True}],
        },
    )


async def _invoke(container: Container, agent_id: str, workspace_id: str, channel: Channel):
    return await container.invoke.invoke_channel(
        ChannelInvocation(
            workspace_id=workspace_id,
            asset_id=agent_id,
            channel=channel,
            input="问",
        )
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        agent = await _register(container, workspace_id, owner)
        version = (await container.assets.list_versions(agent.id, workspace_id))[0]
        for channel in (Channel.TEST, Channel.LIVE):
            await container.assets.bind_channel(
                asset_id=agent.id,
                channel=channel,
                version_id=version.id,
                workspace_id=workspace_id,
                actor_id=owner,
            )

        # -- 1. 加密存储：库里没有明文 -------------------------------------
        live_secret = await container.assets.put_secret(
            workspace_id=workspace_id,
            name="llm_api_key",
            plaintext="sk-live-PRODUCTION-abcdef",
            created_by=owner,
        )
        assert "sk-live" not in live_secret.ciphertext
        assert live_secret.fingerprint and len(live_secret.fingerprint) == 12

        # -- 2. required 的密钥没绑 → 调用失败，不静默少给 ------------------
        unbound: DomainError | None = None
        try:
            await _invoke(container, agent.id, workspace_id, Channel.TEST)
        except DomainError as exc:
            unbound = exc
        assert unbound is not None, "缺密钥应当直接失败"
        assert unbound.error is Errors.CHANNEL_UNBOUND, unbound

        # -- 3. 两个通道绑**不同的**密钥——测试/生产分离 --------------------
        test_secret = await container.assets.put_secret(
            workspace_id=workspace_id,
            name="llm_api_key",
            plaintext="sk-test-SANDBOX-123456",
            created_by=owner,
        )
        await container.assets.bind_secret(
            asset_version_id=version.id,
            channel=Channel.TEST,
            secret_name="llm_api_key",
            resource_secret_id=test_secret.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )
        await container.assets.bind_secret(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            secret_name="llm_api_key",
            resource_secret_id=live_secret.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )

        # -- 4. 明文真的注入到了 Agent ------------------------------------
        await _invoke(container, agent.id, workspace_id, Channel.TEST)
        assert RECEIVED["llm_api_key"] == "sk-test-SANDBOX-123456"
        await _invoke(container, agent.id, workspace_id, Channel.LIVE)
        assert RECEIVED["llm_api_key"] == "sk-live-PRODUCTION-abcdef"

        # -- 5. 轮换 = 指针改到新的一把，旧的不动 --------------------------
        rotated = await container.assets.put_secret(
            workspace_id=workspace_id,
            name="llm_api_key",
            plaintext="sk-live-ROTATED-999999",
            created_by=owner,
        )
        await container.assets.bind_secret(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            secret_name="llm_api_key",
            resource_secret_id=rotated.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )
        await _invoke(container, agent.id, workspace_id, Channel.LIVE)
        assert RECEIVED["llm_api_key"] == "sk-live-ROTATED-999999"

        # -- 6. 回滚 = 指针改回旧的，不需要任何恢复操作 --------------------
        await container.assets.bind_secret(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            secret_name="llm_api_key",
            resource_secret_id=live_secret.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )
        await _invoke(container, agent.id, workspace_id, Channel.LIVE)
        assert RECEIVED["llm_api_key"] == "sk-live-PRODUCTION-abcdef"

        # -- 7. 名字对不上要被拒（防止张冠李戴）-----------------------------
        mismatch: DomainError | None = None
        try:
            await container.assets.bind_secret(
                asset_version_id=version.id,
                channel=Channel.TEST,
                secret_name="另一个名字",
                resource_secret_id=test_secret.id,
                workspace_id=workspace_id,
                bound_by=owner,
            )
        except DomainError as exc:
            mismatch = exc
        assert mismatch is not None and "对不上" in str(mismatch)
    finally:
        await container.shutdown()


def test_resource_secrets(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

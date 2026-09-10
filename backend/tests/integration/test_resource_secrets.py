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
from backend.app.modules.asset.domain.models import (
    MODEL_AUTH_TOKEN,
    MODEL_BASE_URL,
    MODEL_NAME,
    MODEL_SECRET_NAMES,
    WORKSPACE_DEFAULT_VERSION,
)
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


async def _default_scenario(tmp_path) -> None:
    """工作区默认 + Agent 覆盖。

    模型配置是**平台兜底**：工作区配一次，所有 Agent 都能用；单个 Agent
    想换模型就在自己的版本上绑同名密钥覆盖——**按 (通道, 密钥名) 粒度覆盖**，
    不是整条记录覆盖，这样只改一项时另两项仍来自默认。
    """
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        # 这个 Agent **不声明**任何必填密钥——专门验「不声明也能拿到模型配置」。
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="model-config-agent",
            connect_type="package",
            source={
                "artifact_id": "a-1",
                "entrypoint": ENTRYPOINT,
                "memory": {"scope": "stateless"},
            },
        )
        version = (await container.assets.list_versions(agent.id, workspace_id))[0]
        for channel in (Channel.TEST, Channel.LIVE):
            await container.assets.bind_channel(
                asset_id=agent.id,
                channel=channel,
                version_id=version.id,
                workspace_id=workspace_id,
                actor_id=owner,
            )

        # -- 1. 配工作区默认的模型配置（三个键）---------------------------
        defaults = {
            MODEL_BASE_URL: "http://216.167.7.16:8080",
            MODEL_AUTH_TOKEN: "sk-default-token",
            MODEL_NAME: "grok-4.5",
        }
        for name, value in defaults.items():
            secret = await container.assets.put_secret(
                workspace_id=workspace_id,
                name=name,
                plaintext=value,
                created_by=owner,
            )
            await container.assets.bind_workspace_default(
                channel=Channel.LIVE,
                secret_name=name,
                resource_secret_id=secret.id,
                workspace_id=workspace_id,
                bound_by=owner,
            )

        # -- 2. Agent **没声明**也能拿到模型配置 ---------------------------
        resolved = await container.assets.resolve_secrets(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            workspace_id=workspace_id,
        )
        assert resolved[MODEL_BASE_URL] == "http://216.167.7.16:8080"
        assert resolved[MODEL_AUTH_TOKEN] == "sk-default-token"
        assert resolved[MODEL_NAME] == "grok-4.5"

        # 另一个通道没配 → 不注入（Agent 自己降级）
        test_side = await container.assets.resolve_secrets(
            asset_version_id=version.id,
            channel=Channel.TEST,
            workspace_id=workspace_id,
        )
        assert MODEL_AUTH_TOKEN not in test_side

        # -- 3. Agent 覆盖其中一项：另两项仍来自默认 ----------------------
        own = await container.assets.put_secret(
            workspace_id=workspace_id,
            name=MODEL_NAME,
            plaintext="grok-4.5-mini",
            created_by=owner,
        )
        await container.assets.bind_secret(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            secret_name=MODEL_NAME,
            resource_secret_id=own.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )
        overridden = await container.assets.resolve_secrets(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            workspace_id=workspace_id,
        )
        assert overridden[MODEL_NAME] == "grok-4.5-mini", "版本绑定应当覆盖默认"
        assert overridden[MODEL_AUTH_TOKEN] == "sk-default-token", "未覆盖的项仍来自默认"

        # -- 4. 生效绑定列表是合并后的结果 ---------------------------------
        effective = await container.assets.secret_bindings_of(version.id, workspace_id)
        names = {item.secret_name for item in effective}
        assert names == set(MODEL_SECRET_NAMES)

        # -- 5. 解绑默认：没有覆盖的项随之消失 -----------------------------
        await container.assets.unbind_secret(
            asset_version_id=WORKSPACE_DEFAULT_VERSION,
            channel=Channel.LIVE,
            secret_name=MODEL_AUTH_TOKEN,
            workspace_id=workspace_id,
        )
        after = await container.assets.resolve_secrets(
            asset_version_id=version.id,
            channel=Channel.LIVE,
            workspace_id=workspace_id,
        )
        assert MODEL_AUTH_TOKEN not in after
        assert after[MODEL_NAME] == "grok-4.5-mini", "版本自己的绑定不受影响"
    finally:
        await container.shutdown()


def test_workspace_default_and_override(tmp_path) -> None:
    asyncio.run(_default_scenario(tmp_path))

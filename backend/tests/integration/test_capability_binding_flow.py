"""能力资产引用：`follow` 解析模式与晋级门禁。

核心命题：**引用跟着 Agent 的通道走**。

- Agent 在 TEST → 用 Skill 的 TEST 版本
- Agent 晋级到 LIVE → 用 Skill 的 LIVE 版本（自动，不需要手工同步）
- 但 Skill 在目标通道没版本时，**晋级被阻断**——否则 Agent 到生产会带悬空引用
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.container import Container
from backend.app.contracts.common import AssetKind, Channel
from backend.app.contracts.errors import DomainError
from backend.app.modules.delivery.domain.lifecycle import (
    DEFAULT_POLICY,
    CheckName,
    LifecyclePolicy,
)
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

AGENT_ENTRY = f"{__name__}:echo_agent"


def echo_agent(input: str) -> str:  # noqa: A002
    return f"echo:{input}"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'binding.db'}",
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
        assets = container.assets

        # 一个 Skill 和一个 Agent
        skill = await assets.register_capability(
            workspace_id=workspace_id, owner_id=owner, kind=AssetKind.SKILL, name="退款处理",
            spec={
                "kind": "skill",
                "instructions": "识别退款意图，查询订单与政策，说明结果",
                "allowed_tools": ["lookup_order", "create_refund"],
                "max_steps": 8,
                "timeout_ms": 30000,
            },
        )
        agent = await assets.register_agent(
            workspace_id=workspace_id, owner_id=owner, name="客服 Agent",
            connect_type="package",
            source={"artifact_id": "a1", "entrypoint": AGENT_ENTRY,
                    "memory": {"scope": "stateless"}},
        )
        agent_version = (await assets.list_versions(agent.id, workspace_id))[0]
        skill_version = (await assets.list_versions(skill.id, workspace_id))[0]

        # -- 1. 默认是 follow：跟着 Agent 走 ---------------------------------
        binding = await assets.bind_capability(
            workspace_id=workspace_id, actor_id=owner,
            consumer_asset_id=agent.id, provider_asset_id=skill.id,
        )
        assert binding.resolve_mode == "follow"

        # Agent 在 TEST → 解析到 Skill 的 TEST 版本
        resolved = await assets.resolve_bindings(agent_version.id, workspace_id)
        assert resolved[skill.id] == skill_version.id

        # -- 2. Agent 晋级到 LIVESH，但 Skill 没有 LIVESH 版本 → 阻断 ---------
        # 用策略覆盖跳过门禁与影子路由，把焦点放在「引用就绪」这一项上
        payload = DEFAULT_POLICY.as_dict()
        for transition in payload["transitions"]:
            transition["checks"] = [
                check for check in transition["checks"]
                if check["name"] == CheckName.ASSETS_READY.value
            ]
        await container.delivery.save_policy(
            workspace_id, LifecyclePolicy.from_dict(payload), owner
        )

        with pytest.raises(DomainError) as blocked:
            await container.delivery.request_promotion(
                asset_id=agent.id, version_id=agent_version.id,
                to_channel=Channel.LIVESH, run_id=None,
                workspace_id=workspace_id, actor_id=owner,
            )
        assert blocked.value.code == "gate_blocked"
        assert "退款处理" in str(blocked.value)
        assert "livesh" in str(blocked.value)

        # -- 3. 把 Skill 也推到 LIVESH → 放行 --------------------------------
        await assets.bind_channel(
            asset_id=skill.id, channel=Channel.LIVESH,
            version_id=skill_version.id, workspace_id=workspace_id, actor_id=owner,
        )
        promotion = await container.delivery.request_promotion(
            asset_id=agent.id, version_id=agent_version.id,
            to_channel=Channel.LIVESH, run_id=None,
            workspace_id=workspace_id, actor_id=owner,
        )
        assert promotion.to_channel is Channel.LIVESH

        # -- 4. Agent 到了 LIVESH → 引用自动解析到 Skill 的 LIVESH 版本 -------
        assert await assets.resolve_bindings(agent_version.id, workspace_id) == {
            skill.id: skill_version.id
        }

        # -- 5. `pinned` 不受通道影响 ----------------------------------------
        await assets.bind_capability(
            workspace_id=workspace_id, actor_id=owner,
            consumer_asset_id=agent.id, provider_asset_id=skill.id,
            resolve_mode="pinned", provider_version_id=skill_version.id,
        )
        pinned = await assets.resolve_bindings(agent_version.id, workspace_id)
        assert pinned[skill.id] == skill_version.id
    finally:
        await container.shutdown()


def test_capability_binding_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

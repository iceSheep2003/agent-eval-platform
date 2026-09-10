"""N1 + N2 验收：能力资产台账 → 不可变版本 → 引用关系 → 解析成具体版本。

关键不变量：
1. 能力资产与 Agent 共用一套「身份 + 版本 + 通道」骨架，spec 校验按 kind 分派；
2. 引用**不复制内容**，只存指针；`channel` 模式跟随通道，`pinned` 模式锁死版本；
3. `resolve_bindings` 是两种模式唯一分支的地方，下游看到的是同一个映射；
4. 跨 kind 的 id 不能互相打通（Skill 的 id 打不到 Agent 接口上）。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.container import Container
from backend.app.contracts.common import AssetKind, Channel
from backend.app.contracts.errors import DomainError, NotFound
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

SKILL_SPEC = {
    "kind": "skill",
    "instructions": "提取并校验 order_id，然后查询订单",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "allowed_tools": ["orders.lookup"],
    "max_steps": 8,
    "timeout_ms": 12000,
}

MCP_SPEC = {
    "kind": "mcp",
    "endpoint": "https://mcp.internal/orders",
    "transport": "streamable-http",
    "authentication": {"type": "bearer", "secret_ref": "vault://mcp/orders"},
    "tools": [{"name": "orders.lookup", "description": "查订单"}],
}


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'capability.db'}",
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
        owner_id = seeded["admin"]
        assets = container.assets

        # --- N1：台账与不可变版本 ------------------------------------------
        skill = await assets.register_capability(
            workspace_id=workspace_id,
            owner_id=owner_id,
            kind=AssetKind.SKILL,
            name="refund-policy",
            description="退款政策解读",
            spec=SKILL_SPEC,
        )
        assert skill.kind is AssetKind.SKILL
        versions = await assets.list_versions(skill.id, workspace_id)
        assert [v.version_label for v in versions] == ["0.1.0"]
        channels = await assets.channel_states(skill.id, workspace_id)
        assert channels[Channel.TEST].version_id == versions[0].id

        # 相同内容不重复落库
        duplicate = await assets.create_version(
            asset_id=skill.id,
            workspace_id=workspace_id,
            created_by=owner_id,
            spec=SKILL_SPEC,
        )
        assert duplicate.id == versions[0].id

        # 新内容 → 新版本，TEST 指针跟着走
        v2 = await assets.create_version(
            asset_id=skill.id,
            workspace_id=workspace_id,
            created_by=owner_id,
            spec={**SKILL_SPEC, "max_steps": 4},
        )
        assert v2.version_label == "0.1.1"
        channels = await assets.channel_states(skill.id, workspace_id)
        assert channels[Channel.TEST].version_id == v2.id

        # 非法 spec 被拒绝：能力资产的校验器按 kind 分派
        with pytest.raises(DomainError):
            await assets.register_capability(
                workspace_id=workspace_id,
                owner_id=owner_id,
                kind=AssetKind.MCP,
                name="broken-mcp",
                spec={"kind": "mcp", "endpoint": "https://x", "transport": "stdio", "tools": []},
            )

        mcp = await assets.register_capability(
            workspace_id=workspace_id,
            owner_id=owner_id,
            kind=AssetKind.MCP,
            name="orders-mcp",
            spec=MCP_SPEC,
        )
        # MCP/知识库没有用户可见的发布通道，注册后当前配置立即可解析。
        mcp_v1 = (await assets.list_versions(mcp.id, workspace_id))[0]
        assert (await assets.channel_states(mcp.id, workspace_id))[Channel.LIVE].version_id == mcp_v1.id

        # 跨 kind 的 id 打不通：Skill 的 id 不能从 Agent 接口读到
        with pytest.raises(NotFound):
            await assets.get_agent(skill.id, workspace_id)
        with pytest.raises(NotFound):
            await assets.get_capability("asset_missing", workspace_id)

        # --- N2：引用关系 ---------------------------------------------------
        agent = await assets.register_agent(
            workspace_id=workspace_id, owner_id=owner_id, name="support-agent"
        )
        agent_versions = await assets.list_versions(agent.id, workspace_id)
        agent_version_id = agent_versions[0].id
        # Agent 不是能力资产
        with pytest.raises(NotFound):
            await assets.get_capability(agent.id, workspace_id)

        # 默认跟随 LIVE；LIVE 还没绑版本 → 解析不出来，但引用本身存在
        binding = await assets.bind_capability(
            workspace_id=workspace_id,
            actor_id=owner_id,
            consumer_asset_id=agent.id,
            provider_asset_id=skill.id,
            resolve_mode="channel",
        )
        assert binding.resolve_mode == "channel"
        assert binding.target_channel() is Channel.LIVE
        assert await assets.resolve_bindings(agent_version_id, workspace_id) == {}

        # LIVE 绑上 v2 → 引用自动解析到 v2（不必重冻 Agent）
        await assets.bind_channel(
            asset_id=skill.id,
            channel=Channel.LIVE,
            version_id=v2.id,
            workspace_id=workspace_id,
            actor_id=owner_id,
        )
        resolved = await assets.resolve_bindings(agent_version_id, workspace_id)
        assert resolved == {skill.id: v2.id}

        # pinned 模式锁死 v1
        pinned = await assets.bind_capability(
            workspace_id=workspace_id,
            actor_id=owner_id,
            consumer_asset_id=agent.id,
            provider_asset_id=mcp.id,
            resolve_mode="pinned",
            provider_version_id=(await assets.list_versions(mcp.id, workspace_id))[0].id,
        )
        assert pinned.provider_channel is None
        resolved = await assets.resolve_bindings(agent_version_id, workspace_id)
        assert resolved == {skill.id: v2.id, mcp.id: mcp_v1.id}

        # 绑定覆盖（N4 的 A/B 入口）：只影响本次解析，不改绑定
        resolved = await assets.resolve_bindings(
            agent_version_id, workspace_id, overrides={skill.id: versions[0].id}
        )
        assert resolved[skill.id] == versions[0].id
        assert (await assets.resolve_bindings(agent_version_id, workspace_id))[skill.id] == v2.id

        # 版本级绑定优先于 Agent 级绑定
        await assets.bind_capability(
            workspace_id=workspace_id,
            actor_id=owner_id,
            consumer_asset_id=agent.id,
            provider_asset_id=skill.id,
            consumer_version_id=agent_version_id,
            resolve_mode="pinned",
            provider_version_id=versions[0].id,
        )
        assert (await assets.resolve_bindings(agent_version_id, workspace_id))[skill.id] == versions[0].id

        # 影响面：谁在引用这个 Skill
        impact = await assets.list_bindings_of_provider(skill.id, workspace_id)
        assert len(impact) == 2

        # 解除引用
        await assets.unbind_capability(impact[0].id, workspace_id)
        assert len(await assets.list_bindings_of_provider(skill.id, workspace_id)) == 1

        # 引用不存在的资源 → 404
        with pytest.raises(NotFound):
            await assets.bind_capability(
                workspace_id=workspace_id,
                actor_id=owner_id,
                consumer_asset_id=agent.id,
                provider_asset_id="asset_missing",
            )
    finally:
        await container.shutdown()


def test_capability_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

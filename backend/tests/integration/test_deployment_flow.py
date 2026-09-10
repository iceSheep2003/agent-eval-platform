"""运行实例的启停。

核心命题：**发布通道和运行实例是两条独立的生命周期**。

- 冻结版本不启动
- 晋级不启动（LIVE 除外：发布即生效）
- 启动的前提是该通道已绑定版本
- 只有 running 的实例能被生产调用；TEST/LIVESH 允许临时沙箱兜底
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.container import Container
from backend.app.contracts.common import Channel
from backend.app.contracts.errors import DomainError
from backend.app.contracts.execution import ChannelInvocation
from backend.app.modules.deployment.domain.models import InstanceState
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

ENTRYPOINT = f"{__name__}:echo_agent"


def echo_agent(input: str) -> str:  # noqa: A002
    return f"echo:{input}"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'deployment.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _agent(container: Container, workspace_id: str, owner: str):
    agent = await container.assets.register_agent(
        workspace_id=workspace_id,
        owner_id=owner,
        name="echo-agent",
        connect_type="package",
        source={
            "artifact_id": "a1",
            "entrypoint": ENTRYPOINT,
            "memory": {"scope": "stateless"},
        },
    )
    versions = await container.assets.list_versions(agent.id, workspace_id)
    return agent, versions[0]


async def _bind(container, agent, version, channel, workspace_id, owner) -> None:
    await container.assets.bind_channel(
        asset_id=agent.id,
        channel=channel,
        version_id=version.id,
        workspace_id=workspace_id,
        actor_id=owner,
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        deployments = container.deployments

        agent, version = await _agent(container, workspace_id, owner)

        # -- 1. 冻结版本 ≠ 启动 ---------------------------------------------
        assert await deployments.list_instances(agent.id, workspace_id) == []

        # -- 2. TEST 不设常驻实例（调试走临时沙箱）-------------------------
        with pytest.raises(DomainError) as candidate:
            await deployments.start(
                asset_id=agent.id, channel=Channel.TEST,
                workspace_id=workspace_id, actor_id=owner,
            )
        assert candidate.value.code == "validation_failed"
        assert "候选通道" in str(candidate.value)

        # -- 3. 通道没绑版本 → 先晋级 ---------------------------------------
        with pytest.raises(DomainError) as unbound:
            await deployments.start(
                asset_id=agent.id, channel=Channel.LIVE,
                workspace_id=workspace_id, actor_id=owner,
            )
        assert "还没有绑定版本" in str(unbound.value)

        # -- 4. 绑定后启动 → running ---------------------------------------
        await _bind(container, agent, version, Channel.LIVE, workspace_id, owner)
        instance = await deployments.start(
            asset_id=agent.id, channel=Channel.LIVE,
            workspace_id=workspace_id, actor_id=owner,
        )
        assert instance.state is InstanceState.RUNNING
        assert instance.endpoint is not None or instance.handle_id is not None
        assert instance.started_at is not None

        # -- 5. 重复启动被拒 -------------------------------------------------
        with pytest.raises(DomainError) as twice:
            await deployments.start(
                asset_id=agent.id, channel=Channel.LIVE,
                workspace_id=workspace_id, actor_id=owner,
            )
        assert "不能重复启动" in str(twice.value)

        # -- 6. running 实例能被调用 ----------------------------------------
        result = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id, asset_id=agent.id,
                channel=Channel.LIVE, input="ping",
            )
        )
        assert result.output == "echo:ping"

        # -- 7. 停止后不能再被调用 -------------------------------------------
        stopped = await deployments.stop(
            instance_id=instance.id, workspace_id=workspace_id, actor_id=owner
        )
        assert stopped.state is InstanceState.STOPPED

        with pytest.raises(DomainError) as down:
            await container.invoke.invoke_channel(
                ChannelInvocation(
                    workspace_id=workspace_id, asset_id=agent.id,
                    channel=Channel.LIVE, input="ping",
                )
            )
        assert down.value.code == "run_state_conflict"
        assert "没有运行中的实例" in str(down.value)

        # -- 8. 重启回到 running ---------------------------------------------
        restarted = await deployments.restart(
            instance_id=instance.id, workspace_id=workspace_id, actor_id=owner
        )
        assert restarted.state is InstanceState.RUNNING

        # -- 9. LIVESH 允许临时沙箱（没有实例也能调）-------------------------
        await _bind(container, agent, version, Channel.LIVESH, workspace_id, owner)
        shadow = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id, asset_id=agent.id,
                channel=Channel.LIVESH, input="ping",
            )
        )
        assert shadow.output == "echo:ping"
        # 而且**没有**因此凭空多出一个实例
        assert len(await deployments.list_instances(agent.id, workspace_id)) == 1
    finally:
        await container.shutdown()


def test_deployment_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))


async def _promotion_scenario(tmp_path) -> None:
    """晋级到 LIVE 自动拉起实例；晋级到 LIVESH 不拉。"""
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        agent, version = await _agent(container, workspace_id, owner)

        # 本测试只关心「晋级会不会顺带启动实例」，不想为了过门禁跑一整轮评测。
        # 用策略覆盖把 TEST→LIVESH 的检查减到只剩影子路由——顺带证明了策略是可配的。
        from backend.app.modules.delivery.domain.lifecycle import (
            DEFAULT_POLICY,
            CheckName,
            LifecyclePolicy,
        )

        payload = DEFAULT_POLICY.as_dict()
        for transition in payload["transitions"]:
            if transition["to_channel"] == Channel.LIVESH.value:
                transition["checks"] = [
                    check
                    for check in transition["checks"]
                    if check["name"] == CheckName.SHADOW_ROUTE.value
                ]
        await container.delivery.save_policy(
            workspace_id, LifecyclePolicy.from_dict(payload), owner
        )

        # 版本冻结后自动绑到 TEST；按策略 TEST→LIVESH 还要先配影子路由
        await container.delivery.configure_shadow(
            asset_id=agent.id,
            candidate_version_id=version.id,
            baseline_version_id=None,
            sample_rate=0.1,
            workspace_id=workspace_id,
        )

        # 晋级 TEST→LIVESH：只改指针，**不**启动实例
        await container.delivery.request_promotion(
            asset_id=agent.id, version_id=version.id, to_channel=Channel.LIVESH,
            run_id=None, workspace_id=workspace_id, actor_id=owner,
        )
        assert await container.deployments.list_instances(agent.id, workspace_id) == []
    finally:
        await container.shutdown()


def test_promotion_to_livesh_does_not_start_instance(tmp_path) -> None:
    """LIVESH 手动：影子什么时候开始接流量由人决定。"""
    asyncio.run(_promotion_scenario(tmp_path))


async def _health_scenario(tmp_path) -> None:
    """探活：失败先摘流量，连续失败到阈值才判死。"""
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        deployments = container.deployments
        agent, version = await _agent(container, workspace_id, owner)
        await _bind(container, agent, version, Channel.LIVE, workspace_id, owner)
        instance = await deployments.start(
            asset_id=agent.id, channel=Channel.LIVE,
            workspace_id=workspace_id, actor_id=owner,
        )

        # -- 健康时：running，计数清零 -------------------------------------
        probed = await deployments.probe(instance.id, workspace_id)
        assert probed.state is InstanceState.RUNNING
        assert probed.consecutive_failures == 0
        assert probed.last_health_at is not None

        # -- 模拟故障：把句柄从执行面摘掉（等价于进程重启/容器消失）---------
        await container.deployments._runtime.teardown(  # noqa: SLF001 - 模拟执行面故障
            _handle_of(instance, container)
        )

        first = await deployments.probe(instance.id, workspace_id)
        assert first.state is InstanceState.DEGRADED
        assert first.consecutive_failures == 1
        assert first.last_health_error

        # DEGRADED **不再接流量**——否则探活只是装饰
        assert await deployments.running_for(agent.id, Channel.LIVE, workspace_id) is None
        with pytest.raises(DomainError) as down:
            await container.invoke.invoke_channel(
                ChannelInvocation(
                    workspace_id=workspace_id, asset_id=agent.id,
                    channel=Channel.LIVE, input="ping",
                )
            )
        assert down.value.code == "run_state_conflict"

        # -- 连续失败到阈值 → failed，仍然不自动重启 ------------------------
        await deployments.probe(instance.id, workspace_id)
        final = await deployments.probe(instance.id, workspace_id)
        assert final.state is InstanceState.FAILED
        assert final.consecutive_failures >= 3

        # -- probe_due 跨工作区扫描，但不碰非活跃实例 -----------------------
        assert await deployments.probe_due() == 0
    finally:
        await container.shutdown()


def _handle_of(instance, container):
    from backend.app.contracts.execution import RuntimeHandle

    return RuntimeHandle(
        id=instance.handle_id or instance.id,
        asset_version_id=instance.asset_version_id,
        endpoint=instance.endpoint,
    )


def test_instance_health_probe(tmp_path) -> None:
    asyncio.run(_health_scenario(tmp_path))

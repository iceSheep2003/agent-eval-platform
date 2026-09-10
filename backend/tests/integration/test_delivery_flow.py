"""M5 验收：门禁阻断晋级、逐级晋级、回退、影子路由。

三条业务底线：
1. 门禁未通过 → **409 `gate_blocked`**（不是 403——这不是权限问题）；
2. 版本只能 TEST → LIVESH → LIVE，不能跳级；
3. 回退只改指针，问题版本与证据全部保留。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.app.container import Container
from backend.app.contracts.common import (
    Channel,
    DatasetPurpose,
    EvaluationStage,
    RunStatus,
)
from backend.app.contracts.errors import DomainError
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock
from backend.runtime.worker import Worker

CALLS: list[dict] = []


def echo_agent(input: str) -> str:  # noqa: A002
    CALLS.append({"input": input})
    return input


ENTRYPOINT = f"{__name__}:echo_agent"

async def _seed_shadow_traces(
    container, agent_id: str, version_id: str, workspace_id: str, *, count: int
) -> None:
    """直接写影子 Trace——测晋级判定，不必绕一遍 ingest。"""
    from datetime import timedelta
    from decimal import Decimal

    from backend.app.contracts.common import TraceOrigin, Usage
    from backend.app.modules.observability.domain.models import TraceRecord
    from backend.app.modules.observability.infrastructure.repositories import TraceRepository
    from backend.app.persistence import UnitOfWork
    from backend.app.shared.ids import new_id

    now = container.clock.now()
    async with UnitOfWork(container.database) as uow:
        repo = TraceRepository(uow.session)
        for index in range(count):
            started = now - timedelta(minutes=index + 1)
            repo.add(
                TraceRecord(
                    id=new_id("trace"),
                    workspace_id=workspace_id,
                    tenant_id=None,
                    origin=TraceOrigin.SHADOW,
                    asset_id=agent_id,
                    asset_version_id=version_id,
                    channel=None,
                    run_id=None,
                    trial_id=None,
                    external_trace_id=f"shadow-{index}",
                    name="shadow",
                    status="success",
                    started_at=started,
                    ended_at=started + timedelta(milliseconds=200),
                    input=None,
                    output=None,
                    usage=Usage(cost=type(Usage().cost)(Decimal("0.001"))),
                    span_count=1,
                    ingested_via="sdk",
                ),
                (),
            )
        await uow.commit()


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'delivery.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _drain(container: Container, rounds: int = 16) -> None:
    worker = Worker(container, [container.execution_handlers], worker_id="test")
    for _ in range(rounds):
        if await worker.run_once() == 0:
            break


async def _run_eval(
    container: Container, *, workspace_id: str, owner: str, agent_id: str, version_id: str,
    dataset_name: str, samples: list[dict], gate: float, run_name: str,
):
    dataset = await container.datasets.create_dataset(
        workspace_id=workspace_id, owner_id=owner, name=dataset_name,
        purpose=DatasetPurpose.GATE,
    )
    outcome = await container.datasets.import_file(
        dataset_id=dataset.id, workspace_id=workspace_id, actor_id=owner,
        filename="samples.json", content=json.dumps(samples).encode(),
    )
    finalized = await container.datasets.finalize_version(outcome.version.id, workspace_id)
    template = await container.evaluations.create_template(
        workspace_id=workspace_id, created_by=owner, name=f"{dataset_name}-策略",
        stage=EvaluationStage.RELEASE, dataset_version_id=finalized.id,
        evaluator_names=["answer_exact_match"], gates={"task_success_rate": gate},
    )
    run = await container.runs.create_run(
        workspace_id=workspace_id, created_by=owner, name=run_name,
        asset_version_id=version_id, dataset_version_id=finalized.id, template_id=template.id,
    )
    await _drain(container)
    return await container.runs.get_run_ref(run.id, workspace_id)


async def _scenario(tmp_path) -> None:
    CALLS.clear()
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]

        agent = await container.assets.register_agent(
            workspace_id=workspace_id, owner_id=owner, name="echo-agent",
            connect_type="package",
            source={"artifact_id": "a1", "entrypoint": ENTRYPOINT, "memory": {"scope": "stateless"}},
        )

        # 版本 A：评测全通过 → 门禁放行
        good = await container.assets.create_version(
            asset_id=agent.id, workspace_id=workspace_id, created_by=owner,
            spec={"kind": "agent", "connect_type": "package", "artifact_id": "a1",
                  "entrypoint": ENTRYPOINT, "memory": {"scope": "stateless"}},
        )
        run = await _run_eval(
            container, workspace_id=workspace_id, owner=owner, agent_id=agent.id,
            version_id=good.id, dataset_name="门禁集A",
            samples=[{"input": "hello", "expected_output": "hello"}],
            gate=0.9, run_name="A 评测",
        )
        assert run is not None and run.gate_passed

        # 跳级：TEST 直接到 LIVE → 拒绝
        with pytest.raises(DomainError) as skip:
            await container.delivery.request_promotion(
                asset_id=agent.id, version_id=good.id, to_channel=Channel.LIVE,
                run_id=None, workspace_id=workspace_id, actor_id=owner,
            )
        assert skip.value.code == "promotion_order_violation"

        # 没配影子路由就进 LIVESH → 挡住（否则「影子验证」无从谈起）
        with pytest.raises(DomainError) as no_route:
            await container.delivery.request_promotion(
                asset_id=agent.id, version_id=good.id, to_channel=Channel.LIVESH,
                run_id=None, workspace_id=workspace_id, actor_id=owner,
            )
        assert no_route.value.code == "gate_blocked"

        # 配好影子路由（方向固定 copy_in_only）
        route = await container.delivery.configure_shadow(
            asset_id=agent.id, candidate_version_id=good.id, baseline_version_id=None,
            sample_rate=0.15, workspace_id=workspace_id,
        )
        assert route.direction == "copy_in_only" and route.sample_rate == 0.15

        # 正常晋级 TEST → LIVESH
        promotion = await container.delivery.request_promotion(
            asset_id=agent.id, version_id=good.id, to_channel=Channel.LIVESH,
            run_id=None, workspace_id=workspace_id, actor_id=owner,
        )
        assert promotion.from_channel is Channel.TEST
        assert promotion.gate_passed

        bindings = await container.assets.channel_map(agent.id, workspace_id)
        assert bindings[Channel.LIVESH] == good.id
        assert bindings[Channel.TEST] == good.id  # 原通道仍指向它

        # LIVESH → LIVE：影子样本不足 → 挡住
        with pytest.raises(DomainError) as thin:
            await container.delivery.request_promotion(
                asset_id=agent.id, version_id=good.id, to_channel=Channel.LIVE,
                run_id=None, workspace_id=workspace_id, actor_id=owner,
            )
        assert thin.value.code == "gate_blocked"
        assert "影子样本不足" in str(thin.value)

        # 补够影子样本后放行
        await _seed_shadow_traces(container, agent.id, good.id, workspace_id, count=30)
        to_live = await container.delivery.request_promotion(
            asset_id=agent.id, version_id=good.id, to_channel=Channel.LIVE,
            run_id=None, workspace_id=workspace_id, actor_id=owner,
        )
        assert to_live.to_channel is Channel.LIVE

        # 版本 B：评测不通过 → 门禁阻断
        bad = await container.assets.create_version(
            asset_id=agent.id, workspace_id=workspace_id, created_by=owner,
            spec={"kind": "agent", "connect_type": "package", "artifact_id": "a1",
                  "entrypoint": ENTRYPOINT, "variant": "b", "memory": {"scope": "stateless"}},
        )
        bad_run = await _run_eval(
            container, workspace_id=workspace_id, owner=owner, agent_id=agent.id,
            version_id=bad.id, dataset_name="门禁集B",
            samples=[
                {"input": "hello", "expected_output": "hello"},
                {"input": "world", "expected_output": "nope"},
            ],
            gate=0.9, run_name="B 评测",
        )
        assert bad_run is not None and not bad_run.gate_passed

        with pytest.raises(DomainError) as blocked:
            await container.delivery.request_promotion(
                asset_id=agent.id, version_id=bad.id, to_channel=Channel.LIVESH,
                run_id=None, workspace_id=workspace_id, actor_id=owner,
            )
        assert blocked.value.code == "gate_blocked"
        assert blocked.value.http_status == 409  # 不是 403

        # 没有任何评测结果就晋级 → 同样阻断
        bare = await container.assets.create_version(
            asset_id=agent.id, workspace_id=workspace_id, created_by=owner,
            spec={"kind": "agent", "connect_type": "package", "artifact_id": "a1",
                  "entrypoint": ENTRYPOINT, "variant": "c", "memory": {"scope": "stateless"}},
        )
        with pytest.raises(DomainError) as no_run:
            await container.delivery.request_promotion(
                asset_id=agent.id, version_id=bare.id, to_channel=Channel.LIVESH,
                run_id=None, workspace_id=workspace_id, actor_id=owner,
            )
        assert no_run.value.code == "gate_blocked"

        # 回退：LIVESH 指回版本 A（本来就是 A，先换到别的再回退）
        await container.assets.bind_channel(
            asset_id=agent.id, channel=Channel.LIVESH, version_id=bad.id,
            workspace_id=workspace_id, actor_id=owner,
        )
        rollback = await container.delivery.rollback(
            asset_id=agent.id, channel=Channel.LIVESH, to_version_id=good.id,
            reason="B 版本线上退化", workspace_id=workspace_id, actor_id=owner,
        )
        assert rollback.from_version_id == bad.id
        assert rollback.to_version_id == good.id

        bindings = await container.assets.channel_map(agent.id, workspace_id)
        assert bindings[Channel.LIVESH] == good.id
        # 问题版本仍在，证据没被删
        versions = await container.assets.list_versions(agent.id, workspace_id)
        assert bad.id in {item.id for item in versions}

        # 回退必须写原因
        with pytest.raises(DomainError):
            await container.delivery.rollback(
                asset_id=agent.id, channel=Channel.LIVESH, to_version_id=bad.id,
                reason="   ", workspace_id=workspace_id, actor_id=owner,
            )

        # 审计留痕：两次晋级（TEST→LIVESH、LIVESH→LIVE）各一行
        promotions = await container.delivery.list_promotions(agent.id, workspace_id)
        assert [(p.from_channel.value, p.to_channel.value) for p in promotions] == [
            ("livesh", "live"),
            ("test", "livesh"),
        ]
        assert len(await container.delivery.list_rollbacks(agent.id, workspace_id)) == 1
    finally:
        await container.shutdown()


def test_delivery_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

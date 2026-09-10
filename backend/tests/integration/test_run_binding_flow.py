"""N2 验收：Run 冻结引用快照 → 能力资产 A/B。

三条硬约束：
1. `CreateRun` 把「跟随通道」的引用**解析一次并冻结**，之后资源晋级不改这个 Run；
2. `binding_overrides` 只影响本次 Run，不改绑定本身——这是能力资产 A/B 的唯一入口；
3. 被测函数**没声明** `capabilities` 形参时，Runtime 不注入该参数（不打破现有 Agent 签名）。
"""

from __future__ import annotations

import asyncio
import json

from backend.app.container import Container
from backend.app.contracts.common import (
    AssetKind,
    Channel,
    DatasetPurpose,
    EvaluationStage,
)
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock
from backend.runtime.worker import Worker

CALLS: list[dict] = []


def skill_aware_agent(input: str, capabilities: dict | None = None) -> str:  # noqa: A002
    CALLS.append({"input": input, "capabilities": capabilities or {}})
    for spec in (capabilities or {}).values():
        if spec.get("kind") == "skill":
            return f"{input}:{spec['max_steps']}"
    return input


ENTRYPOINT = f"{__name__}:skill_aware_agent"

SKILL_SPEC = {
    "kind": "skill",
    "instructions": "退款政策解读",
    "max_steps": 8,
    "timeout_ms": 12000,
}


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


async def _drain(container: Container, rounds: int = 12) -> None:
    worker = Worker(container, [container.execution_handlers], worker_id="test")
    for _ in range(rounds):
        if await worker.run_once() == 0:
            break


async def _scenario(tmp_path) -> None:
    CALLS.clear()
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        assets = container.assets

        agent = await assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="skill-agent",
            connect_type="package",
            source={"artifact_id": "artifact-1", "entrypoint": ENTRYPOINT, "memory": {"scope": "stateless"}},
        )
        agent_version = (await assets.list_versions(agent.id, workspace_id))[0]

        skill = await assets.register_capability(
            workspace_id=workspace_id,
            owner_id=owner,
            kind=AssetKind.SKILL,
            name="refund-policy",
            spec=SKILL_SPEC,
        )
        v1 = (await assets.list_versions(skill.id, workspace_id))[0]
        v2 = await assets.create_version(
            asset_id=skill.id,
            workspace_id=workspace_id,
            created_by=owner,
            spec={**SKILL_SPEC, "max_steps": 4},
        )

        # 引用：跟随 LIVE；先把 LIVE 指到 v1
        await assets.bind_capability(
            workspace_id=workspace_id,
            actor_id=owner,
            consumer_asset_id=agent.id,
            provider_asset_id=skill.id,
        )
        await assets.bind_channel(
            asset_id=skill.id,
            channel=Channel.LIVE,
            version_id=v1.id,
            workspace_id=workspace_id,
            actor_id=owner,
        )

        # 数据集 + 策略
        dataset = await container.datasets.create_dataset(
            workspace_id=workspace_id,
            owner_id=owner,
            name="A/B 测试集",
            purpose=DatasetPurpose.CAPABILITY,
        )
        outcome = await container.datasets.import_file(
            dataset_id=dataset.id,
            workspace_id=workspace_id,
            actor_id=owner,
            filename="samples.json",
            content=json.dumps(
                [{"input": "退款", "expected_output": "退款:8"}]
            ).encode(),
        )
        finalized = await container.datasets.finalize_version(outcome.version.id, workspace_id)
        template = await container.evaluations.create_template(
            workspace_id=workspace_id,
            created_by=owner,
            name="A/B 策略",
            stage=EvaluationStage.DEVELOPMENT,
            dataset_version_id=finalized.id,
            evaluator_names=["answer_exact_match"],
        )

        # --- 冻结：CreateRun 时解析并冻住 v1 ------------------------------
        run_a = await container.runs.create_run(
            workspace_id=workspace_id,
            created_by=owner,
            name="A: skill v1",
            asset_version_id=agent_version.id,
            dataset_version_id=finalized.id,
            template_id=template.id,
        )
        assert run_a.binding_snapshot == {skill.id: v1.id}
        assert run_a.binding_overrides == {}

        await _drain(container)
        assert CALLS[-1]["capabilities"][skill.id]["max_steps"] == 8

        # --- 资源晋级不改变已冻结的 Run ------------------------------------
        await assets.bind_channel(
            asset_id=skill.id,
            channel=Channel.LIVE,
            version_id=v2.id,
            workspace_id=workspace_id,
            actor_id=owner,
        )
        again = await container.runs.get_run(run_a.id, workspace_id)
        assert again.binding_snapshot == {skill.id: v1.id}, "历史 Run 的快照不该随资源晋级漂移"

        # --- 新 Run 跟随新通道值 -------------------------------------------
        run_b = await container.runs.create_run(
            workspace_id=workspace_id,
            created_by=owner,
            name="B: skill v2",
            asset_version_id=agent_version.id,
            dataset_version_id=finalized.id,
            template_id=template.id,
        )
        assert run_b.binding_snapshot == {skill.id: v2.id}
        await _drain(container)
        assert CALLS[-1]["capabilities"][skill.id]["max_steps"] == 4  # B 用的是 v2

        # --- overrides：不晋级也能测 v1（A/B 的入口）-----------------------
        CALLS.clear()
        run_c = await container.runs.create_run(
            workspace_id=workspace_id,
            created_by=owner,
            name="C: override 到 v1",
            asset_version_id=agent_version.id,
            dataset_version_id=finalized.id,
            template_id=template.id,
            binding_overrides={skill.id: v1.id},
        )
        assert run_c.binding_snapshot == {skill.id: v1.id}
        assert run_c.binding_overrides == {skill.id: v1.id}
        # 绑定本身没被改动
        assert (await assets.resolve_bindings(agent_version.id, workspace_id))[skill.id] == v2.id

        await _drain(container)
        assert CALLS[-1]["capabilities"][skill.id]["max_steps"] == 8  # C 用的是 v1
    finally:
        await container.shutdown()


def test_run_binding_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

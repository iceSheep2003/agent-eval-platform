"""M2 验收：评测策略编排、数据集匹配硬约束、绑定、门禁预览。"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.app.container import Container
from backend.app.contracts.common import (
    DatasetPurpose,
    Determinism,
    EvaluationStage,
)
from backend.app.contracts.errors import DomainError, NotFound
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'evaluation.db'}",
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

        # 种子里的能力与维度
        capabilities = await container.evaluations.list_capabilities(workspace_id)
        assert {view.capability.name for view in capabilities} == {"回答质量", "工具使用"}
        tool_capability = next(v for v in capabilities if v.capability.name == "工具使用")
        assert [d.name for d in tool_capability.dimensions] == ["工具正确率", "参数合规率"]

        # 内置评估器目录：确定性 vs 概率性
        catalog = {item.name: item.determinism for item in container.evaluations.evaluator_catalog()}
        assert catalog["tool_name_correctness"] is Determinism.DETERMINISTIC
        assert catalog["llm_judge"] is Determinism.PROBABILISTIC

        # 准备一个只适用于 release 的数据集
        dataset = await container.datasets.create_dataset(
            workspace_id=workspace_id,
            owner_id=owner,
            name="发布门禁集",
            purpose=DatasetPurpose.GATE,  # 默认阶段 = release
        )
        outcome = await container.datasets.import_file(
            dataset_id=dataset.id,
            workspace_id=workspace_id,
            actor_id=owner,
            filename="gate.json",
            content=json.dumps([{"input": "问题", "expected_output": "答案"}]).encode(),
        )
        version_id = outcome.version.id

        # 阶段匹配 → 通过
        template = await container.evaluations.create_template(
            workspace_id=workspace_id,
            created_by=owner,
            name="发布门禁策略",
            stage=EvaluationStage.RELEASE,
            dataset_version_id=version_id,
            evaluator_names=["deterministic_match", "llm_judge"],  # 走别名解析
            gates={"task_success_rate": 0.95, "safety_violation_rate": 0.0},
        )
        assert template.dataset_id == dataset.id
        assert {item.name for item in template.evaluators} == {"answer_exact_match", "llm_judge"}
        assert template.gates[0].threshold == 0.95

        # 阶段不匹配 → 拒绝（硬约束）
        with pytest.raises(DomainError) as mismatch:
            await container.evaluations.create_template(
                workspace_id=workspace_id,
                created_by=owner,
                name="错阶段策略",
                stage=EvaluationStage.DEVELOPMENT,
                dataset_version_id=version_id,
            )
        assert "不适用于 development" in str(mismatch.value)

        # 未注册的评估器 → 拒绝
        with pytest.raises(DomainError):
            await container.evaluations.create_template(
                workspace_id=workspace_id,
                created_by=owner,
                name="坏评估器",
                stage=EvaluationStage.RELEASE,
                evaluator_names=["not_a_real_evaluator"],
            )

        # 绑定到 Agent
        agent = await container.assets.register_agent(
            workspace_id=workspace_id, owner_id=owner, name="agent-a", connect_type="sdk"
        )
        binding = await container.evaluations.bind(template.id, agent.id, workspace_id)
        assert binding.asset_id == agent.id
        counts = await container.evaluations.binding_counts(workspace_id)
        assert counts[template.id] == 1
        bound = await container.evaluations.list_templates_for_asset(agent.id, workspace_id)
        assert [item.id for item in bound] == [template.id]

        # 绑定不存在的资产 → 404
        with pytest.raises(NotFound):
            await container.evaluations.bind(template.id, "ast_nope", workspace_id)

        # 门禁预览：整体达标
        decision = await container.evaluations.preview_gate(
            template.id, workspace_id, {"task_success_rate": 0.97, "safety_violation_rate": 0.0}
        )
        assert decision.passed

        # 门禁预览：不达标 → 给出可读原因
        blocked = await container.evaluations.preview_gate(
            template.id, workspace_id, {"task_success_rate": 0.5, "safety_violation_rate": 0.0}
        )
        assert not blocked.passed
        assert blocked.blocked_rules == ("task_success_rate",)
        assert "门槛 0.95" in blocked.blocked_reasons[0]

        # 停用后仍在列表里，但 enabled=False（历史执行结果保留）
        disabled = await container.evaluations.disable_template(template.id, workspace_id)
        assert disabled.enabled is False

        # 解绑
        await container.evaluations.unbind(template.id, agent.id, workspace_id)
        assert await container.evaluations.binding_counts(workspace_id) == {}
    finally:
        await container.shutdown()


def test_evaluation_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

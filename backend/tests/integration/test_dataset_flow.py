"""M2 验收：创建数据集 → 导入预检 → 复核 → 固化 → 导出。

关键不变量：固化后的版本不可再改；有待复核样本时不允许固化。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.app.container import Container
from backend.app.contracts.common import (
    DatasetOrigin,
    DatasetPurpose,
    EvaluationStage,
    ItemValidation,
    TaskShape,
    TaskProtocol,
)
from backend.app.contracts.errors import DomainError
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'dataset.db'}",
            master_key="test",
        ),
        clock=clock,
    )


def _jsonl(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode("utf-8")


ROWS = [
    {"input": "订单 A001 能退款吗", "expected_output": {"refundable": True}},
    {"input": "订单 A002 能退款吗", "expected_output": {"refundable": False}},
    # 与第 1 行内容重复（换了无关元数据）
    {"input": "订单 A001 能退款吗", "expected_output": {"refundable": True}, "note": "副本"},
    # 缺输入字段 → 无效
    {"expected_output": {"refundable": True}},
]


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        service = container.datasets

        # benchmark 数据集不能只打一个标签：必须绑定已注册的 adapter，
        # 且样本执行协议要与 manifest 一致。
        with pytest.raises(DomainError):
            await service.create_dataset(
                workspace_id=workspace_id,
                owner_id=owner,
                name="伪 benchmark",
                origin=DatasetOrigin.BENCHMARK,
            )
        benchmark = await service.create_dataset(
            workspace_id=workspace_id,
            owner_id=owner,
            name="tau2 airline",
            origin=DatasetOrigin.BENCHMARK,
            task_shape=TaskShape.AGENTIC,
            protocol=TaskProtocol.AGENTIC,
            source={
                "benchmark_id": "tau2",
                "benchmark_version": "1.0.0",
                "adapter": "backend.app.modules.dataset.domain.benchmarks:Tau2DatasetAdapter",
                "adapter_version": "1.0.0",
                "split": "base",
            },
        )
        assert benchmark.source is not None
        assert benchmark.source.benchmark_id == "tau2"

        # purpose=REGRESSION 应带出默认阶段（regression + release）
        dataset = await service.create_dataset(
            workspace_id=workspace_id,
            owner_id=owner,
            name="退款回归集",
            description="历史缺陷复现",
            origin=DatasetOrigin.DEFECT,
            purpose=DatasetPurpose.REGRESSION,
            task_shape=TaskShape.SINGLE_TURN,
        )
        assert set(dataset.stages) == {
            EvaluationStage.REGRESSION,
            EvaluationStage.RELEASE,
        }

        # 导入：2 有效 + 1 重复 + 1 无效
        outcome = await service.import_file(
            dataset_id=dataset.id,
            workspace_id=workspace_id,
            actor_id=owner,
            filename="samples.jsonl",
            content=_jsonl(ROWS),
        )
        session = outcome.session
        assert (session.total_rows, session.valid_rows) == (4, 2)
        assert session.duplicate_rows == 1
        assert session.invalid_rows == 1
        assert {issue.code for issue in session.issues} == {"duplicate", "invalid_row"}

        version = outcome.version
        assert version.lifecycle == "draft"
        assert version.version_label == "1.0.0"

        # 草稿版本里的样本：三段式 + 只存 task/private 的摘要
        items, total = await service.list_items(version.id, workspace_id)
        assert total == 2
        first = items[0]
        assert first.task.instruction == "订单 A001 能退款吗"
        assert first.private is not None
        assert first.private.expected_output == {"refundable": True}
        assert first.validation is ItemValidation.VALID
        # 原始样本保真留存
        assert first.raw["input"] == "订单 A001 能退款吗"

        # 有待复核样本时不允许固化
        await service.review_item(first.id, workspace_id, ItemValidation.NEEDS_REVIEW)
        with pytest.raises(DomainError) as blocked:
            await service.finalize_version(version.id, workspace_id)
        assert "待复核" in str(blocked.value)

        # 复核通过后固化
        await service.review_item(first.id, workspace_id, ItemValidation.VALID)
        finalized = await service.finalize_version(version.id, workspace_id)
        assert finalized.lifecycle == "finalized"
        assert finalized.item_count == 2
        assert finalized.content_digest
        assert finalized.finalized_at is not None

        # 固化后样本不可改（需求说明 §9.3）
        with pytest.raises(DomainError) as immutable:
            await service.review_item(first.id, workspace_id, ItemValidation.INVALID)
        assert immutable.value.code == "dataset_version_immutable"

        # 再导入产生新版本，不覆盖旧版本
        again = await service.import_file(
            dataset_id=dataset.id,
            workspace_id=workspace_id,
            actor_id=owner,
            filename="samples.json",
            content=json.dumps([{"input": "新问题", "expected_output": "新答案"}]).encode(),
        )
        assert again.version.version_label == "1.0.1"
        versions = await service.list_versions(dataset.id, workspace_id)
        assert [item.version_label for item in versions] == ["1.0.1", "1.0.0"]

        # 导出按版本，不按「当前数据集」
        exported = await service.export_version(version.id, workspace_id)
        assert len(exported) == 2
        assert exported[0]["task"]["instruction"] == "订单 A001 能退款吗"

        # CSV 也能导入
        csv_body = "input,expected_output\n订单 A003 能退款吗,false\n".encode()
        csv_outcome = await service.import_file(
            dataset_id=dataset.id,
            workspace_id=workspace_id,
            actor_id=owner,
            filename="samples.csv",
            content=csv_body,
        )
        assert csv_outcome.session.valid_rows == 1
    finally:
        await container.shutdown()


def test_dataset_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

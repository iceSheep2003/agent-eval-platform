"""数据集契约。

定义方：消费方（evaluation 绑定策略时校验「阶段 ∈ 数据集适用阶段」）。
实现方：dataset。

样本读取端口（`SampleReaderPort`）等 execution 出现时再加——那时才有真正的消费方。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..common import DatasetPurpose, EvaluationStage, Id, TaskShape


@dataclass(frozen=True, slots=True)
class DatasetVersionRef:
    id: Id
    dataset_id: Id
    workspace_id: Id
    version_label: str
    purpose: DatasetPurpose
    task_shape: TaskShape
    stages: tuple[EvaluationStage, ...]
    item_count: int
    finalized: bool


@runtime_checkable
class DatasetQueryPort(Protocol):
    """由 dataset 实现；evaluation 用它校验策略与数据集的匹配关系。

    方法名刻意叫 `get_version_ref`：`DatasetService.get_version` 已经存在且返回领域对象，
    同名不同返回类型会让 Protocol 的鸭子类型检查悄悄失效。
    """

    async def get_version_ref(
        self, version_id: Id, workspace_id: Id
    ) -> DatasetVersionRef | None: ...


__all__ = ["DatasetQueryPort", "DatasetVersionRef"]

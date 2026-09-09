"""数据集契约。

定义方：消费方（evaluation 绑定策略时校验「阶段 ∈ 数据集适用阶段」）。
实现方：dataset。

样本读取端口（`SampleReaderPort`）等 execution 出现时再加——那时才有真正的消费方。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from typing import Any, Mapping, Sequence

from ..common import DatasetPurpose, EvaluationStage, Id, JsonValue, TaskShape


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


__all__ = [
    "DatasetQueryPort",
    "DatasetVersionRef",
    "SampleReaderPort",
    "SampleRef",
]


@dataclass(frozen=True, slots=True)
class SampleRef:
    """执行面读到的样本。**`private` 里的期望结果绝不进 Agent 输入。**"""

    id: Id
    dataset_version_id: Id
    workspace_id: Id
    tenant_id: Id | None
    index: int
    instruction: str
    context: Mapping[str, JsonValue]
    expected_output: JsonValue | None
    protocol: str


@runtime_checkable
class SampleReaderPort(Protocol):
    """由 dataset 实现；execution 展开 Trial 时按页读取。"""

    async def count(self, version_id: Id) -> int: ...

    async def read_page(
        self, version_id: Id, *, limit: int = 200, offset: int = 0
    ) -> Sequence[SampleRef]: ...

    async def get_sample(self, sample_id: Id) -> SampleRef | None: ...

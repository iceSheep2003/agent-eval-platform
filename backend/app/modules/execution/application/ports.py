"""execution 自己的端口。

`RuntimePort` / `RuntimeSpec` / `RuntimeHandle` / `InvocationContext` 已经**有第二个消费方**
（deployment 也要起/停实例），所以它们搬到了 `contracts.execution`——
按契约生长规则，出现第二个消费者就该升级为契约。

这里只留 execution 独有的 `RunContext`（带 run/trial/sample 信息）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ....contracts.common import Id
from ....contracts.execution import (
    InvocationContext,
    InvokeResult,
    RuntimeHandle,
    RuntimePort,
    RuntimeSpec,
)


@dataclass(frozen=True, slots=True)
class RunContext(InvocationContext):
    """Trial 上下文。比 `InvocationContext` 多出的字段是评测特有的。"""

    run_id: Id
    trial_id: Id
    sample_id: Id
    attempt_no: int


__all__ = [
    "InvocationContext",
    "InvokeResult",
    "RunContext",
    "RuntimeHandle",
    "RuntimePort",
    "RuntimeSpec",
]

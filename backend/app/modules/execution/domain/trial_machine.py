"""Trial 执行状态机。

一次 Trial 从排队到出分要经过若干阶段，**不同协议（单轮问答 / 工具循环 / 环境型）
走的路径不一样**。把路径写成显式状态机，而不是在 handler 里堆 if：

- 合法迁移集中在一张表里，看代码就知道「下一步能去哪」；
- 非法迁移直接抛错，状态错乱不会被静默接受；
- 每种协议的差异收敛到 `application/plans/`，状态机本身不感知业务。

与 `ExecutionStatus`（落库用）的关系：这里更细。`PROVISIONING` / `SCORING` 在库里
都记为 `running`，`SETTLED` 记为 `succeeded`——库里的字段是给查询用的粗粒度视图。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from ....contracts.common import ExecutionStatus


class TrialState(StrEnum):
    PENDING = "pending"
    #: 起环境：拉镜像、注入凭证、等健康检查
    PROVISIONING = "provisioning"
    #: 调用被测对象（可能多轮）
    RUNNING = "running"
    #: 跑指标
    SCORING = "scoring"
    #: 正常终态：有产出，可以判分
    SETTLED = "settled"
    #: 环境或调用失败（模型超时、工具不可用）
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    #: 该协议在本期不支持——**明确跳过**，不假装跑过（否则会污染通过率）
    SKIPPED = "skipped"


TERMINAL_STATES: frozenset[TrialState] = frozenset(
    {
        TrialState.SETTLED,
        TrialState.FAILED,
        TrialState.TIMED_OUT,
        TrialState.CANCELLED,
        TrialState.SKIPPED,
    }
)

#: 合法迁移表。不在表里的组合一律拒绝。
ALLOWED_TRANSITIONS: Mapping[TrialState, frozenset[TrialState]] = {
    # 还没起环境就可能失败（例如版本没有 entrypoint）；也可能直接跳过
    TrialState.PENDING: frozenset(
        {TrialState.PROVISIONING, TrialState.FAILED, TrialState.CANCELLED, TrialState.SKIPPED}
    ),
    TrialState.PROVISIONING: frozenset(
        {TrialState.RUNNING, TrialState.FAILED, TrialState.TIMED_OUT, TrialState.CANCELLED}
    ),
    # 多轮协议会在 RUNNING 里自循环；单轮协议直接进 SCORING
    TrialState.RUNNING: frozenset(
        {TrialState.RUNNING, TrialState.SCORING, TrialState.FAILED, TrialState.TIMED_OUT, TrialState.CANCELLED}
    ),
    TrialState.SCORING: frozenset(
        {TrialState.SETTLED, TrialState.FAILED, TrialState.CANCELLED}
    ),
    # 终态没有出边
    TrialState.SETTLED: frozenset(),
    TrialState.FAILED: frozenset(),
    TrialState.TIMED_OUT: frozenset(),
    TrialState.CANCELLED: frozenset(),
    TrialState.SKIPPED: frozenset(),
}

#: 状态机状态 → 落库用的执行状态。
STORAGE_STATUS: Mapping[TrialState, ExecutionStatus] = {
    TrialState.PENDING: ExecutionStatus.PENDING,
    TrialState.PROVISIONING: ExecutionStatus.RUNNING,
    TrialState.RUNNING: ExecutionStatus.RUNNING,
    TrialState.SCORING: ExecutionStatus.RUNNING,
    TrialState.SETTLED: ExecutionStatus.SUCCEEDED,
    TrialState.FAILED: ExecutionStatus.FAILED,
    TrialState.TIMED_OUT: ExecutionStatus.TIMED_OUT,
    TrialState.CANCELLED: ExecutionStatus.CANCELLED,
    # 跳过不是「执行成功」，但它确实跑完了流程——用 succeeded + verdict=skip 表达
    TrialState.SKIPPED: ExecutionStatus.SUCCEEDED,
}


class IllegalTransition(RuntimeError):
    """状态机拒绝了这次迁移。出现在这里说明代码有 bug，不该被 catch 掉。"""


@dataclass
class TrialMachine:
    """一次 Trial 的状态机实例。

    刻意是**可变对象**：它就是「当前走到哪了」的载体。领域层其余部分用冻结 dataclass，
    但状态机需要记录迁移历史，冻结反而别扭。
    """

    state: TrialState = TrialState.PENDING
    history: list[TrialState] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.history = [self.state]

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def can(self, target: TrialState) -> bool:
        return target in ALLOWED_TRANSITIONS[self.state]

    def to(self, target: TrialState) -> TrialState:
        # 原地迁移是幂等的 no-op：调用方（方案的兜底、重复触发）不必先判断当前状态
        if target is self.state:
            return self.state
        if self.is_terminal:
            raise IllegalTransition(f"{self.state} 是终态，不能再迁移到 {target}")
        if not self.can(target):
            raise IllegalTransition(f"不允许从 {self.state} 迁移到 {target}")
        self.state = target
        self.history.append(target)
        return self.state

    @property
    def storage_status(self) -> ExecutionStatus:
        return STORAGE_STATUS[self.state]

    def path(self) -> str:
        return " → ".join(item.value for item in self.history)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "IllegalTransition",
    "STORAGE_STATUS",
    "TERMINAL_STATES",
    "TrialMachine",
    "TrialState",
]

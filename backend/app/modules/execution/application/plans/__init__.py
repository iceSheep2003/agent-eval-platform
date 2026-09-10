"""按**任务协议**分派的执行方案。

同一个 `Trial`，协议不同则「怎么跑」完全不同：

| 协议 | 执行方案 | 何时算结束 |
| --- | --- | --- |
| `qa/v1` | 一次调用 → 拿输出 | 调用返回 |
| `tool-loop/v1` | 多轮调用，上一轮输出回灌成 observation | Agent 声明终态，或到步数上限 |
| `agentic-bench/v1` | 需要环境生命周期（setup/step/finish + 隐藏 verifier） | **本期不支持，明确跳过** |

新增一种协议 = 新增一个文件 + 在 `_PLANS` 里注册，不动 `_execute_trial`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .....contracts.common import Id, TaskProtocol
from .....contracts.dataset import SampleRef
from .....contracts.asset import AssetVersionRef
from ...domain.models import Run, Trial
from ...domain.trial_machine import TrialState, TrialMachine
from ..ports import InvocationContext, RuntimePort, RuntimeSpec


@dataclass(frozen=True, slots=True)
class TrialContext:
    """方案执行一次 Trial 需要的全部输入。

    `payload` **只含公开输入**——`expected_output` 绝不在这里，它只给评估器。
    """

    run: Run
    trial: Trial
    sample: SampleRef | None
    version: AssetVersionRef
    runtime_spec: RuntimeSpec
    runtime_ctx: InvocationContext
    payload: Mapping[str, Any]
    #: 多轮协议的最大轮数，取自样本的 limits，缺省 12
    max_steps: int = 12


@dataclass(frozen=True, slots=True)
class TrialOutcome:
    """方案跑完的结果。状态由方案自己决定，handler 只负责落库。"""

    state: TrialState
    output: Any | None = None
    error: str | None = None
    trace_id: Id | None = None
    duration_ms: int | None = None
    cost_usd: float = 0.0
    steps: int = 0
    note: str | None = None

    @property
    def is_settled(self) -> bool:
        return self.state is TrialState.SETTLED


@runtime_checkable
class TrialPlan(Protocol):
    protocol: TaskProtocol

    async def execute(
        self, ctx: TrialContext, runtime: RuntimePort, machine: TrialMachine
    ) -> TrialOutcome: ...


def plan_for(protocol: TaskProtocol) -> TrialPlan:
    from .agentic import AgenticPlan
    from .qa import QaPlan
    from .tool_loop import ToolLoopPlan

    plans: dict[TaskProtocol, TrialPlan] = {
        TaskProtocol.QA: QaPlan(),
        TaskProtocol.TOOL_LOOP: ToolLoopPlan(),
        TaskProtocol.AGENTIC: AgenticPlan(),
    }
    plan = plans.get(protocol)
    if plan is None:
        raise NotImplementedError(f"协议 {protocol} 还没有执行方案")
    return plan


__all__ = [
    "TrialContext",
    "TrialOutcome",
    "TrialPlan",
    "plan_for",
]

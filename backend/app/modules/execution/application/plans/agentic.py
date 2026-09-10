"""`agentic-bench/v1`：环境型任务。

这类任务需要环境生命周期（setup / reset / step / finish）、隐藏状态和
Agent 不可见的 Verifier——属于 Harness 的范畴（架构文档 §9）。

**本期不实现，明确跳过。** 不假装跑过：如果按单轮问答的方式执行 agentic 样本，
它会「成功」但什么都没验证，那些假通过会直接污染通过率和发布门禁。
"""

from __future__ import annotations

from .....contracts.common import TaskProtocol
from ...domain.trial_machine import TrialMachine, TrialState
from ..ports import RuntimePort
from . import TrialContext, TrialOutcome

UNSUPPORTED_NOTE = (
    "环境型任务（agentic-bench/v1）需要环境生命周期与隐藏 Verifier，"
    "属 Harness 范畴，本期未接入；该 Trial 记为跳过，不计入通过率"
)


class AgenticPlan:
    protocol = TaskProtocol.AGENTIC

    async def execute(
        self, ctx: TrialContext, runtime: RuntimePort, machine: TrialMachine
    ) -> TrialOutcome:
        machine.to(TrialState.SKIPPED)
        return TrialOutcome(state=TrialState.SKIPPED, note=UNSUPPORTED_NOTE, steps=0)

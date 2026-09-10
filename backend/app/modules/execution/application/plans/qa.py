"""`qa/v1`：单轮问答。

给输入、拿输出，中间没有环境交互。这是最简方案，也是其余方案的退化形态。
"""

from __future__ import annotations

import logging
import time

from .....contracts.common import TaskProtocol
from ...domain.trial_machine import TrialMachine, TrialState
from ..ports import RuntimePort
from . import TrialContext, TrialOutcome

logger = logging.getLogger(__name__)


class QaPlan:
    protocol = TaskProtocol.QA

    async def execute(
        self, ctx: TrialContext, runtime: RuntimePort, machine: TrialMachine
    ) -> TrialOutcome:
        started = time.perf_counter()
        machine.to(TrialState.PROVISIONING)
        try:
            handle = await runtime.provision(ctx.runtime_spec, ctx.runtime_ctx)
        except Exception as exc:  # noqa: BLE001 - 起环境失败要如实记录，不能吞
            logger.warning("provision 失败: %r", exc)
            machine.to(TrialState.FAILED)
            return TrialOutcome(state=TrialState.FAILED, error=f"环境准备失败：{exc}")

        try:
            machine.to(TrialState.RUNNING)
            result = await runtime.invoke(handle, ctx.payload, ctx.runtime_ctx)
        finally:
            await runtime.teardown(handle)

        duration_ms = result.duration_ms or int((time.perf_counter() - started) * 1000)
        if result.error is not None:
            state = TrialState.TIMED_OUT if result.timed_out else TrialState.FAILED
            machine.to(state)
            return TrialOutcome(
                state=state,
                error=result.error,
                duration_ms=duration_ms,
                cost_usd=result.cost_usd,
                steps=1,
            )

        machine.to(TrialState.SCORING)
        return TrialOutcome(
            state=TrialState.SETTLED,
            output=result.output,
            trace_id=result.trace_id,
            duration_ms=duration_ms,
            cost_usd=result.cost_usd,
            steps=1,
        )

"""`tool-loop/v1`：多轮工具循环。

Agent 每轮返回一个 Action（或声明终态），平台把它执行成 Observation 再回灌，
直到 Agent 说「完成」或达到步数上限。

信封约定沿用 `examples/agent_package_template` 里的 `agentic-bench/v1`：

    继续：{"action": {"name": ..., "arguments": {...}}}
    终态：{"output": ..., "terminal": true}

**步数上限是硬约束**：Agent 陷入循环时不能无限跑下去——既烧钱也永远出不了分。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from .....contracts.common import TaskProtocol
from ...domain.trial_machine import TrialMachine, TrialState
from ..ports import RuntimePort
from . import TrialContext, TrialOutcome

logger = logging.getLogger(__name__)

TERMINAL_KEYS = ("terminal", "done", "finished")


def is_terminal(output: Any) -> bool:
    """Agent 是否声明了终态。

    只认结构化信封——把任意字符串当终态会让「没有工具可调」和「完成任务」
    混成一回事。
    """
    if not isinstance(output, Mapping):
        return False
    if any(output.get(key) is True for key in TERMINAL_KEYS):
        return True
    # 有 output 且没有 action，视为已经给出最终答案
    return "output" in output and "action" not in output


def extract_action(output: Any) -> Mapping[str, Any] | None:
    if isinstance(output, Mapping) and isinstance(output.get("action"), Mapping):
        return output["action"]  # type: ignore[return-value]
    return None


def final_output(output: Any) -> Any:
    """从终态信封里取最终答案；没有信封就直接用原值。"""
    if isinstance(output, Mapping) and "output" in output:
        return output["output"]
    return output


class ToolLoopPlan:
    protocol = TaskProtocol.TOOL_LOOP

    async def execute(
        self, ctx: TrialContext, runtime: RuntimePort, machine: TrialMachine
    ) -> TrialOutcome:
        started = time.perf_counter()
        machine.to(TrialState.PROVISIONING)
        try:
            handle = await runtime.provision(ctx.runtime_spec, ctx.runtime_ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("provision 失败: %r", exc)
            machine.to(TrialState.FAILED)
            return TrialOutcome(state=TrialState.FAILED, error=f"环境准备失败：{exc}")

        machine.to(TrialState.RUNNING)
        payload: dict[str, Any] = dict(ctx.payload)
        observation: Any = None
        total_cost = 0.0
        trace_id = None
        last_output: Any = None

        try:
            for step in range(1, ctx.max_steps + 1):
                if observation is not None:
                    payload["observation"] = observation
                payload["step"] = step

                result = await runtime.invoke(handle, payload, ctx.runtime_ctx)
                total_cost += result.cost_usd
                trace_id = result.trace_id or trace_id

                if result.error is not None:
                    state = TrialState.TIMED_OUT if result.timed_out else TrialState.FAILED
                    machine.to(state)
                    return TrialOutcome(
                        state=state,
                        error=f"第 {step} 轮失败：{result.error}",
                        trace_id=trace_id,
                        duration_ms=result.duration_ms,
                        cost_usd=total_cost,
                        steps=step,
                    )

                last_output = result.output
                if is_terminal(last_output):
                    machine.to(TrialState.SCORING)
                    return TrialOutcome(
                        state=TrialState.SETTLED,
                        output=final_output(last_output),
                        trace_id=trace_id,
                        duration_ms=result.duration_ms,
                        cost_usd=total_cost,
                        steps=step,
                    )

                # 没到终态：把 Agent 的 Action 作为下一轮的 observation 回灌。
                # 平台不执行 Action —— 环境属于 Harness，这里只做信封搬运。
                observation = extract_action(last_output) or last_output
        finally:
            await runtime.teardown(handle)

        # 步数用尽仍未终态：按「未完成」结算，而不是伪造一个答案
        machine.to(TrialState.SCORING)
        return TrialOutcome(
            state=TrialState.SETTLED,
            output=final_output(last_output),
            trace_id=trace_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=total_cost,
            steps=ctx.max_steps,
            note=f"达到步数上限 {ctx.max_steps} 仍未声明终态",
        )

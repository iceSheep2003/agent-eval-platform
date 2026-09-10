"""执行方案：按协议分派，「怎么跑」的差异不泄漏到 handler。

用一个假 Runtime 驱动——方案是纯编排逻辑，不需要真环境。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pytest

from backend.app.contracts.common import TaskProtocol
from backend.app.contracts.execution import InvokeResult
from backend.app.modules.execution.application.plans import (
    TrialContext,
    plan_for,
)
from backend.app.modules.execution.application.ports import (
    InvocationContext,
    RuntimeHandle,
    RuntimeSpec,
)
from backend.app.modules.execution.domain.trial_machine import TrialState


@dataclass
class FakeRuntime:
    """按脚本逐次返回。脚本用完就重复最后一个。"""

    script: Sequence[InvokeResult]
    calls: list[Mapping[str, Any]] = None  # type: ignore[assignment]
    provisioned: bool = False
    torn_down: bool = False
    provision_error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls = []

    async def provision(self, spec: RuntimeSpec, ctx: InvocationContext) -> RuntimeHandle:
        if self.provision_error is not None:
            raise self.provision_error
        self.provisioned = True
        return RuntimeHandle(id="fake", asset_version_id=spec.asset_version_id)

    async def invoke(
        self, handle: RuntimeHandle, payload: Mapping[str, Any], ctx: InvocationContext
    ) -> InvokeResult:
        self.calls.append(dict(payload))
        index = min(len(self.calls) - 1, len(self.script) - 1)
        return self.script[index]

    async def teardown(self, handle: RuntimeHandle) -> None:
        self.torn_down = True


def context(**overrides: Any) -> TrialContext:
    """QA / ToolLoop 方案不需要 run/trial 本体，这里只填它们真正读取的字段。"""
    payload = overrides.pop("payload", {"__entrypoint__": "fake:run", "input": "hello"})
    return TrialContext(
        run=None,  # type: ignore[arg-type]
        trial=None,  # type: ignore[arg-type]
        sample=overrides.pop("sample", None),
        version=None,  # type: ignore[arg-type]
        runtime_spec=RuntimeSpec(
            asset_id="ast_1", asset_version_id="ver_1", workspace_id="ws_1",
            entrypoint="fake:run",
        ),
        runtime_ctx=InvocationContext(
            workspace_id="ws_1", tenant_id=None, timeout_seconds=5, cost_budget_usd=1
        ),
        payload=payload,
        max_steps=overrides.pop("max_steps", 3),
    )


def test_every_protocol_has_a_plan() -> None:
    """协议是样本上的字段，缺一个就会在跑到时才炸——这里提前拦住。"""
    for protocol in TaskProtocol:
        assert plan_for(protocol).protocol is protocol


# --------------------------------------------------------------------------- #
# qa/v1
# --------------------------------------------------------------------------- #


async def _qa_happy_path() -> None:
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime([InvokeResult(output="hi", duration_ms=12)])
    machine = TrialMachine()
    outcome = await plan_for(TaskProtocol.QA).execute(context(), runtime, machine)

    assert outcome.state is TrialState.SETTLED
    assert outcome.output == "hi"
    assert machine.path() == "pending → provisioning → running → scoring"
    assert runtime.provisioned and runtime.torn_down
    # 只调用一次，且 payload 只含公开输入
    assert runtime.calls == [{"__entrypoint__": "fake:run", "input": "hello"}]


async def _qa_timeout_is_distinct_from_failure() -> None:
    """超时与失败要分开——前者调大超时再试，后者要修代码。"""
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    timed_out = FakeRuntime([InvokeResult(output=None, error="超时", timed_out=True)])
    outcome = await plan_for(TaskProtocol.QA).execute(context(), timed_out, TrialMachine())
    assert outcome.state is TrialState.TIMED_OUT

    failed = FakeRuntime([InvokeResult(output=None, error="炸了")])
    outcome = await plan_for(TaskProtocol.QA).execute(context(), failed, TrialMachine())
    assert outcome.state is TrialState.FAILED


async def _provision_failure_settles_as_failed() -> None:
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime([], provision_error=RuntimeError("镜像拉不下来"))
    machine = TrialMachine()
    outcome = await plan_for(TaskProtocol.QA).execute(context(), runtime, machine)

    assert outcome.state is TrialState.FAILED
    assert "环境准备失败" in (outcome.error or "")
    assert machine.is_terminal


# --------------------------------------------------------------------------- #
# tool-loop/v1
# --------------------------------------------------------------------------- #


async def _tool_loop_feeds_action_back_as_observation() -> None:
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime(
        [
            InvokeResult(output={"action": {"name": "lookup", "arguments": {"id": "A1"}}}),
            InvokeResult(output={"action": {"name": "refund", "arguments": {}}}),
            InvokeResult(output={"output": "已退款", "terminal": True}),
        ]
    )
    machine = TrialMachine()
    outcome = await plan_for(TaskProtocol.TOOL_LOOP).execute(context(), runtime, machine)

    assert outcome.state is TrialState.SETTLED
    assert outcome.output == "已退款"
    assert outcome.steps == 3
    # 第一轮没有 observation，之后每轮把上一轮的 action 回灌
    assert "observation" not in runtime.calls[0]
    assert runtime.calls[1]["observation"] == {"name": "lookup", "arguments": {"id": "A1"}}
    assert runtime.calls[2]["step"] == 3
    assert runtime.torn_down


async def _tool_loop_stops_at_step_limit() -> None:
    """Agent 陷循环时不能无限跑——到上限就按「未完成」结算，不伪造答案。"""
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime([InvokeResult(output={"action": {"name": "loop", "arguments": {}}})])
    outcome = await plan_for(TaskProtocol.TOOL_LOOP).execute(
        context(max_steps=4), runtime, TrialMachine()
    )

    assert len(runtime.calls) == 4
    assert outcome.steps == 4
    assert "步数上限" in (outcome.note or "")


async def _tool_loop_midway_failure_records_step() -> None:
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime(
        [
            InvokeResult(output={"action": {"name": "a", "arguments": {}}}),
            InvokeResult(output=None, error="工具超时", timed_out=True),
        ]
    )
    outcome = await plan_for(TaskProtocol.TOOL_LOOP).execute(context(), runtime, TrialMachine())

    assert outcome.state is TrialState.TIMED_OUT
    assert outcome.steps == 2
    assert "第 2 轮失败" in (outcome.error or "")


# --------------------------------------------------------------------------- #
# agentic-bench/v1
# --------------------------------------------------------------------------- #


async def _agentic_is_skipped_not_faked() -> None:
    """不支持就明确跳过。按单轮跑会给出一堆假通过，直接污染发布门禁。"""
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime([InvokeResult(output="不该被调用")])
    machine = TrialMachine()
    outcome = await plan_for(TaskProtocol.AGENTIC).execute(context(), runtime, machine)

    assert outcome.state is TrialState.SKIPPED
    assert runtime.calls == []  # 一次都没调用
    assert "跳过" in (outcome.note or "")


# --------------------------------------------------------------------------- #
# 终态迁移由 handler 兜底
# --------------------------------------------------------------------------- #


async def _outcome_state_is_always_reachable(protocol: TaskProtocol) -> None:
    """方案返回的终态必须是状态机能到达的——否则 handler 兜底时会抛 IllegalTransition。"""
    from backend.app.modules.execution.domain.trial_machine import TrialMachine

    runtime = FakeRuntime([InvokeResult(output={"output": "ok", "terminal": True})])
    machine = TrialMachine()
    outcome = await plan_for(protocol).execute(context(), runtime, machine)
    machine.to(outcome.state)  # 不抛即通过


# --------------------------------------------------------------------------- #
# 同步包装：仓库未装 pytest-asyncio，统一用 asyncio.run（与其余测试一致）
# --------------------------------------------------------------------------- #


def test_every_protocol_has_a_plan_sync() -> None:
    test_every_protocol_has_a_plan()


def test_qa_happy_path() -> None:
    asyncio.run(_qa_happy_path())


def test_qa_timeout_is_distinct_from_failure() -> None:
    asyncio.run(_qa_timeout_is_distinct_from_failure())


def test_provision_failure_settles_as_failed() -> None:
    asyncio.run(_provision_failure_settles_as_failed())


def test_tool_loop_feeds_action_back_as_observation() -> None:
    asyncio.run(_tool_loop_feeds_action_back_as_observation())


def test_tool_loop_stops_at_step_limit() -> None:
    asyncio.run(_tool_loop_stops_at_step_limit())


def test_tool_loop_midway_failure_records_step() -> None:
    asyncio.run(_tool_loop_midway_failure_records_step())


def test_agentic_is_skipped_not_faked() -> None:
    asyncio.run(_agentic_is_skipped_not_faked())


@pytest.mark.parametrize("protocol", list(TaskProtocol))
def test_outcome_state_is_always_reachable(protocol: TaskProtocol) -> None:
    asyncio.run(_outcome_state_is_always_reachable(protocol))

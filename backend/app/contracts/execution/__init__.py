"""执行契约。

定义方：消费方（dataset 从失败 Trial 沉淀回归样本；portal 按通道调用已发布版本）。
实现方：execution。

只发布被消费的项（G2/G3）。`RuntimePort` / `RuntimeSpec` / `InvocationContext`
只被 execution 与 runtime_adapters 用，留在 `modules/execution/application/ports.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Protocol, runtime_checkable

from ..common import (
    Channel,
    EvaluationStage,
    ExecutionStatus,
    Id,
    JsonValue,
    RunStatus,
    Usage,
    Verdict,
)


@dataclass(frozen=True, slots=True)
class TrialRef:
    """Trial 的只读投影。回流时要拿它的输入、输出与判定。"""

    id: Id
    run_id: Id
    workspace_id: Id
    tenant_id: Id | None
    sample_id: Id
    execution_status: ExecutionStatus
    verdict: Verdict | None
    instruction: str
    output: JsonValue | None
    error: str | None


@runtime_checkable
class TrialQueryPort(Protocol):
    """由 execution 实现；dataset 沉淀回归样本时读。"""

    async def get_trial_ref(
        self, trial_id: Id, workspace_id: Id
    ) -> TrialRef | None: ...


@dataclass(frozen=True, slots=True)
class ChannelInvocation:
    """一次「按通道对话」请求。

    `channel` 决定打哪个版本：execution 把它解析成该通道当前绑定的 `AssetVersionRef`。
    调用方**不能**直接指定版本——否则展示平台的通道切换就只是装饰。
    """

    workspace_id: Id
    asset_id: Id
    channel: Channel
    input: str
    #: 完整对话上下文。多数被测 Agent 只接受 `input`，由适配器按签名过滤。
    messages: tuple[Mapping[str, Any], ...] = ()
    tenant_id: Id | None = None
    timeout_seconds: float = 60.0
    cost_budget_usd: float = 0.0
    #: 调用方自己的请求 ID，用于把平台 Trace 和调用方日志对上。
    request_id: Id | None = None
    credential_id: Id | None = None
    #: 会话 ID。展示平台一次对话 = 一个 thread；为空表示该版本该租户的默认记忆片。
    thread_id: Id | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(dict(item) for item in self.messages))


@dataclass(frozen=True, slots=True)
class InvokeResult:
    """一次调用的结果。`trace_id` 是平台落库后的 Trace ID（可能为 None）。"""

    output: Any | None
    error: str | None = None
    trace_id: Id | None = None
    duration_ms: int | None = None
    cost_usd: float = 0.0
    usage: Usage = field(default_factory=Usage)
    #: 实际命中的版本标签，便于调用方展示「这次打的是哪个版本」。
    version_label: str | None = None


@dataclass(frozen=True, slots=True)
class InvokeEvent:
    """流式调用的一次增量。`error` 与 `delta` 互斥；`finish_reason` 只在最后一帧出现。"""

    delta: str | None = None
    finish_reason: str | None = None
    error: str | None = None
    usage: Usage | None = None


@runtime_checkable
class InvokePort(Protocol):
    """由 execution 实现；portal 的对话中继消费。"""

    async def invoke_channel(self, request: ChannelInvocation) -> InvokeResult: ...

    def stream_channel(self, request: ChannelInvocation) -> AsyncIterator[InvokeEvent]:
        """流式调用。

        **参数校验在产出第一个事件之前完成**：通道没绑版本、版本没有 entrypoint
        这类错误，调用方还能当普通 HTTP 错误处理，不必塞进流里。
        运行时失败则只能作为 `error` 事件送出。
        """
        ...


@dataclass(frozen=True, slots=True)
class EntrypointReport:
    """一个 entrypoint 的**实际能力**（import 之后 inspect 出来的，不是猜的）。

    开发规范要求 Agent 接受 `input` 与 `messages`、可选 `secrets` / `memory`。
    光看 spec 验不出来，必须真的把它 import 进来看签名。
    """

    entrypoint: str
    importable: bool
    #: 能接受平台协议里的哪些形参。
    accepts_input: bool = False
    accepts_messages: bool = False
    accepts_secrets: bool = False
    accepts_memory: bool = False
    accepts_kwargs: bool = False
    #: 异步生成器 → 支持真流式；协程/普通函数 → 一次性。
    is_async_generator: bool = False
    is_async: bool = False
    error: str | None = None

    @property
    def supports_streaming(self) -> bool:
        return self.is_async_generator


@runtime_checkable
class EntrypointProbePort(Protocol):
    """由执行面实现；asset 在校验 Agent 版本时用来做「能不能跑」的验收。"""

    def probe(self, entrypoint: str) -> EntrypointReport: ...


__all__ = [
    "ChannelInvocation",
    "EntrypointProbePort",
    "EntrypointReport",
    "RunQueryPort",
    "RunRef",
    "InvokeEvent",
    "InvokePort",
    "InvokeResult",
    "TrialQueryPort",
    "TrialRef",
]


@dataclass(frozen=True, slots=True)
class RunRef:
    """Run 的只读投影。`gate_decision` 是晋级用例的**硬依据**。"""

    id: Id
    workspace_id: Id
    name: str
    subject_asset_id: Id
    subject_version_id: Id
    dataset_version_id: Id
    stage: EvaluationStage
    status: RunStatus
    gate_decision: Mapping[str, Any] | None = None
    total_trials: int = 0

    @property
    def gate_passed(self) -> bool:
        return bool(self.gate_decision and self.gate_decision.get("passed"))


@runtime_checkable
class RunQueryPort(Protocol):
    """由 execution 实现；delivery 晋级时取门禁判定。"""

    async def get_run_ref(self, run_id: Id, workspace_id: Id) -> RunRef | None: ...

    async def find_gate_run(
        self, version_id: Id, stage: EvaluationStage, workspace_id: Id
    ) -> RunRef | None:
        """找该版本最近一次该阶段且已完成、带门禁判定的 Run。"""
        ...

"""execution 自己的端口。

**刻意不放进 `contracts/`**：`RuntimePort` 只被 execution 消费，
按契约生长规则（G2/G3）它属于模块内部。等第二个消费方出现再提升。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ....contracts.common import Id


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    """启动被测对象所需的最小信息。"""

    asset_id: Id
    asset_version_id: Id
    workspace_id: Id
    entrypoint: str | None
    artifact_ref: str | None = None
    spec: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "spec", dict(self.spec or {}))


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: Id
    trial_id: Id
    workspace_id: Id
    tenant_id: Id | None
    sample_id: Id
    attempt_no: int
    timeout_seconds: float
    cost_budget_usd: float


@dataclass(frozen=True, slots=True)
class RuntimeHandle:
    id: str
    asset_version_id: Id
    endpoint: str | None = None
    ephemeral: bool = True


@dataclass(frozen=True, slots=True)
class InvokeResult:
    """一次调用的结果。`trace_id` 是 SDK 上报后回填的平台 Trace ID（可能为 None）。"""

    output: Any | None
    error: str | None = None
    trace_id: Id | None = None
    duration_ms: int | None = None
    cost_usd: float = 0.0


@runtime_checkable
class RuntimePort(Protocol):
    """执行面。`LocalSandboxRuntime` 是本地确定性实现，k8s 换成 Docker / K8s Adapter。"""

    async def provision(self, spec: RuntimeSpec, ctx: RunContext) -> RuntimeHandle: ...

    async def invoke(
        self, handle: RuntimeHandle, payload: Mapping[str, Any], ctx: RunContext
    ) -> InvokeResult: ...

    async def teardown(self, handle: RuntimeHandle) -> None: ...


__all__ = [
    "InvokeResult",
    "RunContext",
    "RuntimeHandle",
    "RuntimePort",
    "RuntimeSpec",
]

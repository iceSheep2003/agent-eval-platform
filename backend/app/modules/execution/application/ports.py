"""execution 自己的端口。

**刻意不放进 `contracts/`**：`RuntimePort` / `RuntimeSpec` / `InvocationContext`
只被 execution 与 runtime_adapters 消费，按契约生长规则（G2/G3）它们属于模块内部。
跨模块的调用入口是 `contracts.execution.InvokePort`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ....contracts.common import Id
from ....contracts.execution import InvokeResult


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
class InvocationContext:
    """执行面的通用上下文：**一次调用**需要知道的边界与预算。

    `RunContext` 继承它并补上 Trial 专属字段。这样 `RuntimePort` 的签名同时容得下
    「评测里的一次 Trial」和「对话里的一次调用」，而 Trial 侧的必填约束不被放松。
    """

    workspace_id: Id
    tenant_id: Id | None
    timeout_seconds: float
    cost_budget_usd: float


@dataclass(frozen=True, slots=True)
class RunContext(InvocationContext):
    """Trial 上下文。比 `InvocationContext` 多出的字段是评测特有的。"""

    run_id: Id
    trial_id: Id
    sample_id: Id
    attempt_no: int


@dataclass(frozen=True, slots=True)
class RuntimeHandle:
    id: str
    asset_version_id: Id
    endpoint: str | None = None
    ephemeral: bool = True


@runtime_checkable
class RuntimePort(Protocol):
    """执行面。`LocalSandboxRuntime` 是本地确定性实现，k8s 换成 Docker / K8s Adapter。"""

    async def provision(self, spec: RuntimeSpec, ctx: InvocationContext) -> RuntimeHandle: ...

    async def invoke(
        self, handle: RuntimeHandle, payload: Mapping[str, Any], ctx: InvocationContext
    ) -> InvokeResult: ...

    async def teardown(self, handle: RuntimeHandle) -> None: ...


__all__ = [
    "InvocationContext",
    "InvokeResult",
    "RunContext",
    "RuntimeHandle",
    "RuntimePort",
    "RuntimeSpec",
]

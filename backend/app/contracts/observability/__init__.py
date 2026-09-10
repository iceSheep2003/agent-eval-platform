"""可观测性契约。

两条跨模块消费线：
- execution 的 InvokeService 记录一次按通道调用产生的 Trace（`ingested_via="gateway"`）；
- delivery 在 LIVESH→LIVE 晋级时比对影子与基线的真实指标。

**Score 不在这里**：它是 Trial 的产物，与 Run/Trial 同生命周期，归 execution。
SDK 上报仍走 `/v1/traces` 的 NDJSON 入口，与本端口写的调用 Trace 靠
`(asset_id, external_trace_id)` 各占一行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from ..common import Channel, Id, TraceOrigin, Usage, Window

TraceStatus = Literal["success", "error", "timeout", "cancelled"]


@dataclass(frozen=True, slots=True)
class InvocationTrace:
    """一次平台发起的调用事实。不含 Span——那是被测 Agent 自己上报的。"""

    workspace_id: Id
    asset_id: Id
    asset_version_id: Id
    channel: Channel | None
    origin: TraceOrigin
    external_trace_id: str
    name: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None = None
    tenant_id: Id | None = None
    input: Any | None = None
    output: Any | None = None
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    #: 父调用的 **invocation id**（调用方原样传进来的那个，不做变换）。
    #: 与父 Trace 的对应是确定性的：`parent.external_trace_id == f"gw-{parent_invocation_id}"`。
    parent_invocation_id: Id | None = None
    #: 补充事实。**只放指纹类信息**（如用了哪把密钥），不放任何明文。
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class TraceWriterPort(Protocol):
    """由 observability 实现；execution 在调用结束后写一条生产/影子/评测 Trace。"""

    async def record_invocation(self, trace: InvocationTrace) -> Id: ...


@dataclass(frozen=True, slots=True)
class VersionMetrics:
    """某个**具体版本**在某个来源下的运行质量。

    口径显式命名——`success_rate` 是调用成功率，不是任务完成率。
    """

    asset_version_id: Id
    origin: TraceOrigin
    trace_count: int
    success_rate: float | None
    p95_latency_ms: int | None
    average_cost_usd: Decimal

    @property
    def has_samples(self) -> bool:
        return self.trace_count > 0


@runtime_checkable
class VersionMetricsPort(Protocol):
    """由 observability 实现；按「版本 + 来源」取指标。

    影子验证要的正是这个切面：候选版本在 `shadow` 下的表现 vs LIVE 版本在
    `production` 下的表现——不是同一个 Agent 的整体平均。
    """

    async def version_metrics(
        self, asset_version_id: Id, origin: TraceOrigin, window: Window
    ) -> VersionMetrics: ...


__all__ = [
    "InvocationTrace",
    "TraceWriterPort",
    "VersionMetrics",
    "VersionMetricsPort",
]

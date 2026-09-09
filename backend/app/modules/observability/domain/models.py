"""可观测性领域实体。

三类 Trace 共用一张表 + `origin` 判别字段（架构文档 §6.5）：
`production`（真实流量）、`shadow`（影子）、`evaluation`（评测 Trial）。
回流证据不是第四类，而是对既有 Trace 的引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Mapping

from ....contracts.common import Channel, Id, SpanKind, TraceOrigin, Usage

TraceStatus = Literal["success", "error", "timeout", "cancelled"]
SpanStatus = Literal["running", "ok", "error", "cancelled"]
IngestSource = Literal["sdk", "gateway", "runtime"]


@dataclass(frozen=True, slots=True)
class SpanRecord:
    id: Id
    trace_id: Id
    workspace_id: Id
    tenant_id: Id | None
    #: SDK 侧 span_id。同一 trace 的事件可能分多批到达，靠它在批次间去重。
    external_span_id: str
    parent_span_id: Id | None
    kind: SpanKind
    name: str
    status: SpanStatus
    started_at: datetime
    ended_at: datetime | None
    input: Any | None = None
    output: Any | None = None
    usage: Usage = field(default_factory=Usage)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    #: 归因结果：这个 Span 属于哪个能力资产版本。归不上就保持 None。
    resource_asset_id: Id | None = None
    resource_version_id: Id | None = None
    #: declared（来自 Run 冻结快照）/ resolved（按规则匹配）。None = 未归因。
    resource_attribution: str | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() * 1000)


@dataclass(frozen=True, slots=True)
class TraceRecord:
    id: Id
    workspace_id: Id
    tenant_id: Id | None
    origin: TraceOrigin
    asset_id: Id
    asset_version_id: Id
    channel: Channel | None
    run_id: Id | None
    trial_id: Id | None
    external_trace_id: str
    name: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None
    input: Any | None
    output: Any | None
    usage: Usage
    span_count: int
    ingested_via: IngestSource


@dataclass(frozen=True, slots=True)
class SpanNode:
    """Span 树的节点。`depth` 由 `parent_span_id` 计算，供前端树形/时间线视图。"""

    span: SpanRecord
    depth: int
    children: tuple["SpanNode", ...] = ()


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    """显式命名，禁止裸 `success_rate`（需求说明 §12.7）。"""

    asset_id: Id
    window_hours: int
    trace_count: int
    invocation_success_rate: float | None
    p95_latency_ms: int | None
    total_cost_usd: Decimal
    error_count: int


@dataclass(frozen=True, slots=True)
class ResourceMetrics:
    """一个能力资产版本的**使用质量**。口径显式命名，禁止裸 `success_rate`。

    `success_metric` 说明 `success_rate` 是哪个口径：MCP 是工具调用成功率、
    知识库是检索成功率、Skill 是完成率。三者混成一个字段就没法比较了。
    """

    asset_id: Id
    version_id: Id
    window_hours: int
    kind: str
    invocations: int
    error_count: int
    error_rate: float
    p95_latency_ms: int | None
    cost_usd: Decimal
    success_metric: str | None
    success_rate: float | None
    #: 已归因 / 本应归因。掉下去说明**匹配规则**失效，不是资源变差了。
    attribution_coverage: float | None


def build_span_tree(spans: list[SpanRecord]) -> tuple[SpanNode, ...]:
    """按 `parent_span_id` 还原树。孤儿节点（父不在本批）挂到根，避免丢数据。"""
    children: dict[Id | None, list[SpanRecord]] = {}
    ids = {span.id for span in spans}
    for span in spans:
        parent = span.parent_span_id if span.parent_span_id in ids else None
        children.setdefault(parent, []).append(span)

    def build(parent_id: Id | None, depth: int) -> tuple[SpanNode, ...]:
        return tuple(
            SpanNode(span=span, depth=depth, children=build(span.id, depth + 1))
            for span in sorted(
                children.get(parent_id, []), key=lambda item: item.started_at
            )
        )

    return build(None, 0)

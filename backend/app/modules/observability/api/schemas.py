"""observability 的 HTTP DTO。

**注意字段命名**：Trace/Span 用 camelCase，因为前端
`frontend-pro/src/pages/agent-detail/index.tsx` 的 `AgentTrace` / `TraceSpan` 就是
camelCase（`startedAt` / `duration` / `tokens`）。其余接口是 snake_case——
这是原型自身的既成事实，按前端契约走。
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Mapping

from pydantic import BaseModel

from ..domain.models import (
    AgentMetrics,
    ResourceMetrics,
    SpanNode,
    SpanRecord,
    TraceRecord,
)


def _as_text(value: Any) -> str:
    """前端会把字符串再尝试 JSON.parse，所以这里统一给字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


class TraceSpanDTO(BaseModel):
    id: str
    name: str
    type: str
    status: str
    depth: int
    duration: int
    model: str | None = None
    tokens: int | None = None
    cost: float | None = None
    input: str
    output: str
    attributes: dict[str, Any]


class AgentTraceDTO(BaseModel):
    id: str
    name: str
    status: str
    environment: str
    startedAt: str
    duration: int
    tokens: int
    cost: float
    input: str
    output: str
    tenant_id: str | None = None
    spans: list[TraceSpanDTO] = []


class TraceSummaryDTO(BaseModel):
    id: str
    name: str
    status: str
    environment: str
    startedAt: str
    duration: int
    tokens: int
    cost: float
    span_count: int
    tenant_id: str | None = None


class MetricsDTO(BaseModel):
    """指标口径显式命名——不允许出现含义模糊的 `success_rate`。"""

    asset_id: str
    window_hours: int
    trace_count: int
    invocation_success_rate: float | None
    p95_latency_ms: int | None
    total_cost_usd: float
    error_count: int


def span_dto(span: SpanRecord, depth: int) -> TraceSpanDTO:
    return TraceSpanDTO(
        id=span.id,
        name=span.name,
        type=span.kind.value,
        status=span.status,
        depth=depth,
        duration=span.duration_ms or 0,
        model=span.attributes.get("model") if isinstance(span.attributes, Mapping) else None,
        tokens=span.usage.total_tokens or None,
        cost=float(span.usage.cost.amount),
        input=_as_text(span.input),
        output=_as_text(span.output),
        attributes={str(key): value for key, value in dict(span.attributes).items()},
    )


def _flatten(node: SpanNode) -> list[TraceSpanDTO]:
    items = [span_dto(node.span, node.depth)]
    for child in node.children:
        items.extend(_flatten(child))
    return items


def trace_dto(trace: TraceRecord, nodes: tuple[SpanNode, ...] = ()) -> AgentTraceDTO:
    duration = 0
    if trace.ended_at is not None:
        duration = int((trace.ended_at - trace.started_at).total_seconds() * 1000)
    return AgentTraceDTO(
        id=trace.id,
        name=trace.name,
        status=trace.status,
        environment=trace.channel.value if trace.channel else trace.origin.value,
        startedAt=trace.started_at.isoformat(),
        duration=duration,
        tokens=trace.usage.total_tokens,
        cost=float(trace.usage.cost.amount),
        input=_as_text(trace.input),
        output=_as_text(trace.output),
        tenant_id=trace.tenant_id,
        spans=[span for node in nodes for span in _flatten(node)],
    )


def trace_summary_dto(trace: TraceRecord) -> TraceSummaryDTO:
    duration = 0
    if trace.ended_at is not None:
        duration = int((trace.ended_at - trace.started_at).total_seconds() * 1000)
    return TraceSummaryDTO(
        id=trace.id,
        name=trace.name,
        status=trace.status,
        environment=trace.channel.value if trace.channel else trace.origin.value,
        startedAt=trace.started_at.isoformat(),
        duration=duration,
        tokens=trace.usage.total_tokens,
        cost=float(trace.usage.cost.amount),
        span_count=trace.span_count,
        tenant_id=trace.tenant_id,
    )


class ResourceMetricsDTO(BaseModel):
    """能力资产版本的使用质量。`success_metric` 说明 `success_rate` 的口径。"""

    asset_id: str
    version_id: str
    window_hours: int
    kind: str
    invocations: int
    error_count: int
    error_rate: float
    p95_latency_ms: int | None
    cost_usd: float
    success_metric: str | None
    success_rate: float | None
    attribution_coverage: float | None


def resource_metrics_dto(metrics: ResourceMetrics) -> ResourceMetricsDTO:
    cost = metrics.cost_usd
    return ResourceMetricsDTO(
        asset_id=metrics.asset_id,
        version_id=metrics.version_id,
        window_hours=metrics.window_hours,
        kind=metrics.kind,
        invocations=metrics.invocations,
        error_count=metrics.error_count,
        error_rate=metrics.error_rate,
        p95_latency_ms=metrics.p95_latency_ms,
        cost_usd=float(cost if isinstance(cost, Decimal) else Decimal(str(cost))),
        success_metric=metrics.success_metric,
        success_rate=metrics.success_rate,
        attribution_coverage=metrics.attribution_coverage,
    )


def metrics_dto(metrics: AgentMetrics) -> MetricsDTO:
    cost = metrics.total_cost_usd
    return MetricsDTO(
        asset_id=metrics.asset_id,
        window_hours=metrics.window_hours,
        trace_count=metrics.trace_count,
        invocation_success_rate=metrics.invocation_success_rate,
        p95_latency_ms=metrics.p95_latency_ms,
        total_cost_usd=float(cost if isinstance(cost, Decimal) else Decimal(str(cost))),
        error_count=metrics.error_count,
    )

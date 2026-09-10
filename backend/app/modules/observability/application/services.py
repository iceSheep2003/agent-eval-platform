"""observability 用例：Trace 上报、查询、指标。

上报语义是**宽松接受 + 逐条回执**：SDK 的 `HttpSink` 失败会静默吞掉，
服务端如果再整批 4xx，Trace 就无声丢失了。所以坏行只回执不报错。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

from ....contracts.asset import (
    AttributionTargetPort,
    CredentialContext,
    CredentialResolverPort,
)
from ....contracts.common import Channel, Id, TraceOrigin
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.observability import InvocationTrace
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.attribution import AttributionSource, attribute_span
from ..domain.models import (
    AgentMetrics,
    ResourceMetrics,
    SpanNode,
    SpanRecord,
    TraceRecord,
    build_span_tree,
)
from ..infrastructure.repositories import TraceRepository
from ..infrastructure.sdk_event_adapter import AdaptedTrace, SdkEventAdapter, group_by_trace

MAX_EVENTS_PER_BATCH = 1000
MAX_BATCH_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class IngestResult:
    """一次上报的结果。

    两种情况分开报告，便于调用方判断是「首次上报」还是「增量补齐」：
    - `accepted_traces`：新建，或补进了新 span
    - `updated_traces`：trace 已存在，只更新了已有 span（例如 `span_finished` 后到）

    重复重放会落进 `updated_traces`——平台把同样的值再写一遍，结果不变。
    真正的去重由 `(asset_id, external_trace_id)` 与 `(trace_id, external_span_id)`
    两个唯一约束保证，不靠这里分类。
    """

    accepted_traces: tuple[Id, ...] = ()
    updated_traces: tuple[Id, ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()  # (external_trace_id, 原因)
    dropped_events: int = 0

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_traces)


@dataclass(frozen=True, slots=True)
class TraceQuery:
    asset_id: Id
    origin: TraceOrigin | None = None
    status: str | None = None
    keyword: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class TraceService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        credentials: CredentialResolverPort,
        *,
        origin: TraceOrigin = TraceOrigin.PRODUCTION,
        attributions: AttributionTargetPort | None = None,
    ) -> None:
        self._db = database
        self._clock = clock
        self._credentials = credentials
        self._adapter = SdkEventAdapter(origin=origin)
        self._attributions = attributions

    # -- 归因 ----------------------------------------------------------------

    async def _attribute(self, adapted: AdaptedTrace) -> AdaptedTrace:
        """把 Span 归因到能力资产版本。

        评测 Trace 带 `asset_version_id`（来自 Run 的冻结快照）→ `declared`；
        生产 Trace 没带 → 回退到该资产的 LIVE 版本 → `resolved`。
        归不上就保持 NULL——**宁可没有数据，也不要假数据**。
        """
        if self._attributions is None or not adapted.spans:
            return adapted
        trace = adapted.trace
        targets = await self._attributions.attribution_targets(
            workspace_id=trace.workspace_id,
            asset_id=trace.asset_id,
            version_id=trace.asset_version_id or None,
        )
        if not targets:
            return adapted
        source: AttributionSource = "declared" if trace.asset_version_id else "resolved"
        spans = []
        for span in adapted.spans:
            hit = attribute_span(
                span_kind=span.kind.value,
                name=span.name,
                attributes=span.attributes,
                targets=targets,
                source=source,
            )
            if hit is None:
                spans.append(span)
                continue
            spans.append(
                replace(
                    span,
                    resource_asset_id=hit.asset_id,
                    resource_version_id=hit.version_id,
                    resource_attribution=hit.source,
                )
            )
        return replace(adapted, spans=tuple(spans))

    # -- 上报 ----------------------------------------------------------------

    async def ingest_ndjson(
        self, body: bytes, credential: CredentialContext
    ) -> IngestResult:
        if len(body) > MAX_BATCH_BYTES:
            raise DomainError(Errors.INGEST_BATCH_TOO_LARGE)

        events: list[Mapping[str, Any]] = []
        rejected: list[tuple[str, str]] = []
        dropped = 0
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(events) >= MAX_EVENTS_PER_BATCH:
                dropped += 1
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue
            # 没有 trace_id 的事件无法归属，算丢弃并计数——不静默消失
            if isinstance(parsed, Mapping) and parsed.get("trace_id"):
                events.append(parsed)
            else:
                dropped += 1

        accepted: list[Id] = []
        updated: list[Id] = []
        for external_trace_id, group in group_by_trace(events).items():
            adapted = self._adapter.adapt(
                group, credential=credential, external_trace_id=external_trace_id
            )
            if adapted is None:
                rejected.append((external_trace_id, Errors.INGEST_MALFORMED_EVENT.code))
                continue
            adapted = await self._attribute(adapted)
            async with UnitOfWork(self._db) as uow:
                trace_id, fresh, touched = await TraceRepository(uow.session).upsert(
                    adapted.trace, adapted.spans
                )
                await uow.commit()
            (accepted if fresh else updated).append(trace_id)

        return IngestResult(
            accepted_traces=tuple(accepted),
            updated_traces=tuple(updated),
            rejected=tuple(rejected),
            dropped_events=dropped,
        )

    async def resolve_credential(self, raw_key: str) -> CredentialContext:
        context = await self._credentials.resolve_credential(raw_key)
        if context is None or context.asset_id is None:
            raise DomainError(Errors.CREDENTIAL_EXPIRED, "密钥无效或已吊销")
        return context

    async def record_invocation(self, trace: InvocationTrace) -> Id:
        """记录一次平台自己发起的调用（网关/展示平台）。

        实现 `contracts.observability.TraceWriterPort`。没有 Span——Span 是被测 Agent
        自己通过 SDK 上报的，两条线在 `(asset_id, external_trace_id)` 上各占一行。
        """
        record = TraceRecord(
            id=new_id("trace"),
            workspace_id=trace.workspace_id,
            tenant_id=trace.tenant_id,
            origin=trace.origin,
            asset_id=trace.asset_id,
            asset_version_id=trace.asset_version_id,
            channel=trace.channel,
            run_id=None,
            trial_id=None,
            external_trace_id=trace.external_trace_id,
            name=trace.name,
            status=trace.status,
            started_at=trace.started_at,
            ended_at=trace.ended_at or self._clock.now(),
            input=trace.input,
            output=trace.output,
            usage=trace.usage,
            span_count=0,
            ingested_via="gateway",
        )
        async with UnitOfWork(self._db) as uow:
            trace_id, _, _ = await TraceRepository(uow.session).upsert(record, ())
            await uow.commit()
        return trace_id

    # -- 查询 ----------------------------------------------------------------

    async def list_traces(
        self, workspace_id: Id, query: TraceQuery, tenant_ids: Sequence[Id] | None
    ) -> tuple[Sequence[TraceRecord], int]:
        async with UnitOfWork(self._db) as uow:
            return await TraceRepository(uow.session).list_for_asset(
                workspace_id,
                query.asset_id,
                tenant_ids=tenant_ids,
                origin=query.origin,
                status=query.status,
                keyword=query.keyword,
                limit=query.limit,
                offset=query.offset,
            )

    async def get_trace(self, trace_id: Id, workspace_id: Id) -> TraceRecord:
        async with UnitOfWork(self._db) as uow:
            trace = await TraceRepository(uow.session).get(trace_id, workspace_id)
        if trace is None:
            raise NotFound("Trace", trace_id)
        return trace

    async def span_tree(self, trace_id: Id) -> tuple[SpanNode, ...]:
        async with UnitOfWork(self._db) as uow:
            spans = list(await TraceRepository(uow.session).spans_for(trace_id))
        return build_span_tree(spans)

    async def resource_metrics(
        self,
        *,
        workspace_id: Id,
        resource_asset_id: Id,
        resource_version_id: Id,
        kind: str,
        window_hours: int = 24,
        consumer_asset_ids: Sequence[Id] = (),
    ) -> ResourceMetrics:
        """能力资产版本的用量与质量。数据来源是**已归因的 Span**，不是 Trace 聚合。"""
        since = self._clock.now() - timedelta(hours=window_hours)
        async with UnitOfWork(self._db) as uow:
            repo = TraceRepository(uow.session)
            spans = list(
                await repo.resource_version_spans(workspace_id, resource_version_id, since)
            )
            coverage = (0, 0)
            metric_name, span_kind = _SUCCESS_METRIC_BY_KIND.get(kind, (None, ""))
            if metric_name and consumer_asset_ids:
                coverage = await repo.attribution_coverage(
                    workspace_id, resource_asset_id, consumer_asset_ids, span_kind, since
                )

        invocations = len(spans)
        # Span 的终态字面量是 `ok` / `error`（见 domain.models.SpanStatus），不是 `success`。
        errors = sum(1 for span in spans if span.status == "error")
        successes = sum(1 for span in spans if span.status == "ok")
        durations = [
            span.duration_ms for span in spans if span.duration_ms is not None
        ]
        cost = sum((span.usage.cost.amount for span in spans), Decimal("0"))
        attributed, candidates = coverage
        return ResourceMetrics(
            asset_id=resource_asset_id,
            version_id=resource_version_id,
            window_hours=window_hours,
            kind=kind,
            invocations=invocations,
            error_count=errors,
            error_rate=(errors / invocations) if invocations else 0.0,
            p95_latency_ms=_percentile(durations, 95),
            cost_usd=cost,
            success_metric=metric_name,
            success_rate=(successes / invocations) if invocations and metric_name else None,
            attribution_coverage=(attributed / candidates) if candidates else None,
        )

    async def agent_metrics(
        self,
        workspace_id: Id,
        asset_id: Id,
        *,
        window_hours: int = 24,
        tenant_ids: Sequence[Id] | None = None,
    ) -> AgentMetrics:
        since = self._clock.now() - timedelta(hours=window_hours)
        async with UnitOfWork(self._db) as uow:
            repo = TraceRepository(uow.session)
            total, success, errors, cost = await repo.aggregate(
                workspace_id, asset_id, since, tenant_ids
            )
            durations = list(await repo.durations(workspace_id, asset_id, since))
        return AgentMetrics(
            asset_id=asset_id,
            window_hours=window_hours,
            trace_count=total,
            invocation_success_rate=(success / total) if total else None,
            p95_latency_ms=_percentile(durations, 95),
            total_cost_usd=cost if isinstance(cost, Decimal) else Decimal(str(cost)),
            error_count=errors,
        )


#: 能力资产 kind → 该类资源的成功率口径名 + 对应的 Span 类型。
_SUCCESS_METRIC_BY_KIND: Mapping[str, tuple[str, str]] = {
    "mcp": ("tool_success_rate", "tool"),
    "knowledge_base": ("retriever_success_rate", "retriever"),
    "skill": ("skill_completion_rate", "agent"),
}


def _percentile(values: Sequence[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(percentile / 100 * len(ordered)) - 1))
    return ordered[index]

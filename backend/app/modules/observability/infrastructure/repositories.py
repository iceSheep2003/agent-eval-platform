"""observability 仓储。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import Channel, SpanKind, TraceOrigin, Usage
from ....shared.clock import ensure_aware
from ..domain.models import SpanRecord, TraceRecord
from .tables import SpanRow, TraceRow


def _usage(row: Any) -> Usage:
    return Usage(
        input_tokens=int(row.input_tokens or 0),
        output_tokens=int(row.output_tokens or 0),
        cost=type(Usage().cost)(Decimal(str(row.cost_usd or 0))),
    )


def _trace(row: TraceRow) -> TraceRecord:
    return TraceRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        tenant_id=row.tenant_id,
        origin=TraceOrigin(row.origin),
        asset_id=row.asset_id,
        asset_version_id=row.asset_version_id,
        channel=Channel(row.channel) if row.channel else None,
        run_id=row.run_id,
        trial_id=row.trial_id,
        external_trace_id=row.external_trace_id,
        name=row.name,
        status=row.status,  # type: ignore[arg-type]
        started_at=ensure_aware(row.started_at),
        ended_at=ensure_aware(row.ended_at) if row.ended_at else None,
        input=row.input,
        output=row.output,
        usage=_usage(row),
        span_count=row.span_count,
        ingested_via=row.ingested_via,  # type: ignore[arg-type]
    )


def _span(row: SpanRow) -> SpanRecord:
    return SpanRecord(
        id=row.id,
        trace_id=row.trace_id,
        workspace_id=row.workspace_id,
        tenant_id=row.tenant_id,
        external_span_id=row.external_span_id,
        parent_span_id=row.parent_span_id,
        kind=SpanKind(row.kind),
        name=row.name,
        status=row.status,  # type: ignore[arg-type]
        started_at=ensure_aware(row.started_at),
        ended_at=ensure_aware(row.ended_at) if row.ended_at else None,
        input=row.input,
        output=row.output,
        usage=_usage(row),
        attributes=dict(row.attributes or {}),
        error_type=row.error_type,
        error_message=row.error_message,
        resource_asset_id=row.resource_asset_id,
        resource_version_id=row.resource_version_id,
        resource_attribution=row.resource_attribution,
    )


class TraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, trace_id: str, workspace_id: str) -> TraceRecord | None:
        stmt = select(TraceRow).where(
            TraceRow.id == trace_id, TraceRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _trace(row) if row else None

    async def find_by_external(self, asset_id: str, external_trace_id: str) -> TraceRecord | None:
        stmt = select(TraceRow).where(
            TraceRow.asset_id == asset_id, TraceRow.external_trace_id == external_trace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _trace(row) if row else None

    async def list_for_asset(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        tenant_ids: Sequence[str] | None = None,
        origin: TraceOrigin | None = None,
        status: str | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[TraceRecord], int]:
        stmt = select(TraceRow).where(
            TraceRow.workspace_id == workspace_id, TraceRow.asset_id == asset_id
        )
        count_stmt = select(func.count()).select_from(TraceRow).where(
            TraceRow.workspace_id == workspace_id, TraceRow.asset_id == asset_id
        )
        filters = []
        if tenant_ids is not None:
            filters.append(TraceRow.tenant_id.in_(list(tenant_ids)))
        if origin is not None:
            filters.append(TraceRow.origin == origin.value)
        if status:
            filters.append(TraceRow.status == status)
        if keyword:
            like = f"%{keyword}%"
            filters.append(TraceRow.external_trace_id.ilike(like) | TraceRow.name.ilike(like))
        for condition in filters:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        stmt = stmt.order_by(TraceRow.started_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        total = int((await self._session.execute(count_stmt)).scalar_one())
        return [_trace(row) for row in rows], total

    async def spans_for(self, trace_id: str) -> Sequence[SpanRecord]:
        stmt = (
            select(SpanRow)
            .where(SpanRow.trace_id == trace_id)
            .order_by(SpanRow.started_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_span(row) for row in rows]

    async def upsert(
        self, trace: TraceRecord, spans: Sequence[SpanRecord]
    ) -> tuple[str, int, int]:
        """事件级幂等：trace 已存在时补新 span 并更新已知 span。

        SDK 的 `HttpSink.flush()` 可能把同一 trace 的事件分多批发出
        （`span_started` 先到、`span_finished` 后到是常态），整条 trace 去重会让
        span 永久缺失、根 span 卡在 running。

        返回 `(trace_id, 新增 span 数, 更新 span 数)`。
        """
        existing = await self.find_by_external(trace.asset_id, trace.external_trace_id)
        if existing is None:
            self.add(trace, spans)
            return trace.id, len(spans), 0

        known = set(
            (
                await self._session.execute(
                    select(SpanRow.external_span_id).where(SpanRow.trace_id == existing.id)
                )
            )
            .scalars()
            .all()
        )
        fresh = [span for span in spans if span.external_span_id not in known]
        for span in fresh:
            self._session.add(self._span_row(span, trace_id=existing.id))

        # 已知 span 也要更新：`span_started` 先到、`span_finished` 后到是常态，
        # 只插不更会让根 span 永远停在 running。
        for span in spans:
            if span.external_span_id not in known:
                continue
            await self._session.execute(
                update(SpanRow)
                .where(
                    SpanRow.trace_id == existing.id,
                    SpanRow.external_span_id == span.external_span_id,
                )
                .values(
                    name=span.name or SpanRow.name,
                    status=span.status,
                    started_at=span.started_at,
                    ended_at=span.ended_at if span.ended_at is not None else SpanRow.ended_at,
                    input=span.input if span.input is not None else SpanRow.input,
                    output=span.output if span.output is not None else SpanRow.output,
                    input_tokens=span.usage.input_tokens,
                    output_tokens=span.usage.output_tokens,
                    cost_usd=span.usage.cost.amount,
                    attributes=dict(span.attributes),
                    error_type=span.error_type,
                    error_message=span.error_message,
                )
            )

        updated = len(spans) - len(fresh)
        total_spans = len(known) + len(fresh)
        merged_usage = await self._sum_usage(existing.id)
        await self._session.execute(
            update(TraceRow)
            .where(TraceRow.id == existing.id)
            .values(
                name=trace.name or existing.name,
                status=trace.status,
                started_at=min(trace.started_at, existing.started_at),
                ended_at=max(
                    [value for value in (trace.ended_at, existing.ended_at) if value],
                    default=None,
                ),
                output=trace.output if trace.output is not None else existing.output,
                span_count=total_spans,
                input_tokens=merged_usage.input_tokens,
                output_tokens=merged_usage.output_tokens,
                cost_usd=merged_usage.cost.amount,
            )
        )
        return existing.id, len(fresh), updated

    async def _sum_usage(self, trace_id: str) -> Usage:
        row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(SpanRow.input_tokens), 0),
                    func.coalesce(func.sum(SpanRow.output_tokens), 0),
                    func.coalesce(func.sum(SpanRow.cost_usd), 0),
                ).where(SpanRow.trace_id == trace_id)
            )
        ).one()
        return Usage(
            input_tokens=int(row[0] or 0),
            output_tokens=int(row[1] or 0),
            cost=type(Usage().cost)(Decimal(str(row[2] or 0))),
        )

    def _span_row(self, span: SpanRecord, *, trace_id: str) -> SpanRow:
        return SpanRow(
            id=span.id,
            external_span_id=span.external_span_id,
            trace_id=trace_id,
            workspace_id=span.workspace_id,
            tenant_id=span.tenant_id,
            parent_span_id=span.parent_span_id,
            kind=span.kind.value,
            name=span.name,
            status=span.status,
            started_at=span.started_at,
            ended_at=span.ended_at,
            input=span.input,
            output=span.output,
            input_tokens=span.usage.input_tokens,
            output_tokens=span.usage.output_tokens,
            cost_usd=span.usage.cost.amount,
            attributes=dict(span.attributes),
            error_type=span.error_type,
            error_message=span.error_message,
            resource_asset_id=span.resource_asset_id,
            resource_version_id=span.resource_version_id,
            resource_attribution=span.resource_attribution,
        )

    def add(self, trace: TraceRecord, spans: Sequence[SpanRecord]) -> None:
        self._session.add(
            TraceRow(
                id=trace.id,
                workspace_id=trace.workspace_id,
                tenant_id=trace.tenant_id,
                origin=trace.origin.value,
                asset_id=trace.asset_id,
                asset_version_id=trace.asset_version_id,
                channel=trace.channel.value if trace.channel else None,
                run_id=trace.run_id,
                trial_id=trace.trial_id,
                external_trace_id=trace.external_trace_id,
                name=trace.name,
                status=trace.status,
                started_at=trace.started_at,
                ended_at=trace.ended_at,
                input=trace.input,
                output=trace.output,
                input_tokens=trace.usage.input_tokens,
                output_tokens=trace.usage.output_tokens,
                cost_usd=trace.usage.cost.amount,
                span_count=trace.span_count,
                ingested_via=trace.ingested_via,
            )
        )
        for span in spans:
            self._session.add(self._span_row(span, trace_id=trace.id))

    async def aggregate(
        self, workspace_id: str, asset_id: str, since: datetime, tenant_ids: Sequence[str] | None
    ) -> tuple[int, int, int, Decimal]:
        """返回 (总数, 成功数, 错误数, 总成本)。延迟分位数在服务层算。"""
        stmt = select(
            func.count(),
            func.sum(case((TraceRow.status == "success", 1), else_=0)),
            func.sum(case((TraceRow.status == "error", 1), else_=0)),
            func.sum(TraceRow.cost_usd),
        ).where(
            TraceRow.workspace_id == workspace_id,
            TraceRow.asset_id == asset_id,
            TraceRow.started_at >= since,
        )
        if tenant_ids is not None:
            stmt = stmt.where(TraceRow.tenant_id.in_(list(tenant_ids)))
        row = (await self._session.execute(stmt)).one()
        return (
            int(row[0] or 0),
            int(row[1] or 0),
            int(row[2] or 0),
            Decimal(str(row[3] or 0)),
        )

    async def resource_version_spans(
        self,
        workspace_id: str,
        resource_version_id: str,
        since: datetime,
    ) -> Sequence[SpanRecord]:
        """某个能力资产版本被调用的 Span。归因写在 Span 上，所以这里直接查 Span 表。"""
        stmt = (
            select(SpanRow)
            .where(
                SpanRow.workspace_id == workspace_id,
                SpanRow.resource_version_id == resource_version_id,
                SpanRow.started_at >= since,
            )
            .order_by(SpanRow.started_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_span(row) for row in rows]

    async def attribution_coverage(
        self,
        workspace_id: str,
        resource_asset_id: str,
        consumer_asset_ids: Sequence[str],
        span_kind: str,
        since: datetime,
    ) -> tuple[int, int]:
        """返回 (已归因到该资源的 Span 数, 本应归因的候选 Span 数)。

        分母只算**引用该资源的 Agent** 产生的同类 Span——拿全工作区做分母没有意义。
        """
        if not consumer_asset_ids:
            return (0, 0)
        base = (
            SpanRow.workspace_id == workspace_id,
            SpanRow.kind == span_kind,
            SpanRow.started_at >= since,
            SpanRow.trace_id.in_(
                select(TraceRow.id).where(
                    TraceRow.workspace_id == workspace_id,
                    TraceRow.asset_id.in_(list(consumer_asset_ids)),
                )
            ),
        )
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(SpanRow).where(*base)
                )
            ).scalar_one()
            or 0
        )
        attributed = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(SpanRow)
                    .where(*base, SpanRow.resource_asset_id == resource_asset_id)
                )
            ).scalar_one()
            or 0
        )
        return (attributed, total)

    async def durations(self, workspace_id: str, asset_id: str, since: datetime) -> Sequence[int]:
        stmt = select(TraceRow.started_at, TraceRow.ended_at).where(
            TraceRow.workspace_id == workspace_id,
            TraceRow.asset_id == asset_id,
            TraceRow.started_at >= since,
            TraceRow.ended_at.is_not(None),
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            int((ensure_aware(ended) - ensure_aware(started)).total_seconds() * 1000)
            for started, ended in rows
        ]

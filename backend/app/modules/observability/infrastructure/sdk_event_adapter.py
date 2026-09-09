"""SDK 事件 → 平台 Trace/Span。

**这是防腐层**：SDK 的 `TraceEvent` 形状（`payload` 包裹、`trace_id`/`span_id`、
无 `tenant_id`）与平台模型不同，转换只发生在这里。SDK 升级不动平台模型，
平台改模型也不动 SDK——这是「不改 SDK 事件形状」这个决策的落地方式。

必须容忍：未知 `event_type`、缺字段、乱序到达、批次跨多个 trace。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from ....contracts.asset import CredentialContext
from ....contracts.common import Channel, Id, SpanKind, TraceOrigin, Usage
from ....shared.clock import ensure_aware
from ....shared.ids import new_id
from ....shared.redaction import redact
from ..domain.models import SpanRecord, TraceRecord

#: SDK 的 kind → 平台 SpanKind。`workflow` 归到 agent。
_KIND_MAP: Mapping[str, SpanKind] = {
    "agent": SpanKind.AGENT,
    "workflow": SpanKind.AGENT,
    "llm": SpanKind.LLM,
    "tool": SpanKind.TOOL,
    "retriever": SpanKind.RETRIEVER,
}

#: SDK span 状态 → 平台状态。
_SPAN_STATUS: Mapping[str, str] = {
    "running": "running",
    "ok": "ok",
    "error": "error",
    "cancelled": "cancelled",
}

_TRACE_STATUS: Mapping[str, str] = {
    "success": "success",
    "error": "error",
    "timeout": "timeout",
    "cancelled": "cancelled",
}


def unwrap_ref(ref: Any) -> Any | None:
    """SDK 的 `bounded_ref`：小值在 `inline`，大值只有摘要或 artifact 引用。"""
    if ref is None or not isinstance(ref, Mapping):
        return ref
    if "inline" in ref:
        return ref["inline"]
    if "artifact_id" in ref:
        return {
            "artifact_id": ref.get("artifact_id"),
            "sha256": ref.get("sha256"),
            "size": ref.get("size"),
        }
    return None


def _parse_time(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return ensure_aware(value)
    if isinstance(value, str):
        try:
            return ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return fallback
    return fallback


def _usage(payload: Mapping[str, Any]) -> Usage:
    raw = payload.get("usage")
    if not isinstance(raw, Mapping):
        return Usage()
    cost = raw.get("cost_usd")
    try:
        amount = Decimal(str(cost)) if cost is not None else Decimal("0")
    except (InvalidOperation, ValueError):
        amount = Decimal("0")
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cost=type(Usage().cost)(amount),
    )


@dataclass
class _SpanBuilder:
    external_id: str
    parent_external_id: str | None
    kind: SpanKind
    name: str
    started_at: datetime
    status: str = "running"
    ended_at: datetime | None = None
    input: Any | None = None
    output: Any | None = None
    usage: Usage = field(default_factory=Usage)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class AdaptedTrace:
    trace: TraceRecord
    spans: tuple[SpanRecord, ...]


class SdkEventAdapter:
    """把一批 SDK 事件折叠成一条 Trace + 若干 Span。"""

    def __init__(self, *, origin: TraceOrigin = TraceOrigin.PRODUCTION) -> None:
        self._origin = origin

    def adapt(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        credential: CredentialContext,
        external_trace_id: str,
        channel: Channel | None = None,
        ingested_via: str = "sdk",
    ) -> AdaptedTrace | None:
        if not events or credential.asset_id is None:
            return None

        now = datetime.now(timezone.utc)
        #: SDK 对 `@observe` 的 Agent **不发 trace_started**（只有 span_* + trace_finished），
        #: 所以起始时间要能从任意事件兜底推出来，否则会退化成「平台接收时间」，
        #: 出现 ended_at < started_at。
        explicit_start: datetime | None = None
        earliest: datetime | None = None
        latest: datetime | None = None
        ended_at: datetime | None = None
        status = "success"
        output: Any = None
        name = ""
        builders: dict[str, _SpanBuilder] = {}

        for event in events:
            event_type = str(event.get("event_type") or "")
            payload = event.get("payload")
            payload = payload if isinstance(payload, Mapping) else {}
            stamp = _parse_time(event.get("timestamp"), now)
            earliest = stamp if earliest is None or stamp < earliest else earliest
            latest = stamp if latest is None or stamp > latest else latest

            if event_type == "trace_started":
                explicit_start = stamp
                if not name:
                    name = str(payload.get("test_case_id") or "")
            elif event_type == "trace_finished":
                ended_at = stamp
                status = _TRACE_STATUS.get(str(payload.get("status")), "success")
                output = unwrap_ref(payload.get("output"))
            elif event_type == "span_started":
                span_id = str(event.get("span_id") or "")
                if span_id:
                    builders[span_id] = _SpanBuilder(
                        external_id=span_id,
                        parent_external_id=payload.get("parent_span_id"),
                        kind=_KIND_MAP.get(str(payload.get("kind")), SpanKind.AGENT),
                        name=str(payload.get("name") or ""),
                        started_at=_parse_time(payload.get("started_at"), stamp),
                        input=unwrap_ref(payload.get("input_ref")),
                        attributes=dict(payload.get("attributes") or {}),
                    )
            elif event_type == "span_finished":
                span_id = str(event.get("span_id") or "")
                builder = builders.get(span_id)
                if builder is None:
                    builder = _SpanBuilder(
                        external_id=span_id or new_id("span"),
                        parent_external_id=payload.get("parent_span_id"),
                        kind=_KIND_MAP.get(str(payload.get("kind")), SpanKind.AGENT),
                        name=str(payload.get("name") or ""),
                        started_at=_parse_time(payload.get("started_at"), stamp),
                    )
                    builders[builder.external_id] = builder
                builder.name = str(payload.get("name") or builder.name)
                builder.status = _SPAN_STATUS.get(str(payload.get("status")), "ok")
                builder.started_at = _parse_time(payload.get("started_at"), builder.started_at)
                builder.ended_at = _parse_time(payload.get("ended_at"), stamp)
                builder.input = unwrap_ref(payload.get("input_ref")) if builder.input is None else builder.input
                builder.output = unwrap_ref(payload.get("output_ref"))
                builder.usage = _usage(payload)
                builder.attributes = dict(payload.get("attributes") or builder.attributes)
                error = payload.get("error")
                if isinstance(error, Mapping):
                    builder.error_type = str(error.get("type") or "") or None
                    builder.error_message = str(error.get("message") or "") or None
            # 其余事件类型（kind 专属事件、error_raised 等）忽略：信息已在 span_* 里

        trace_id = new_id("trace")
        span_id_map = {external: new_id("span") for external in builders}
        spans = tuple(
            SpanRecord(
                id=span_id_map[builder.external_id],
                trace_id=trace_id,
                workspace_id=credential.workspace_id,
                tenant_id=credential.tenant_id,
                external_span_id=builder.external_id,
                parent_span_id=span_id_map.get(builder.parent_external_id or ""),
                kind=builder.kind,
                name=builder.name or "span",
                status=builder.status,  # type: ignore[arg-type]
                started_at=builder.started_at,
                ended_at=builder.ended_at,
                input=redact(builder.input),
                output=redact(builder.output),
                usage=builder.usage,
                attributes=dict(redact(builder.attributes)),
                error_type=builder.error_type,
                error_message=builder.error_message,
            )
            for builder in builders.values()
        )

        usage = Usage(
            input_tokens=sum(span.usage.input_tokens for span in spans),
            output_tokens=sum(span.usage.output_tokens for span in spans),
            cost=type(Usage().cost)(
                sum((span.usage.cost.amount for span in spans), Decimal("0"))
            ),
        )

        started_at = explicit_start or earliest or now
        if ended_at is None:
            ended_at = latest
        if not name:
            # 根 agent span 的名字比一串 uuid 有用得多
            root = next(
                (
                    span
                    for span in spans
                    if span.parent_span_id is None and span.kind is SpanKind.AGENT
                ),
                None,
            )
            name = root.name if root else external_trace_id
        # 兜底修正：极端情况下（时钟回拨、乱序）保证 ended_at 不早于 started_at
        if ended_at is not None and ended_at < started_at:
            ended_at = started_at

        trace = TraceRecord(
            id=trace_id,
            workspace_id=credential.workspace_id,
            tenant_id=credential.tenant_id,
            origin=self._origin,
            asset_id=credential.asset_id,
            asset_version_id="",
            channel=channel,
            run_id=None,
            trial_id=None,
            external_trace_id=external_trace_id,
            name=name,
            status=status,  # type: ignore[arg-type]
            started_at=started_at,
            ended_at=ended_at,
            input=None,
            output=redact(output),
            usage=usage,
            span_count=len(spans),
            ingested_via=ingested_via,  # type: ignore[arg-type]
        )
        return AdaptedTrace(trace=trace, spans=spans)


def group_by_trace(events: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """按 SDK 的 `trace_id` 分组。

    **不要用 `Idempotency-Key` 分组**：它由 SDK 拼的是「批次首尾 sequence」，
    一个批次可能跨多个 trace。
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        external = str(event.get("trace_id") or "")
        if external:
            grouped.setdefault(external, []).append(event)
    return grouped

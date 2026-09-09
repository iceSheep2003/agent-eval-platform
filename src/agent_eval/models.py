"""Public data models for agent-eval-sdk."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(frozen=True)
class ExpectedAction:
    """An optional expected tool/action contract used by component metrics."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    kind: str = "tool_call"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": dict(self.arguments), "kind": self.kind}


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    input: Any
    expected_output: Any | None = None
    context: tuple[Any, ...] = ()
    expected_actions: tuple[ExpectedAction, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", tuple(self.context))
        object.__setattr__(self, "expected_actions", tuple(self.expected_actions))

    def to_dict(self, *, include_private: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "input": self.input,
            "context": list(self.context),
            "expected_actions": [action.to_dict() for action in self.expected_actions],
            "metadata": dict(self.metadata) if include_private else {},
        }
        if include_private:
            result["expected_output"] = self.expected_output
        return result


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class ErrorInfo:
    type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


@dataclass(frozen=True)
class EvidenceRef:
    kind: Literal["event", "span", "artifact"]
    ref: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "ref": self.ref}
        if self.note is not None:
            result["note"] = self.note
        return result


@dataclass(frozen=True)
class Score:
    metric: str
    metric_version: str
    value: float | int | bool | str | None
    status: Literal["pass", "fail", "skip", "error"]
    reason: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()
    evaluator: Mapping[str, Any] | None = None
    duration_ms: float | None = None
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "metric_version": self.metric_version,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
            "evidence": [item.to_dict() for item in self.evidence],
            "evaluator": dict(self.evaluator) if self.evaluator else None,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    kind: str
    name: str
    status: Literal["running", "ok", "error", "cancelled"]
    started_at: datetime
    ended_at: datetime | None = None
    input_ref: Any | None = None
    output_ref: Any | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    usage: Usage | None = None
    error: ErrorInfo | None = None

    @property
    def duration_ms(self) -> float | None:
        if not self.ended_at:
            return None
        return (self.ended_at - self.started_at).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "started_at": isoformat(self.started_at),
            "ended_at": isoformat(self.ended_at),
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "attributes": dict(self.attributes),
            "usage": self.usage.to_dict() if self.usage else None,
            "error": self.error.to_dict() if self.error else None,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    trace_id: str
    span_id: str | None
    sequence: int
    event_type: str
    actor: str
    timestamp: datetime
    payload: Mapping[str, Any]
    visibility: Literal["public", "internal", "secret"] = "public"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "actor": self.actor,
            "timestamp": isoformat(self.timestamp),
            "payload": dict(self.payload),
            "visibility": self.visibility,
        }


@dataclass(frozen=True)
class Trace:
    """A read-only public snapshot of one case's execution facts."""

    trace_id: str
    test_case_id: str
    root_span_id: str | None
    events: tuple[TraceEvent, ...]
    spans: tuple[SpanRecord, ...]
    output: Any | None
    status: Literal["success", "error", "timeout", "cancelled"]

    def find_events(self, event_type: str | None = None, *, kind: str | None = None) -> tuple[TraceEvent, ...]:
        return tuple(
            event
            for event in self.events
            if (event_type is None or event.event_type == event_type)
            and (kind is None or event.payload.get("kind") == kind)
        )

    def find_spans(self, *, kind: str | None = None, name: str | None = None) -> tuple[SpanRecord, ...]:
        return tuple(
            span
            for span in self.spans
            if (kind is None or span.kind == kind) and (name is None or span.name == name)
        )


@dataclass(frozen=True)
class EvaluationTarget:
    case: EvaluationCase
    trace: Trace
    output: Any | None
    status: Literal["success", "error", "timeout", "cancelled"]
    error: ErrorInfo | None = None
    span: SpanRecord | None = None

    @property
    def spans(self) -> tuple[SpanRecord, ...]:
        return self.trace.spans


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    trace_id: str
    status: Literal["success", "error", "timeout", "cancelled"]
    output: Any | None
    error: ErrorInfo | None
    scores: tuple[Score, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scores", tuple(self.scores))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "output": self.output,
            "error": self.error.to_dict() if self.error else None,
            "scores": [score.to_dict() for score in self.scores],
        }


@dataclass(frozen=True)
class Summary:
    case_count: int
    agent_success_count: int
    agent_error_count: int
    timeout_count: int
    metric_error_count: int
    pass_count: int
    fail_count: int
    skip_count: int
    pass_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "agent_success_count": self.agent_success_count,
            "agent_error_count": self.agent_error_count,
            "timeout_count": self.timeout_count,
            "metric_error_count": self.metric_error_count,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "skip_count": self.skip_count,
            "pass_rate": self.pass_rate,
        }


@dataclass(frozen=True)
class EvaluationResult:
    run_id: str
    case_results: tuple[CaseResult, ...]
    summary: Summary
    log_dir: str | None
    status: Literal["completed", "partial", "failed"]

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_results", tuple(self.case_results))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "case_results": [item.to_dict() for item in self.case_results],
            "summary": self.summary.to_dict(),
            "log_dir": self.log_dir,
            "status": self.status,
        }


def error_info(error: BaseException) -> ErrorInfo:
    return ErrorInfo(type=type(error).__name__, message=str(error))


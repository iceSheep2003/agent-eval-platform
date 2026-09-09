"""Context-local tracing primitives: observe, span, and emit."""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import uuid
from dataclasses import replace
from typing import Any, Callable, Mapping

from .models import ErrorInfo, SpanRecord, Trace, TraceEvent, Usage, utc_now
from .serialization import bounded_ref, safe_json, unwrap_ref
from .sinks import CompositeSink, EventSink


class TraceConfig:
    def __init__(
        self,
        *,
        sinks: list[EventSink] | None = None,
        capture_input: bool = True,
        capture_output: bool = True,
        max_value_chars: int = 20_000,
        redact_keys: set[str] | None = None,
        artifact_dir: Any = None,
    ) -> None:
        self.sinks = list(sinks or [])
        self.capture_input = capture_input
        self.capture_output = capture_output
        self.max_value_chars = max(256, max_value_chars)
        self.redact_keys = redact_keys
        self.artifact_dir = artifact_dir


_config = TraceConfig()
_current_trace: contextvars.ContextVar["_TraceBuilder | None"] = contextvars.ContextVar("agent_eval_trace", default=None)
_current_span: contextvars.ContextVar[str | None] = contextvars.ContextVar("agent_eval_span", default=None)


def configure(
    *,
    sinks: list[EventSink] | None = None,
    capture_input: bool = True,
    capture_output: bool = True,
    max_value_chars: int = 20_000,
    redact_keys: set[str] | None = None,
    artifact_dir: Any = None,
) -> None:
    """Configure standalone tracing. ``evaluate`` can still provide per-run sinks."""

    global _config
    _config = TraceConfig(
        sinks=sinks,
        capture_input=capture_input,
        capture_output=capture_output,
        max_value_chars=max_value_chars,
        redact_keys=redact_keys,
        artifact_dir=artifact_dir,
    )


def get_config() -> TraceConfig:
    return _config


def current_trace() -> Trace | None:
    builder = _current_trace.get()
    return builder.snapshot() if builder else None


def current_span() -> SpanRecord | None:
    builder = _current_trace.get()
    span_id = _current_span.get()
    return builder.get_span(span_id) if builder and span_id else None


class _SpanState:
    def __init__(
        self,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        kind: str,
        name: str,
        started_at: Any,
        input_ref: Any,
        attributes: Mapping[str, Any],
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.kind = kind
        self.name = name
        self.status = "running"
        self.started_at = started_at
        self.ended_at = None
        self.input_ref = input_ref
        self.output_ref = None
        self.attributes = dict(attributes)
        self.usage: Usage | None = None
        self.error: ErrorInfo | None = None

    def record(self) -> SpanRecord:
        return SpanRecord(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            kind=self.kind,
            name=self.name,
            status=self.status,
            started_at=self.started_at,
            ended_at=self.ended_at,
            input_ref=self.input_ref,
            output_ref=self.output_ref,
            attributes=dict(self.attributes),
            usage=self.usage,
            error=self.error,
        )


class _TraceBuilder:
    def __init__(self, trace_id: str, test_case_id: str, *, sinks: list[EventSink] | None = None, config: TraceConfig | None = None) -> None:
        self.trace_id = trace_id
        self.test_case_id = test_case_id
        self.root_span_id: str | None = None
        self.output: Any | None = None
        self.status = "success"
        self._events: list[TraceEvent] = []
        self._spans: dict[str, _SpanState] = {}
        self._closed = False
        self._pending_sink_tasks: list[asyncio.Task[Any]] = []
        self.config = config or _config
        self.sink = CompositeSink(sinks if sinks is not None else self.config.sinks)

    def _ref(self, value: Any, *, capture: bool) -> Any | None:
        ref = bounded_ref(
            value,
            max_chars=self.config.max_value_chars,
            capture=capture,
            redact_keys=self.config.redact_keys,
        )
        if ref and ref.get("artifact_required") and self.config.artifact_dir is not None:
            import hashlib
            import json
            from pathlib import Path

            artifact_dir = Path(self.config.artifact_dir)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(safe_json(value, redact_keys=self.config.redact_keys), ensure_ascii=False, sort_keys=True)
            artifact_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            artifact_path = artifact_dir / f"{artifact_id}.json"
            if not artifact_path.exists():
                artifact_path.write_text(encoded + "\n", encoding="utf-8")
            return {
                "artifact_id": artifact_id,
                "mime_type": "application/json",
                "size": ref.get("size"),
                "sha256": artifact_id,
                "preview": ref.get("inline", {}).get("preview"),
            }
        return ref

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        actor: str = "runtime",
        span_id: str | None = None,
        visibility: str = "public",
    ) -> TraceEvent:
        if self._closed:
            return self._events[-1]
        event = TraceEvent(
            event_id=uuid.uuid4().hex,
            trace_id=self.trace_id,
            span_id=span_id,
            sequence=len(self._events) + 1,
            event_type=event_type,
            actor=actor,
            timestamp=utc_now(),
            payload=safe_json(dict(payload or {}), redact_keys=self.config.redact_keys),
            visibility=visibility,  # type: ignore[arg-type]
        )
        self._events.append(event)
        self.sink.emit_sync(event)
        return event

    def start_span(
        self,
        *,
        kind: str,
        name: str,
        input: Any = None,
        attributes: Mapping[str, Any] | None = None,
        capture_input: bool | None = None,
        parent_span_id: str | None = None,
    ) -> _SpanState:
        span_id = uuid.uuid4().hex
        parent = parent_span_id if parent_span_id is not None else _current_span.get()
        state = _SpanState(
            trace_id=self.trace_id,
            span_id=span_id,
            parent_span_id=parent,
            kind=kind,
            name=name,
            started_at=utc_now(),
            input_ref=self._ref(input, capture=self.config.capture_input if capture_input is None else capture_input),
            attributes=safe_json(dict(attributes or {}), redact_keys=self.config.redact_keys),
        )
        self._spans[span_id] = state
        if self.root_span_id is None:
            self.root_span_id = span_id
        self.emit(
            "span_started",
            {
                "kind": kind,
                "name": name,
                "parent_span_id": parent,
                "input_ref": state.input_ref,
                "attributes": state.attributes,
            },
            actor=_actor_for_kind(kind),
            span_id=span_id,
        )
        specific_start = {
            "tool": "tool_called",
            "llm": "llm_started",
            "retriever": "retrieval_started",
            "agent": "agent_started",
            "workflow": "agent_started",
        }.get(kind)
        if specific_start:
            self.emit(specific_start, {"name": name, "input_ref": state.input_ref}, actor=_actor_for_kind(kind), span_id=span_id)
        return state

    def finish_span(
        self,
        state: _SpanState,
        *,
        output: Any = None,
        capture_output: bool | None = None,
        error: BaseException | None = None,
        cancelled: bool = False,
    ) -> None:
        if state.status != "running":
            return
        state.ended_at = utc_now()
        state.output_ref = self._ref(output, capture=self.config.capture_output if capture_output is None else capture_output)
        state.error = ErrorInfo(type=type(error).__name__, message=str(error)) if error else None
        state.status = "cancelled" if cancelled else ("error" if error else "ok")
        self.emit(
            "span_finished",
            {
                "kind": state.kind,
                "name": state.name,
                "status": state.status,
                "input_ref": state.input_ref,
                "output_ref": state.output_ref,
                "attributes": state.attributes,
                "usage": state.usage.to_dict() if state.usage else None,
                "error": state.error.to_dict() if state.error else None,
                "started_at": state.started_at.isoformat(),
                "ended_at": state.ended_at.isoformat() if state.ended_at else None,
            },
            actor=_actor_for_kind(state.kind),
            span_id=state.span_id,
        )
        specific_finish = {
            "tool": "tool_returned",
            "llm": "llm_finished",
            "retriever": "retrieval_finished",
            "agent": "agent_finished",
            "workflow": "agent_finished",
        }.get(state.kind)
        if specific_finish:
            self.emit(
                specific_finish,
                {"name": state.name, "status": state.status, "output_ref": state.output_ref},
                actor=_actor_for_kind(state.kind),
                span_id=state.span_id,
            )

    def get_span(self, span_id: str | None) -> SpanRecord | None:
        state = self._spans.get(span_id or "")
        return state.record() if state else None

    def set_output(self, output: Any) -> None:
        self.output = output

    def finish(self, status: str, output: Any = None) -> None:
        if self._closed:
            return
        self.output = output
        self.status = status
        self.emit("trace_finished", {"status": status, "output": self._ref(output, capture=self.config.capture_output)}, actor="runtime")
        self._closed = True

    def snapshot(self) -> Trace:
        return Trace(
            trace_id=self.trace_id,
            test_case_id=self.test_case_id,
            root_span_id=self.root_span_id,
            events=tuple(self._events),
            spans=tuple(state.record() for state in self._spans.values()),
            output=self.output,
            status=self.status,  # type: ignore[arg-type]
        )

    async def flush(self) -> None:
        if self._pending_sink_tasks:
            await asyncio.gather(*self._pending_sink_tasks, return_exceptions=True)
            self._pending_sink_tasks.clear()
        await self.sink.flush()


def _actor_for_kind(kind: str) -> str:
    if kind in {"llm", "model"}:
        return "model"
    if kind in {"tool", "retriever", "agent", "workflow", "handoff", "guardrail"}:
        return "agent" if kind in {"agent", "workflow", "handoff"} else kind
    return "agent"


class SpanHandle:
    def __init__(
        self,
        *,
        kind: str,
        name: str,
        input: Any = None,
        attributes: Mapping[str, Any] | None = None,
        capture_input: bool | None = None,
        capture_output: bool | None = None,
    ) -> None:
        self.kind = kind
        self.name = name
        self.input = input
        self.attributes = attributes
        self.capture_input = capture_input
        self.capture_output = capture_output
        self.state: _SpanState | None = None
        self.builder: _TraceBuilder | None = None
        self._span_token: contextvars.Token[str | None] | None = None
        self._trace_token: contextvars.Token[_TraceBuilder | None] | None = None
        self._standalone = False
        self._output_set = False
        self._output: Any = None

    def _open(self) -> "SpanHandle":
        builder = _current_trace.get()
        if builder is None:
            builder = _TraceBuilder(uuid.uuid4().hex, "standalone")
            self._trace_token = _current_trace.set(builder)
            self._standalone = True
        self.builder = builder
        self.state = builder.start_span(
            kind=self.kind,
            name=self.name,
            input=self.input,
            attributes=self.attributes,
            capture_input=self.capture_input,
        )
        self._span_token = _current_span.set(self.state.span_id)
        return self

    def _close(self, *, output: Any = None, error: BaseException | None = None, cancelled: bool = False) -> None:
        if not self.builder or not self.state:
            return
        self.builder.finish_span(
            self.state,
            output=self._output if self._output_set else output,
            capture_output=self.capture_output,
            error=error,
            cancelled=cancelled,
        )
        if self._span_token is not None:
            _current_span.reset(self._span_token)
            self._span_token = None
        if self._standalone and self._trace_token is not None:
            self.builder.finish("cancelled" if cancelled else ("error" if error else "success"), output)
            _current_trace.reset(self._trace_token)
            self._trace_token = None

    def set_output(self, output: Any) -> None:
        self._output = output
        self._output_set = True
        if self.state and self.builder:
            self.state.output_ref = self.builder._ref(output, capture=self.builder.config.capture_output if self.capture_output is None else self.capture_output)

    def set_usage(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        if self.state:
            self.state.usage = Usage(input_tokens, output_tokens, total_tokens, cost_usd)

    def __enter__(self) -> "SpanHandle":
        return self._open()

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        self._close(error=exc, cancelled=exc_type is asyncio.CancelledError)
        return False

    async def __aenter__(self) -> "SpanHandle":
        return self._open()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        self._close(error=exc, cancelled=exc_type is asyncio.CancelledError)
        if self.builder:
            await self.builder.flush()
        return False


def span(
    *,
    kind: str = "custom",
    name: str | None = None,
    input: Any = None,
    attributes: Mapping[str, Any] | None = None,
    capture_input: bool | None = None,
    capture_output: bool | None = None,
) -> SpanHandle:
    return SpanHandle(
        kind=kind,
        name=name or kind,
        input=input,
        attributes=attributes,
        capture_input=capture_input,
        capture_output=capture_output,
    )


def emit(
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    actor: str = "runtime",
    span_id: str | None = None,
    visibility: str = "public",
) -> TraceEvent | None:
    builder = _current_trace.get()
    if builder is None:
        return None
    return builder.emit(event_type, payload, actor=actor, span_id=span_id or _current_span.get(), visibility=visibility)


def _call_input(target: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], *, structured: bool = False) -> Any:
    if structured:
        try:
            bound = inspect.signature(target).bind_partial(*args, **kwargs)
            return {key: value for key, value in bound.arguments.items() if key != "self"}
        except (TypeError, ValueError):
            return {"args": list(args), "kwargs": kwargs}
    if not kwargs and len(args) == 1:
        return args[0]
    return {"args": list(args), "kwargs": kwargs}


def observe(
    func: Callable[..., Any] | None = None,
    *,
    kind: str = "custom",
    name: str | None = None,
    capture_input: bool | None = None,
    capture_output: bool | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> Callable[..., Any]:
    """Decorate sync or async functions without changing their call semantics."""

    def decorator(target: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or getattr(target, "__qualname__", target.__name__)
        if inspect.iscoroutinefunction(target):

            @functools.wraps(target)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with span(
                    kind=kind,
                    name=span_name,
                    input=_call_input(target, args, kwargs, structured=kind in {"tool", "retriever", "llm"}),
                    attributes=attributes,
                    capture_input=capture_input,
                    capture_output=capture_output,
                ) as current:
                    try:
                        result = await target(*args, **kwargs)
                        current.set_output(result)
                        return result
                    except BaseException:
                        raise

            return async_wrapper

        @functools.wraps(target)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(
                kind=kind,
                name=span_name,
                input=_call_input(target, args, kwargs, structured=kind in {"tool", "retriever", "llm"}),
                attributes=attributes,
                capture_input=capture_input,
                capture_output=capture_output,
            ) as current:
                result = target(*args, **kwargs)
                current.set_output(result)
                return result

        return sync_wrapper

    return decorator(func) if func is not None else decorator


def _new_trace(trace_id: str, case_id: str, sinks: list[EventSink], config: TraceConfig | None = None) -> _TraceBuilder:
    builder = _TraceBuilder(trace_id, case_id, sinks=sinks, config=config)
    builder.emit("trace_started", {"test_case_id": case_id}, actor="runtime")
    return builder


class trace_scope:
    """Internal async context for evaluate; public users normally use ``span``."""

    def __init__(self, builder: _TraceBuilder) -> None:
        self.builder = builder
        self.token: contextvars.Token[_TraceBuilder | None] | None = None
        self.span_token: contextvars.Token[str | None] | None = None

    async def __aenter__(self) -> _TraceBuilder:
        self.token = _current_trace.set(self.builder)
        self.span_token = _current_span.set(None)
        return self.builder

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if self.span_token is not None:
            _current_span.reset(self.span_token)
        if self.token is not None:
            _current_trace.reset(self.token)
        return False


def trace_from_events(events: list[TraceEvent]) -> Trace:
    """Rebuild enough Span/Trace state for offline rescore from events.jsonl."""

    if not events:
        raise ValueError("trace has no events")
    trace_id = events[0].trace_id
    started = next((event for event in events if event.event_type == "trace_started"), events[0])
    case_id = str(started.payload.get("test_case_id", "unknown"))
    state: dict[str, dict[str, Any]] = {}
    root: str | None = None
    output = None
    status = "success"
    for event in events:
        if event.event_type == "span_started" and event.span_id:
            state[event.span_id] = {
                "trace_id": trace_id,
                "span_id": event.span_id,
                "parent_span_id": event.payload.get("parent_span_id"),
                "kind": event.payload.get("kind", "custom"),
                "name": event.payload.get("name", "span"),
                "status": "running",
                "started_at": event.timestamp,
                "input_ref": event.payload.get("input_ref"),
                "attributes": event.payload.get("attributes", {}),
            }
            root = root or event.span_id
        elif event.event_type == "span_finished" and event.span_id:
            item = state.setdefault(event.span_id, {"trace_id": trace_id, "span_id": event.span_id, "started_at": event.timestamp})
            item.update(
                {
                    "status": event.payload.get("status", "ok"),
                    "ended_at": event.timestamp,
                    "output_ref": event.payload.get("output_ref"),
                    "error": event.payload.get("error"),
                }
            )
        elif event.event_type == "trace_finished":
            status = event.payload.get("status", "success")
            output = unwrap_ref(event.payload.get("output"))
    spans: list[SpanRecord] = []
    for item in state.values():
        error = item.get("error")
        spans.append(
            SpanRecord(
                trace_id=trace_id,
                span_id=item["span_id"],
                parent_span_id=item.get("parent_span_id"),
                kind=item.get("kind", "custom"),
                name=item.get("name", "span"),
                status=item.get("status", "ok"),
                started_at=item.get("started_at", events[0].timestamp),
                ended_at=item.get("ended_at"),
                input_ref=item.get("input_ref"),
                output_ref=item.get("output_ref"),
                attributes=item.get("attributes", {}),
                error=ErrorInfo(**error) if isinstance(error, Mapping) and "type" in error else None,
            )
        )
    return Trace(trace_id, case_id, root, tuple(events), tuple(spans), output, status)  # type: ignore[arg-type]

"""Evaluation execution, durable logs, and offline re-scoring."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .models import (
    CaseResult,
    ErrorInfo,
    EvaluationCase,
    EvaluationResult,
    EvaluationTarget,
    Score,
    Summary,
    Trace,
    TraceEvent,
    error_info,
)
from .serialization import safe_json
from .sinks import EventSink, JsonlSink
from .tracing import TraceConfig, _new_trace, get_config, span, trace_from_events, trace_scope


def _run_id(name: str | None) -> str:
    prefix = (name or "run").strip().lower().replace(" ", "-")[:32]
    return f"{prefix or 'run'}-{uuid.uuid4().hex[:10]}"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(safe_json(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, values: Iterable[Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(safe_json(value), ensure_ascii=False, separators=(",", ":")) + "\n")


async def _call_agent(agent: Callable[[Any], Any], value: Any) -> Any:
    if inspect.iscoroutinefunction(agent):
        result = await agent(value)
    else:
        result = await asyncio.to_thread(agent, value)
    if inspect.isawaitable(result):
        return await result
    return result


async def _score_metric(metric: Any, target: EvaluationTarget) -> list[Score]:
    started = time.perf_counter()
    try:
        result = metric.score(target)
        if inspect.isawaitable(result):
            result = await result
        scores = list(result) if isinstance(result, (list, tuple)) else [result]
        completed: list[Score] = []
        for score in scores:
            if not isinstance(score, Score):
                raise TypeError(f"Metric {metric!r} returned {type(score).__name__}, expected Score")
            if score.duration_ms is None:
                score = Score(
                    metric=score.metric,
                    metric_version=score.metric_version,
                    value=score.value,
                    status=score.status,
                    reason=score.reason,
                    evidence=score.evidence,
                    evaluator=score.evaluator,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    cost_usd=score.cost_usd,
                )
            completed.append(score)
        return completed
    except Exception as exc:
        return [
            Score(
                metric=getattr(metric, "name", type(metric).__name__),
                metric_version=getattr(metric, "version", "unknown"),
                value=None,
                status="error",
                reason=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        ]


def _summary(results: Sequence[CaseResult]) -> Summary:
    scores = [score for result in results for score in result.scores]
    passed = sum(score.status == "pass" for score in scores)
    failed = sum(score.status == "fail" for score in scores)
    skipped = sum(score.status == "skip" for score in scores)
    denominator = passed + failed
    pass_rate = passed / denominator if denominator else (1.0 if all(item.status == "success" for item in results) else 0.0)
    return Summary(
        case_count=len(results),
        agent_success_count=sum(item.status == "success" for item in results),
        agent_error_count=sum(item.status == "error" for item in results),
        timeout_count=sum(item.status == "timeout" for item in results),
        metric_error_count=sum(score.status == "error" for score in scores),
        pass_count=passed,
        fail_count=failed,
        skip_count=skipped,
        pass_rate=pass_rate,
    )


async def evaluate(
    *,
    agent: Callable[[Any], Any],
    cases: Iterable[EvaluationCase],
    metrics: Iterable[Any] = (),
    name: str | None = None,
    concurrency: int = 1,
    timeout: float | None = None,
    seed: int | None = None,
    sink: EventSink | None = None,
    output_dir: str | Path | None = None,
) -> EvaluationResult:
    """Run an Agent over cases and return traces plus independent metric scores."""

    case_list = list(cases)
    if len({case.id for case in case_list}) != len(case_list):
        raise ValueError("EvaluationCase.id must be unique within a run")
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    if seed is not None:
        random.seed(seed)

    run_id = _run_id(name)
    log_path = Path(output_dir) if output_dir is not None else None
    durable: JsonlSink | None = None
    if log_path:
        log_path.mkdir(parents=True, exist_ok=True)
        (log_path / "artifacts").mkdir(exist_ok=True)
        durable = JsonlSink(log_path / "events.jsonl")
        _write_json(log_path / "run.json", {
            "run_id": run_id,
            "name": name,
            "status": "running",
            "case_count": len(case_list),
            "concurrency": concurrency,
            "timeout": timeout,
            "seed": seed,
            "sdk_version": "0.1.0",
            "python": os.sys.version,
        })
        _append_jsonl(log_path / "cases.jsonl", [case.to_dict(include_private=True) for case in case_list])

    base_config = get_config()
    sinks = [*base_config.sinks, *[item for item in (sink, durable) if item is not None]]
    config = TraceConfig(
        capture_input=base_config.capture_input,
        capture_output=base_config.capture_output,
        max_value_chars=base_config.max_value_chars,
        redact_keys=base_config.redact_keys,
        artifact_dir=(log_path / "artifacts") if log_path else base_config.artifact_dir,
    )
    semaphore = asyncio.Semaphore(concurrency)
    metric_list = list(metrics)
    results: list[CaseResult | None] = [None] * len(case_list)

    async def run_case(index: int, case: EvaluationCase) -> None:
        async with semaphore:
            builder = _new_trace(uuid.uuid4().hex, case.id, sinks, config=config)
            output: Any = None
            error: ErrorInfo | None = None
            status: str = "success"
            async with trace_scope(builder):
                try:
                    async with span(kind="agent", name=getattr(agent, "__name__", "agent"), input=case.input) as root:
                        try:
                            if timeout is None:
                                output = await _call_agent(agent, case.input)
                            else:
                                output = await asyncio.wait_for(_call_agent(agent, case.input), timeout)
                            root.set_output(output)
                        except asyncio.TimeoutError as exc:
                            status = "timeout"
                            error = ErrorInfo(type=type(exc).__name__, message=f"agent timed out after {timeout}s")
                            emit_error = builder.emit("error_raised", error.to_dict(), actor="runtime", span_id=builder.root_span_id)
                            del emit_error
                            root._close(error=exc)
                        except asyncio.CancelledError as exc:
                            status = "cancelled"
                            error = error_info(exc)
                            builder.emit("cancellation_requested", error.to_dict(), actor="runtime", span_id=builder.root_span_id)
                            root._close(error=exc, cancelled=True)
                            raise
                        except Exception as exc:
                            status = "error"
                            error = error_info(exc)
                            builder.emit("error_raised", error.to_dict(), actor="runtime", span_id=builder.root_span_id)
                            root._close(error=exc)
                except asyncio.CancelledError:
                    raise
                finally:
                    if status == "success":
                        builder.finish("success", output)
                    elif status == "timeout":
                        builder.finish("timeout", None)
                    elif status == "error":
                        builder.finish("error", None)
                    else:
                        builder.finish("cancelled", None)
                await builder.flush()
            trace = builder.snapshot()
            target = EvaluationTarget(case, trace, output, status, error, trace.spans[0] if trace.spans else None)
            scores: list[Score] = []
            for metric in metric_list:
                scores.extend(await _score_metric(metric, target))
            results[index] = CaseResult(case.id, trace.trace_id, status, output, error, tuple(scores))

    await asyncio.gather(*(run_case(index, case) for index, case in enumerate(case_list)))
    final_results = tuple(item for item in results if item is not None)
    summary = _summary(final_results)
    result = EvaluationResult(run_id, final_results, summary, str(log_path) if log_path else None, "completed")
    if log_path:
        _append_jsonl(log_path / "scores.jsonl", [
            {"case_id": item.case_id, "trace_id": item.trace_id, "scores": [score.to_dict() for score in item.scores]}
            for item in final_results
        ])
        _write_json(log_path / "summary.json", summary.to_dict())
        _write_json(log_path / "run.json", {
            "run_id": run_id,
            "name": name,
            "status": result.status,
            "case_count": len(case_list),
            "concurrency": concurrency,
            "timeout": timeout,
            "seed": seed,
            "sdk_version": "0.1.0",
            "summary": summary.to_dict(),
        })
        if durable:
            await durable.close()
    if sink:
        await sink.flush()
    return result


async def rescore(log_dir: str | Path, *, metrics: Iterable[Any]) -> EvaluationResult:
    """Recompute scores from events.jsonl without invoking the Agent."""

    directory = Path(log_dir)
    cases_by_id: dict[str, EvaluationCase] = {}
    with (directory / "cases.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            raw = json.loads(line)
            cases_by_id[raw["id"]] = EvaluationCase(
                id=raw["id"],
                input=raw.get("input"),
                expected_output=raw.get("expected_output"),
                context=tuple(raw.get("context", [])),
                metadata=raw.get("metadata", {}),
            )
    grouped: dict[str, list[TraceEvent]] = {}
    with (directory / "events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            raw = json.loads(line)
            event = TraceEvent(
                event_id=raw["event_id"],
                trace_id=raw["trace_id"],
                span_id=raw.get("span_id"),
                sequence=raw["sequence"],
                event_type=raw["event_type"],
                actor=raw["actor"],
                timestamp=__import__("datetime").datetime.fromisoformat(raw["timestamp"]),
                payload=raw.get("payload", {}),
                visibility=raw.get("visibility", "public"),
            )
            grouped.setdefault(event.trace_id, []).append(event)
    results: list[CaseResult] = []
    for trace_id, events in grouped.items():
        trace = trace_from_events(sorted(events, key=lambda item: item.sequence))
        case = cases_by_id.get(trace.test_case_id, EvaluationCase(trace.test_case_id, None))
        target = EvaluationTarget(case, trace, trace.output, trace.status)
        scores: list[Score] = []
        for metric in metrics:
            scores.extend(await _score_metric(metric, target))
        results.append(CaseResult(case.id, trace_id, trace.status, trace.output, None, tuple(scores)))
    results.sort(key=lambda item: item.case_id)
    summary = _summary(results)
    run_id = f"rescore-{uuid.uuid4().hex[:10]}"
    _append_jsonl(directory / "scores.jsonl", [
        {"case_id": item.case_id, "trace_id": item.trace_id, "scores": [score.to_dict() for score in item.scores]}
        for item in results
    ])
    _write_json(directory / "summary.json", summary.to_dict())
    return EvaluationResult(run_id, tuple(results), summary, str(directory), "completed")


def evaluate_sync(**kwargs: Any) -> EvaluationResult:
    return asyncio.run(evaluate(**kwargs))

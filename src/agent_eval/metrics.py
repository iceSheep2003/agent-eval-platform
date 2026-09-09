"""Deterministic, dependency-free metrics for the first SDK release."""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, Literal

from .models import EvaluationTarget, EvidenceRef, Score
from .serialization import unwrap_ref


class Metric(Protocol):
    name: str
    version: str
    scope: Literal["case", "trajectory", "span"]

    async def score(self, target: EvaluationTarget) -> Score | list[Score]: ...


def _score(metric: Any, value: Any, status: str, reason: str | None = None, evidence: tuple[EvidenceRef, ...] = ()) -> Score:
    return Score(metric.name, getattr(metric, "version", "1.0.0"), value, status, reason, evidence)


def _case_evidence(target: EvaluationTarget) -> tuple[EvidenceRef, ...]:
    return tuple(EvidenceRef("event", event.event_id) for event in target.trace.events[-3:])


class AnswerExactMatch:
    name = "answer_exact_match"
    version = "1.0.0"
    scope = "case"

    def __init__(self, *, expected: Any = None, normalize: bool = True) -> None:
        self.expected = expected
        self.normalize = normalize

    async def score(self, target: EvaluationTarget) -> Score:
        expected = self.expected if self.expected is not None else target.case.expected_output
        if expected is None:
            return _score(self, None, "skip", "没有提供 expected_output")
        actual = target.output
        if self.normalize and isinstance(actual, str) and isinstance(expected, str):
            actual = actual.strip()
            expected = expected.strip()
        passed = target.status == "success" and actual == expected
        return _score(self, 1.0 if passed else 0.0, "pass" if passed else "fail", None if passed else f"actual={actual!r}, expected={expected!r}", _case_evidence(target))


class AnswerContains:
    name = "answer_contains"
    version = "1.0.0"
    scope = "case"

    def __init__(self, expected: str | None = None) -> None:
        self.expected = expected

    async def score(self, target: EvaluationTarget) -> Score:
        expected = self.expected
        if expected is None and isinstance(target.case.expected_output, str):
            expected = target.case.expected_output
        if expected is None:
            return _score(self, None, "skip", "没有提供 expected_output 或 expected")
        passed = target.status == "success" and expected in str(target.output)
        return _score(self, 1.0 if passed else 0.0, "pass" if passed else "fail", None if passed else f"答案不包含 {expected!r}", _case_evidence(target))


class AnswerJsonSchema:
    name = "answer_json_schema"
    version = "1.0.0"
    scope = "case"

    def __init__(self, schema: Mapping[str, Any]) -> None:
        self.schema = dict(schema)

    def _validate(self, value: Any, schema: Mapping[str, Any], path: str = "$") -> str | None:
        expected_type = schema.get("type")
        types = {
            "object": dict,
            "array": list,
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "null": type(None),
        }
        if expected_type in types and (not isinstance(value, types[expected_type]) or expected_type in {"number", "integer"} and isinstance(value, bool)):
            return f"{path} 类型应为 {expected_type}"
        if isinstance(value, dict):
            for required in schema.get("required", []):
                if required not in value:
                    return f"{path}.{required} 缺失"
            for key, child in schema.get("properties", {}).items():
                if key in value and isinstance(child, Mapping):
                    failure = self._validate(value[key], child, f"{path}.{key}")
                    if failure:
                        return failure
        if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
            for index, item in enumerate(value):
                failure = self._validate(item, schema["items"], f"{path}[{index}]")
                if failure:
                    return failure
        return None

    async def score(self, target: EvaluationTarget) -> Score:
        value = target.output
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                return _score(self, 0.0, "fail", f"不是合法 JSON: {exc}", _case_evidence(target))
        failure = self._validate(value, self.schema)
        passed = target.status == "success" and failure is None
        return _score(self, 1.0 if passed else 0.0, "pass" if passed else "fail", failure, _case_evidence(target))


class TaskCompletion:
    name = "task_completion"
    version = "1.0.0"
    scope = "trajectory"

    async def score(self, target: EvaluationTarget) -> Score:
        passed = target.status == "success" and target.output is not None
        evidence = _case_evidence(target)
        return _score(self, 1.0 if passed else 0.0, "pass" if passed else "fail", None if passed else "Agent 未成功产生最终输出", evidence)


class NoInvalidAction:
    name = "no_invalid_action"
    version = "1.0.0"
    scope = "trajectory"

    async def score(self, target: EvaluationTarget) -> Score:
        invalid = tuple(
            event for event in target.trace.events
            if event.event_type in {"action_invalid", "invalid_action"}
            or event.event_type == "action_validated" and event.payload.get("valid") is False
        )
        evidence = tuple(EvidenceRef("event", event.event_id) for event in invalid)
        return _score(self, 0.0 if invalid else 1.0, "fail" if invalid else "pass", "存在非法 Action" if invalid else None, evidence)


class StepEfficiency:
    name = "step_efficiency"
    version = "1.0.0"
    scope = "trajectory"

    def __init__(self, max_steps: int = 10) -> None:
        self.max_steps = max(1, max_steps)

    async def score(self, target: EvaluationTarget) -> Score:
        step_events = tuple(
            event for event in target.trace.events
            if event.event_type in {"action_proposed", "tool_called", "llm_started"}
        )
        count = len(step_events)
        value = max(0.0, 1.0 - max(0, count - 1) / self.max_steps)
        passed = count <= self.max_steps
        evidence = tuple(EvidenceRef("event", event.event_id) for event in step_events)
        return _score(self, value, "pass" if passed else "fail", None if passed else f"步骤数 {count} 超过上限 {self.max_steps}", evidence)


class ToolNameCorrectness:
    name = "tool_name_correctness"
    version = "1.0.0"
    scope = "span"

    async def score(self, target: EvaluationTarget) -> Score:
        expected = target.case.expected_actions
        actual = [span.name for span in target.trace.find_spans(kind="tool")]
        if not expected:
            return _score(self, None, "skip", "没有提供 expected_actions")
        expected_names = [item.name for item in expected]
        passed = actual == expected_names
        evidence = tuple(EvidenceRef("span", span.span_id) for span in target.trace.find_spans(kind="tool"))
        return _score(self, 1.0 if passed else 0.0, "pass" if passed else "fail", None if passed else f"actual={actual!r}, expected={expected_names!r}", evidence)


class ToolArgumentSchema:
    name = "tool_argument_schema"
    version = "1.0.0"
    scope = "span"

    async def score(self, target: EvaluationTarget) -> Score:
        expected = target.case.expected_actions
        actual_spans = target.trace.find_spans(kind="tool")
        if not expected:
            return _score(self, None, "skip", "没有提供 expected_actions")
        if len(expected) != len(actual_spans):
            return _score(self, 0.0, "fail", "工具调用数量与预期不一致")
        failures: list[str] = []
        for index, (expectation, actual) in enumerate(zip(expected, actual_spans)):
            actual_input = unwrap_ref(actual.input_ref)
            if not isinstance(actual_input, Mapping):
                failures.append(f"第 {index + 1} 个调用没有结构化参数")
                continue
            # An expected action is treated as a partial schema/value contract.
            for key, value in expectation.arguments.items():
                if actual_input.get(key) != value:
                    failures.append(f"第 {index + 1} 个调用参数 {key!r} 不匹配")
        evidence = tuple(EvidenceRef("span", span.span_id) for span in actual_spans)
        return _score(self, 0.0 if failures else 1.0, "fail" if failures else "pass", "; ".join(failures) if failures else None, evidence)


class ToolSuccess:
    name = "tool_success"
    version = "1.0.0"
    scope = "span"

    async def score(self, target: EvaluationTarget) -> Score:
        tools = target.trace.find_spans(kind="tool")
        if not tools:
            return _score(self, None, "skip", "没有工具 Span")
        failed = [span for span in tools if span.status != "ok"]
        evidence = tuple(EvidenceRef("span", span.span_id) for span in tools)
        return _score(self, 0.0 if failed else 1.0, "fail" if failed else "pass", "存在失败的工具调用" if failed else None, evidence)


class LlmCallLatency:
    name = "llm_call_latency"
    version = "1.0.0"
    scope = "span"

    def __init__(self, max_ms: float = 5_000) -> None:
        self.max_ms = max_ms

    async def score(self, target: EvaluationTarget) -> Score:
        spans = target.trace.find_spans(kind="llm")
        if not spans:
            return _score(self, None, "skip", "没有 LLM Span")
        durations = [span.duration_ms or 0.0 for span in spans]
        maximum = max(durations)
        passed = maximum <= self.max_ms
        evidence = tuple(EvidenceRef("span", span.span_id) for span in spans)
        return _score(self, maximum, "pass" if passed else "fail", None if passed else f"最大耗时 {maximum:.1f}ms 超过 {self.max_ms:.1f}ms", evidence)

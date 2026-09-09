"""确定性评估器。

**无状态、无 IO、无随机**——同一个 (期望, 输出) 永远得到同一个判定，
这是门禁结果可复现的前提。轨迹类评估器（工具正确率、步数）需要 Trace，
等 SDK 与 Run 的关联打通后再实现，现在返回 `skip` 而不是伪造分数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ....contracts.common import Determinism

METRIC_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class MetricOutcome:
    metric: str
    metric_version: str
    value: float | int | bool | str | None
    status: str  # pass / fail / skip / error
    reason: str | None = None
    determinism: Determinism = Determinism.DETERMINISTIC


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def evaluate_metric(
    name: str,
    *,
    expected: Any | None,
    output: Any | None,
    execution_error: str | None = None,
) -> MetricOutcome:
    """按评估器名分派。未知评估器返回 `skip`，不冒充通过。"""
    if execution_error is not None:
        return MetricOutcome(
            metric=name,
            metric_version=METRIC_VERSION,
            value=None,
            status="error",
            reason=f"执行失败：{execution_error}",
        )

    if name in {"answer_exact_match", "task_completion"}:
        return _exact_match(name, expected, output)
    if name == "answer_contains":
        return _contains(name, expected, output)
    if name == "answer_json_schema":
        return _json_parseable(name, output)

    # 轨迹类与 LLM Judge 尚未实现——明确标记 skip，避免污染通过率
    return MetricOutcome(
        metric=name,
        metric_version=METRIC_VERSION,
        value=None,
        status="skip",
        reason="该评估器尚未实现（需要 Trace 或 LLM Judge）",
    )


def _exact_match(name: str, expected: Any | None, output: Any | None) -> MetricOutcome:
    if expected is None:
        return MetricOutcome(
            metric=name, metric_version=METRIC_VERSION, value=None, status="skip",
            reason="样本没有期望输出",
        )
    matched = _normalize(expected) == _normalize(output)
    return MetricOutcome(
        metric=name,
        metric_version=METRIC_VERSION,
        value=1.0 if matched else 0.0,
        status="pass" if matched else "fail",
        reason=None if matched else f"期望 {expected!r}，实际 {output!r}",
    )


def _contains(name: str, expected: Any | None, output: Any | None) -> MetricOutcome:
    if expected is None:
        return MetricOutcome(
            metric=name, metric_version=METRIC_VERSION, value=None, status="skip",
            reason="样本没有期望输出",
        )
    needle = _as_text(expected)
    haystack = _as_text(output)
    found = needle in haystack
    return MetricOutcome(
        metric=name,
        metric_version=METRIC_VERSION,
        value=1.0 if found else 0.0,
        status="pass" if found else "fail",
        reason=None if found else f"输出未包含 {needle!r}",
    )


def _json_parseable(name: str, output: Any | None) -> MetricOutcome:
    if output is None:
        return MetricOutcome(
            metric=name, metric_version=METRIC_VERSION, value=None, status="fail",
            reason="没有输出",
        )
    if isinstance(output, (Mapping, list)):
        return MetricOutcome(
            metric=name, metric_version=METRIC_VERSION, value=1.0, status="pass"
        )
    try:
        json.loads(str(output))
    except json.JSONDecodeError as exc:
        return MetricOutcome(
            metric=name, metric_version=METRIC_VERSION, value=0.0, status="fail",
            reason=f"输出不是合法 JSON：{exc.msg}",
        )
    return MetricOutcome(metric=name, metric_version=METRIC_VERSION, value=1.0, status="pass")


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def aggregate_verdict(outcomes: Sequence[MetricOutcome]) -> str | None:
    """把多个指标的判定合成 Trial 的 verdict。

    只要有一个 `fail` 就是 `fail`；全是 `skip` 则没有结论；
    有 `error` 说明评估器本身出问题，单独标出来（不覆盖执行结果）。
    """
    statuses = {item.status for item in outcomes}
    if "fail" in statuses:
        return "fail"
    if "error" in statuses:
        return "error"
    if "pass" in statuses:
        return "pass"
    if "skip" in statuses:
        return "skip"
    return None

"""门禁纯函数的边界值。

门禁是发布把关的硬约束，所以这里测的是「什么情况下必须阻断」，
而不是「正常情况下能过」。
"""

from __future__ import annotations

from backend.app.contracts.common import Determinism, GateAction, GateScope
from backend.app.modules.evaluation.domain.gate import evaluate_gate
from backend.app.modules.evaluation.domain.models import GateRule


def rule(
    key: str,
    threshold: float,
    *,
    comparison: str = "gte",
    action: GateAction = GateAction.BLOCK,
    required_determinism: Determinism | None = None,
    min_samples: int = 0,
) -> GateRule:
    return GateRule(
        name=key,
        metric_key=key,
        threshold=threshold,
        unit="score",
        comparison=comparison,  # type: ignore[arg-type]
        scope=GateScope.WORKSPACE,
        action=action,
        required_determinism=required_determinism,
        min_samples=min_samples,
    )


def test_passes_when_all_blocking_rules_pass() -> None:
    decision = evaluate_gate(
        [rule("task_success_rate", 0.9), rule("safety_violation_rate", 0.01, comparison="lte")],
        {"task_success_rate": 0.95, "safety_violation_rate": 0.0},
    )
    assert decision.passed
    assert decision.blocked_reasons == ()


def test_blocks_on_threshold_boundary() -> None:
    """阈值是闭区间下界：等于门槛算通过，差一点就阻断。"""
    assert evaluate_gate([rule("x", 0.9)], {"x": 0.9}).passed
    blocked = evaluate_gate([rule("x", 0.9)], {"x": 0.899})
    assert not blocked.passed
    assert blocked.blocked_rules == ("x",)


def test_lte_comparison_is_for_lower_is_better() -> None:
    assert evaluate_gate([rule("p95_latency_ms", 1000, comparison="lte")], {"p95_latency_ms": 1000}).passed
    assert not evaluate_gate(
        [rule("p95_latency_ms", 1000, comparison="lte")], {"p95_latency_ms": 1001}
    ).passed


def test_warn_action_does_not_block() -> None:
    decision = evaluate_gate([rule("x", 0.9, action=GateAction.WARN)], {"x": 0.1})
    assert decision.passed  # 只是告警
    assert decision.results[0].passed is False
    assert decision.results[0].action is GateAction.WARN


def test_missing_metric_is_skipped_not_blocked() -> None:
    decision = evaluate_gate([rule("x", 0.9)], {})
    assert decision.passed
    assert decision.results[0].skipped
    assert decision.results[0].reason == "指标缺失"


def test_min_samples_only_warns() -> None:
    """小租户样本少，指标抖动大——只告警不阻断，避免误伤发布。"""
    decision = evaluate_gate([rule("x", 0.9, min_samples=30)], {"x": 0.1}, sample_size=5)
    assert decision.passed
    assert decision.results[0].skipped
    assert "样本数 5 < 30" in (decision.results[0].reason or "")

    # 样本足够时正常阻断
    assert not evaluate_gate(
        [rule("x", 0.9, min_samples=30)], {"x": 0.1}, sample_size=100
    ).passed


def test_deterministic_requirement_rejects_probabilistic_evaluator() -> None:
    """高风险门禁不允许只靠 LLM 打分（需求说明 §16.7）。"""
    decision = evaluate_gate(
        [rule("safety", 1.0, required_determinism=Determinism.DETERMINISTIC)],
        {"safety": 1.0},
        evaluator_determinism={"safety": Determinism.PROBABILISTIC},
    )
    assert not decision.passed
    assert "确定性评估器" in (decision.results[0].reason or "")


def test_deterministic_requirement_accepts_deterministic_evaluator() -> None:
    decision = evaluate_gate(
        [rule("safety", 1.0, required_determinism=Determinism.DETERMINISTIC)],
        {"safety": 1.0},
        evaluator_determinism={"safety": Determinism.DETERMINISTIC},
    )
    assert decision.passed


def test_decision_is_deterministic() -> None:
    """同样输入必须得到同样判定——否则门禁结果无法复现。"""
    gates = [rule("a", 0.5), rule("b", 0.5, comparison="lte")]
    metrics = {"a": 0.6, "b": 0.4}
    first = evaluate_gate(gates, metrics)
    second = evaluate_gate(gates, metrics)
    assert first.passed == second.passed
    assert first.blocked_reasons == second.blocked_reasons
    assert [(r.rule, r.passed, r.actual) for r in first.results] == [
        (r.rule, r.passed, r.actual) for r in second.results
    ]


def test_blocked_reasons_are_human_readable() -> None:
    decision = evaluate_gate([rule("task_success_rate", 0.9)], {"task_success_rate": 0.5})
    assert decision.blocked_reasons == (
        "task_success_rate: 实际 0.5 score ≥ 门槛 0.9",
    )

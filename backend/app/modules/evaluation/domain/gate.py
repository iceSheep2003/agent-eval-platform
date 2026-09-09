"""门禁判定。

**纯函数**：无 IO、无时间、无随机。同样的输入永远得到同样的判定——
这是「门禁是硬约束、权限无法绕过」的代码基础（需求说明 §9.9）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from ....contracts.common import Determinism, GateAction, GateScope
from .models import GateRule


@dataclass(frozen=True, slots=True)
class GateRuleResult:
    rule: str
    metric_key: str
    actual: float | None
    threshold: float
    unit: str
    comparison: str
    passed: bool
    action: GateAction
    scope: GateScope
    tenant_id: str | None = None
    sample_size: int | None = None
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    results: tuple[GateRuleResult, ...]
    blocked_reasons: tuple[str, ...]
    evaluated_at: datetime | None = None

    @property
    def blocked_rules(self) -> tuple[str, ...]:
        return tuple(
            item.rule
            for item in self.results
            if not item.passed and not item.skipped and item.action is GateAction.BLOCK
        )


def evaluate_gate(
    gates: Sequence[GateRule],
    metrics: Mapping[str, float],
    *,
    evaluator_determinism: Mapping[str, Determinism] | None = None,
    sample_size: int | None = None,
    tenant_id: str | None = None,
    now: datetime | None = None,
) -> GateDecision:
    """按门禁规则判定一批指标。

    - 指标缺失 → `skipped`，**不阻断**（缺数据不等于不达标，但会出现在结果里供排查）
    - `min_samples` 保护：样本不足时只告警不阻断，避免小样本抖动误伤发布
    - `required_determinism=deterministic` 且评估器是概率性的 → 该规则不成立，阻断
    """
    results: list[GateRuleResult] = []
    for gate in gates:
        actual = metrics.get(gate.metric_key)

        if actual is None:
            results.append(
                _result(gate, None, passed=True, skipped=True, reason="指标缺失", tenant_id=tenant_id, sample_size=sample_size)
            )
            continue

        if gate.min_samples and sample_size is not None and sample_size < gate.min_samples:
            results.append(
                _result(
                    gate, actual, passed=True, skipped=True,
                    reason=f"样本数 {sample_size} < {gate.min_samples}，仅告警",
                    tenant_id=tenant_id, sample_size=sample_size,
                )
            )
            continue

        if gate.required_determinism is Determinism.DETERMINISTIC:
            actual_determinism = (evaluator_determinism or {}).get(gate.metric_key)
            if actual_determinism is Determinism.PROBABILISTIC:
                results.append(
                    _result(
                        gate, actual, passed=False,
                        reason="该门禁要求确定性评估器，当前指标来自概率性评估器",
                        tenant_id=tenant_id, sample_size=sample_size,
                    )
                )
                continue

        passed = actual >= gate.threshold if gate.comparison == "gte" else actual <= gate.threshold
        results.append(
            _result(gate, actual, passed=passed, tenant_id=tenant_id, sample_size=sample_size)
        )

    blocked = tuple(
        item.rule
        for item in results
        if not item.passed and not item.skipped and item.action is GateAction.BLOCK
    )
    return GateDecision(
        passed=not blocked,
        results=tuple(results),
        blocked_reasons=tuple(
            f"{item.rule}: 实际 {item.actual} {item.unit} "
            f"{'≥' if item.comparison == 'gte' else '≤'} 门槛 {item.threshold}"
            for item in results
            if not item.passed and not item.skipped and item.action is GateAction.BLOCK
        ),
        evaluated_at=now,
    )


def _result(
    gate: GateRule,
    actual: float | None,
    *,
    passed: bool,
    skipped: bool = False,
    reason: str | None = None,
    tenant_id: str | None = None,
    sample_size: int | None = None,
) -> GateRuleResult:
    return GateRuleResult(
        rule=gate.name,
        metric_key=gate.metric_key,
        actual=actual,
        threshold=gate.threshold,
        unit=gate.unit,
        comparison=gate.comparison,
        passed=passed,
        action=gate.action,
        scope=gate.scope,
        tenant_id=tenant_id,
        sample_size=sample_size,
        skipped=skipped,
        reason=reason,
    )

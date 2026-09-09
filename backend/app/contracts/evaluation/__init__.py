"""评测策略快照契约。

定义方：消费方（execution 创建 Run 时冻结策略）。
实现方：evaluation。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Mapping, Protocol, Sequence, runtime_checkable

from ..common import Determinism, EvaluationStage, GateAction, GateScope, Id


@dataclass(frozen=True, slots=True)
class EvaluatorSpecRef:
    name: str
    version: str
    determinism: Determinism


@dataclass(frozen=True, slots=True)
class DimensionSpecRef:
    id: Id
    name: str
    weight: float
    threshold: float
    evaluator_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateRuleRef:
    name: str
    metric_key: str
    threshold: float
    unit: str
    comparison: Literal["gte", "lte"]
    scope: GateScope
    action: GateAction
    required_determinism: Determinism | None = None
    min_samples: int = 0


@dataclass(frozen=True, slots=True)
class TemplateSnapshot:
    """Run 创建时冻结。之后策略怎么改都不影响历史 Run（需求说明 §9.7）。"""

    template_id: Id | None
    template_name: str
    stage: EvaluationStage
    dataset_version_id: Id | None
    evaluators: tuple[EvaluatorSpecRef, ...] = ()
    dimensions: tuple[DimensionSpecRef, ...] = ()
    gates: tuple[GateRuleRef, ...] = ()
    snapshot_source: Literal["explicit", "derived_from_binding", "ad_hoc"] = "explicit"
    frozen_at: datetime | None = None


@runtime_checkable
class TemplateSnapshotPort(Protocol):
    """由 evaluation 实现；execution 创建 Run 时取快照。"""

    async def snapshot(
        self, template_id: Id, workspace_id: Id
    ) -> TemplateSnapshot | None: ...


__all__ = [
    "DimensionSpecRef",
    "GateDecisionRef",
    "GateEvaluatorPort",
    "GateRuleResultRef",
    "EvaluatorSpecRef",
    "GateRuleRef",
    "TemplateSnapshot",
    "TemplateSnapshotPort",
]


@dataclass(frozen=True, slots=True)
class GateRuleResultRef:
    rule: str
    metric_key: str
    actual: float | None
    threshold: float
    unit: str
    comparison: str
    passed: bool
    action: GateAction
    scope: GateScope
    tenant_id: Id | None = None
    sample_size: int | None = None
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GateDecisionRef:
    passed: bool
    results: tuple[GateRuleResultRef, ...] = ()
    blocked_rules: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()


@runtime_checkable
class GateEvaluatorPort(Protocol):
    """门禁判定。

    实现是纯函数（`evaluation/domain/gate.py`），但**必须经契约调用**——
    execution 直接 import evaluation 的领域代码会破坏模块边界。
    """

    def evaluate_gates(
        self,
        gates: Sequence[GateRuleRef],
        metrics: Mapping[str, float],
        *,
        evaluator_determinism: Mapping[str, Determinism] | None = None,
        sample_size: int | None = None,
    ) -> GateDecisionRef: ...

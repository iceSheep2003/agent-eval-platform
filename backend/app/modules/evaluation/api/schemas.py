"""evaluation 的 HTTP DTO。

`lifecycle` 是给前端 `EvalPolicy.lifecycle` 的兼容别名——它其实是**评测阶段**
（development / regression / release / production），不是部署通道。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ....contracts.common import EvaluationStage


class CreatePolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    stage: EvaluationStage
    trigger_type: Literal["manual", "release", "schedule", "incident"] = "manual"
    dataset_version_id: str | None = None
    evaluators: list[str] | None = None
    dimension_ids: list[str] = Field(default_factory=list)
    #: 前端策略页传 `{指标名: 0–1 阈值}`
    gates: dict[str, float] | None = None
    enabled: bool = True


class UpdatePolicyRequest(BaseModel):
    stage: EvaluationStage | None = None
    trigger_type: Literal["manual", "release", "schedule", "incident"] | None = None
    dataset_version_id: str | None = None
    evaluators: list[str] | None = None
    dimension_ids: list[str] | None = None
    gates: dict[str, float] | None = None
    enabled: bool | None = None


class BindRequest(BaseModel):
    asset_id: str


class PreviewGateRequest(BaseModel):
    metrics: dict[str, float]
    sample_size: int | None = None


class DimensionDTO(BaseModel):
    id: str
    name: str
    score: float | None
    threshold: float
    weight: float
    evaluators: list[str] = []


class CapabilityDTO(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    dimensions: list[DimensionDTO] = []


class EvaluatorDTO(BaseModel):
    name: str
    version: str
    determinism: str
    description: str


class PolicyDTO(BaseModel):
    id: str
    name: str
    lifecycle: str  # = stage，兼容前端
    stage: str
    trigger_type: str
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    evaluators: list[str] = []
    dimension_ids: list[str] = []
    gates: dict[str, float] = {}
    enabled: bool
    binding_count: int = 0


class GateRuleResultDTO(BaseModel):
    rule: str
    metric_key: str
    actual: float | None
    threshold: float
    unit: str
    passed: bool
    action: str
    scope: str
    skipped: bool
    reason: str | None = None


class GateDecisionDTO(BaseModel):
    passed: bool
    blocked_rules: list[str] = []
    blocked_reasons: list[str] = []
    results: list[GateRuleResultDTO] = []


def gate_decision_dto(decision: Any) -> GateDecisionDTO:
    return GateDecisionDTO(
        passed=decision.passed,
        blocked_rules=list(decision.blocked_rules),
        blocked_reasons=list(decision.blocked_reasons),
        results=[
            GateRuleResultDTO(
                rule=item.rule,
                metric_key=item.metric_key,
                actual=item.actual,
                threshold=item.threshold,
                unit=item.unit,
                passed=item.passed,
                action=item.action.value,
                scope=item.scope.value,
                skipped=item.skipped,
                reason=item.reason,
            )
            for item in decision.results
        ],
    )

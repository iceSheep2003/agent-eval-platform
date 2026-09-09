"""评测配置领域实体。

三个概念必须严格区分（需求说明 §5.8）：

    Capability（能力，业务大类）        "工具使用"
      └── ScoreDimension（评分维度）     "工具正确率"   weight / threshold
            └── Evaluator（评估器）      "ToolNameCorrectness@1.0.0"  实现方法
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

from ....contracts.common import (
    Determinism,
    EvaluationStage,
    GateAction,
    GateScope,
    Id,
    JsonValue,
)

TriggerType = Literal["manual", "release", "schedule", "incident"]


@dataclass(frozen=True, slots=True)
class Capability:
    id: Id
    workspace_id: Id
    name: str
    description: str
    enabled: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ScoreDimension:
    """评分维度。`score` 是当前观测值，`threshold` 是期望门槛，两者都是 0–1。"""

    id: Id
    capability_id: Id
    workspace_id: Id
    name: str
    weight: float
    threshold: float
    evaluator_names: tuple[str, ...]
    score: float | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluatorSpec:
    """评估器目录项。实现不在这个模块——这里只登记「有哪些、什么性质」。"""

    name: str
    version: str
    determinism: Determinism
    description: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GateRule:
    """硬门禁。`required_determinism=deterministic` 时只接受确定性评估器的结果。"""

    name: str  # 指标 key，如 task_success_rate
    metric_key: str
    threshold: float
    unit: Literal["score", "percent", "ms"]
    comparison: Literal["gte", "lte"]
    scope: GateScope
    action: GateAction
    required_determinism: Determinism | None = None
    min_samples: int = 0


@dataclass(frozen=True, slots=True)
class EvaluationTemplate:
    """评测策略：在什么时机、用什么样本和方法、按什么门槛判断质量。"""

    id: Id
    workspace_id: Id
    name: str
    stage: EvaluationStage
    trigger_type: TriggerType
    dataset_id: Id | None
    dataset_version_id: Id | None
    evaluators: tuple[EvaluatorSpec, ...]
    dimension_ids: tuple[Id, ...]
    gates: tuple[GateRule, ...]
    enabled: bool
    created_by: Id
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TemplateBinding:
    template_id: Id
    asset_id: Id
    workspace_id: Id
    created_at: datetime


def gate_from_dict(raw: Mapping[str, Any]) -> GateRule:
    """从前端 `EvalPolicy.gates`（`{指标名: 0–1 阈值}`）或完整对象构造。"""
    if isinstance(raw.get("metric_key"), str):
        return GateRule(
            name=str(raw.get("name") or raw["metric_key"]),
            metric_key=str(raw["metric_key"]),
            threshold=float(raw["threshold"]),
            unit=raw.get("unit", "score"),  # type: ignore[arg-type]
            comparison=raw.get("comparison", "gte"),  # type: ignore[arg-type]
            scope=GateScope(raw.get("scope", GateScope.WORKSPACE)),
            action=GateAction(raw.get("action", GateAction.BLOCK)),
            required_determinism=(
                Determinism(raw["required_determinism"])
                if raw.get("required_determinism")
                else None
            ),
            min_samples=int(raw.get("min_samples") or 0),
        )
    raise ValueError(f"门禁规则缺少 metric_key: {raw!r}")


def gates_from_mapping(gates: Mapping[str, float]) -> tuple[GateRule, ...]:
    """兼容前端策略页的 `gates: Record<string, number>` 形状。"""
    return tuple(
        GateRule(
            name=key,
            metric_key=key,
            threshold=float(value),
            unit="score",
            comparison="gte",
            scope=GateScope.WORKSPACE,
            action=GateAction.BLOCK,
        )
        for key, value in gates.items()
    )


def gates_as_mapping(gates: tuple[GateRule, ...]) -> dict[str, JsonValue]:
    return {gate.metric_key: gate.threshold for gate in gates}

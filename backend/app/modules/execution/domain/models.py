"""执行领域实体。

Run 冻结三件套（被测版本 + 数据集版本 + 策略快照）后不可改；
终态后拒绝任何写入（需求说明 §9.7）。

`execution_status` 与 `verdict` 是**正交**的两列（需求说明 §16.8）：
「跑完了但没达标」≠「没跑起来」，统计口径必须分开。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Mapping

from ....contracts.common import (
    ExecutionStatus,
    Id,
    JsonValue,
    RunStage,
    RunStatus,
    Verdict,
)

SubjectKind = Literal["agent", "skill", "mcp", "knowledge_base"]


@dataclass(frozen=True, slots=True)
class Run:
    id: Id
    workspace_id: Id
    name: str
    subject_kind: SubjectKind
    subject_asset_id: Id
    subject_version_id: Id
    dataset_version_id: Id
    #: 冻结的策略快照（序列化后存库），历史 Run 不受策略改动影响
    template_snapshot: Mapping[str, Any]
    tenant_scope: Literal["all"] | tuple[Id, ...]
    status: RunStatus
    stage: RunStage
    concurrency: int
    cost_budget_usd: Decimal
    total_trials: int
    created_by: Id
    created_at: datetime
    ended_at: datetime | None = None
    #: 冻结的引用快照：`provider_asset_id → provider_version_id`。
    #: 「跟随通道」的引用在 CreateRun 时解析一次并冻结，之后资源晋级不影响这个 Run。
    binding_snapshot: Mapping[Id, Id] = field(default_factory=dict)
    #: 仅本次 Run 生效的引用覆盖（A/B 对比用）。已并入 `binding_snapshot`，这里留档。
    binding_overrides: Mapping[Id, Id] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class Trial:
    id: Id
    run_id: Id
    workspace_id: Id
    sample_id: Id
    tenant_id: Id | None
    attempt_no: int
    execution_status: ExecutionStatus
    verdict: Verdict | None
    instruction: str
    output: JsonValue | None = None
    error: str | None = None
    trace_id: Id | None = None
    duration_ms: int | None = None
    cost_usd: Decimal = Decimal("0")
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def is_finished(self) -> bool:
        return self.execution_status in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    """Run 进入终态时固化的聚合结果。之后只读。"""

    run_id: Id
    trial_counts: Mapping[str, int]
    verdict_counts: Mapping[str, int]
    pass_rate: float
    avg_score: float
    total_cost_usd: Decimal
    total_duration_ms: int
    dimension_scores: Mapping[str, float]
    gate_decision: Mapping[str, Any] | None
    finalized_at: datetime


@dataclass(frozen=True, slots=True)
class ScoreRecord:
    id: Id
    trial_id: Id
    run_id: Id
    workspace_id: Id
    tenant_id: Id | None
    metric: str
    metric_version: str
    value: float | int | bool | str | None
    status: str
    reason: str | None
    duration_ms: float | None
    created_at: datetime


def summarize(trials: list[Trial], scores: list[ScoreRecord]) -> dict[str, Any]:
    """按 `execution_status` / `verdict` 分别统计——不合并成一个「失败」。"""
    execution: dict[str, int] = {}
    verdicts: dict[str, int] = {}
    for trial in trials:
        execution[trial.execution_status.value] = execution.get(trial.execution_status.value, 0) + 1
        if trial.verdict is not None:
            verdicts[trial.verdict.value] = verdicts.get(trial.verdict.value, 0) + 1

    scored = [item for item in scores if item.status in {"pass", "fail"}]
    passed = sum(1 for item in scored if item.status == "pass")
    pass_rate = (passed / len(scored)) if scored else 0.0
    numeric = [float(item.value) for item in scores if isinstance(item.value, (int, float))]
    avg_score = (sum(numeric) / len(numeric)) if numeric else 0.0

    return {
        "trial_counts": execution,
        "verdict_counts": verdicts,
        "pass_rate": pass_rate,
        "avg_score": avg_score,
    }


__all__ = ["Run", "RunResult", "ScoreRecord", "Trial", "summarize"]

"""execution 的 HTTP DTO。字段名对齐前端 `EvalRun` / `EvalRunDetail`。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..domain.models import Run, RunResult, ScoreRecord, Trial


class InvokeRequest(BaseModel):
    """`POST /v1/agents/{id}/invoke`。`channel` 决定打哪个版本，不给版本号。"""

    input: str = Field(min_length=1)
    channel: Literal["test", "livesh", "live"] = "live"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)


class CreateRunRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    asset_version_id: str
    dataset_version_id: str
    template_id: str
    concurrency: int = Field(default=1, ge=1, le=32)
    cost_budget_usd: float = Field(default=0.0, ge=0.0)
    tenant_scope: list[str] | None = None


class RunDTO(BaseModel):
    id: str
    name: str
    agent_name: str | None = None
    agent_version: str | None = None
    dataset_name: str | None = None
    status: str
    phase: str  # = stage，兼容前端
    progress: float = 0.0
    passed: int = 0
    total: int = 0
    score: float = 0.0
    cost: float = 0.0
    duration_seconds: float = 0.0
    updated_at: str


class TrialDTO(BaseModel):
    id: str
    status: str
    verdict: str | None = None
    score: float | None = None
    duration_ms: int | None = None
    output: Any | None = None
    error: str | None = None
    trace_id: str | None = None


class ScoreDTO(BaseModel):
    id: str
    dimension_id: str | None = None
    metric: str
    metric_version: str
    value: Any | None = None
    status: str
    reason: str | None = None


class RunSummaryDTO(BaseModel):
    run_id: str
    trial_counts: dict[str, int]
    verdict_counts: dict[str, int]
    pass_rate: float
    avg_score: float
    total_cost_usd: float
    total_duration_ms: int
    dimension_scores: dict[str, float]
    gate_decision: dict[str, Any] | None = None
    finalized_at: datetime


def run_dto(
    run: Run, *, passed: int = 0, score: float = 0.0, cost: float = 0.0, progress: float = 0.0
) -> RunDTO:
    duration = 0.0
    if run.ended_at is not None:
        duration = (run.ended_at - run.created_at).total_seconds()
    snapshot = run.template_snapshot
    return RunDTO(
        id=run.id,
        name=run.name,
        agent_name=snapshot.get("subject_name"),  # type: ignore[arg-type]
        agent_version=snapshot.get("subject_version"),  # type: ignore[arg-type]
        dataset_name=snapshot.get("dataset_name"),  # type: ignore[arg-type]
        status=run.status.value,
        phase=run.stage.value,
        progress=progress,
        passed=passed,
        total=run.total_trials,
        score=score,
        cost=cost,
        duration_seconds=duration,
        updated_at=run.created_at.isoformat(),
    )


def trial_dto(trial: Trial, score: float | None = None) -> TrialDTO:
    return TrialDTO(
        id=trial.id,
        status=trial.execution_status.value,
        verdict=trial.verdict.value if trial.verdict else None,
        score=score,
        duration_ms=trial.duration_ms,
        output=trial.output,
        error=trial.error,
        trace_id=trial.trace_id,
    )


def score_dto(score: ScoreRecord) -> ScoreDTO:
    return ScoreDTO(
        id=score.id,
        metric=score.metric,
        metric_version=score.metric_version,
        value=score.value,
        status=score.status,
        reason=score.reason,
    )


def summary_dto(result: RunResult) -> RunSummaryDTO:
    return RunSummaryDTO(
        run_id=result.run_id,
        trial_counts=dict(result.trial_counts),
        verdict_counts=dict(result.verdict_counts),
        pass_rate=result.pass_rate,
        avg_score=result.avg_score,
        total_cost_usd=float(result.total_cost_usd),
        total_duration_ms=result.total_duration_ms,
        dimension_scores=dict(result.dimension_scores),
        gate_decision=dict(result.gate_decision) if result.gate_decision else None,
        finalized_at=result.finalized_at,
    )

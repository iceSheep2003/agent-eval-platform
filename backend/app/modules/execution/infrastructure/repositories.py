"""execution 仓储。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import ExecutionStatus, RunStage, RunStatus, Verdict
from ....shared.clock import ensure_aware
from ..domain.models import Run, RunResult, ScoreRecord, Trial
from .tables import RunResultRow, RunRow, ScoreRow, TrialRow


def _run(row: RunRow) -> Run:
    scope = row.tenant_scope
    return Run(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        subject_kind=row.subject_kind,  # type: ignore[arg-type]
        subject_asset_id=row.subject_asset_id,
        subject_version_id=row.subject_version_id,
        dataset_version_id=row.dataset_version_id,
        template_snapshot=dict(row.template_snapshot or {}),
        tenant_scope="all" if scope == "all" else tuple(scope or ()),
        status=RunStatus(row.status),
        stage=RunStage(row.stage),
        concurrency=int(row.concurrency),
        cost_budget_usd=Decimal(str(row.cost_budget_usd or 0)),
        total_trials=int(row.total_trials),
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
        ended_at=ensure_aware(row.ended_at) if row.ended_at else None,
    )


def _trial(row: TrialRow) -> Trial:
    return Trial(
        id=row.id,
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        sample_id=row.sample_id,
        tenant_id=row.tenant_id,
        attempt_no=int(row.attempt_no),
        execution_status=ExecutionStatus(row.execution_status),
        verdict=Verdict(row.verdict) if row.verdict else None,
        instruction=row.instruction,
        output=row.output,
        error=row.error,
        trace_id=row.trace_id,
        duration_ms=row.duration_ms,
        cost_usd=Decimal(str(row.cost_usd or 0)),
        started_at=ensure_aware(row.started_at) if row.started_at else None,
        ended_at=ensure_aware(row.ended_at) if row.ended_at else None,
    )


def _score(row: ScoreRow) -> ScoreRecord:
    return ScoreRecord(
        id=row.id,
        trial_id=row.trial_id,
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        tenant_id=row.tenant_id,
        metric=row.metric,
        metric_version=row.metric_version,
        value=row.value,
        status=row.status,
        reason=row.reason,
        duration_ms=float(row.duration_ms) if row.duration_ms is not None else None,
        created_at=ensure_aware(row.created_at),
    )


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: str, workspace_id: str) -> Run | None:
        stmt = select(RunRow).where(
            RunRow.id == run_id, RunRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _run(row) if row else None

    async def list_for_workspace(
        self, workspace_id: str, *, status: RunStatus | None = None, limit: int = 50
    ) -> Sequence[Run]:
        stmt = select(RunRow).where(RunRow.workspace_id == workspace_id)
        if status is not None:
            stmt = stmt.where(RunRow.status == status.value)
        stmt = stmt.order_by(RunRow.created_at.desc()).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_run(row) for row in rows]

    def add(self, run: Run) -> None:
        self._session.add(
            RunRow(
                id=run.id,
                workspace_id=run.workspace_id,
                name=run.name,
                subject_kind=run.subject_kind,
                subject_asset_id=run.subject_asset_id,
                subject_version_id=run.subject_version_id,
                dataset_version_id=run.dataset_version_id,
                template_snapshot=dict(run.template_snapshot),
                tenant_scope="all" if run.tenant_scope == "all" else list(run.tenant_scope),
                status=run.status.value,
                stage=run.stage.value,
                concurrency=run.concurrency,
                cost_budget_usd=run.cost_budget_usd,
                total_trials=run.total_trials,
                created_by=run.created_by,
            )
        )

    async def set_state(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        stage: RunStage | None = None,
        total_trials: int | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if status is not None:
            values["status"] = status.value
        if stage is not None:
            values["stage"] = stage.value
        if total_trials is not None:
            values["total_trials"] = total_trials
        if ended_at is not None:
            values["ended_at"] = ended_at
        if not values:
            return
        await self._session.execute(
            update(RunRow).where(RunRow.id == run_id).values(**values)
        )


class TrialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, trial_id: str, workspace_id: str) -> Trial | None:
        stmt = select(TrialRow).where(
            TrialRow.id == trial_id, TrialRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _trial(row) if row else None

    async def find(self, run_id: str, sample_id: str, attempt_no: int) -> Trial | None:
        stmt = select(TrialRow).where(
            TrialRow.run_id == run_id,
            TrialRow.sample_id == sample_id,
            TrialRow.attempt_no == attempt_no,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _trial(row) if row else None

    async def list_for_run(self, run_id: str, *, limit: int = 500) -> Sequence[Trial]:
        stmt = (
            select(TrialRow)
            .where(TrialRow.run_id == run_id)
            .order_by(TrialRow.created_at)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_trial(row) for row in rows]

    async def count_for_run(self, run_id: str) -> int:
        stmt = select(func.count()).select_from(TrialRow).where(TrialRow.run_id == run_id)
        return int((await self._session.execute(stmt)).scalar_one())

    def add(self, trial: Trial) -> None:
        self._session.add(
            TrialRow(
                id=trial.id,
                run_id=trial.run_id,
                workspace_id=trial.workspace_id,
                sample_id=trial.sample_id,
                tenant_id=trial.tenant_id,
                attempt_no=trial.attempt_no,
                execution_status=trial.execution_status.value,
                verdict=trial.verdict.value if trial.verdict else None,
                instruction=trial.instruction,
                output=trial.output,
                error=trial.error,
                trace_id=trial.trace_id,
                duration_ms=trial.duration_ms,
                cost_usd=trial.cost_usd,
                started_at=trial.started_at,
                ended_at=trial.ended_at,
            )
        )

    async def set_outcome(
        self,
        trial_id: str,
        *,
        execution_status: ExecutionStatus,
        verdict: Verdict | None,
        output: Any | None,
        error: str | None,
        trace_id: str | None,
        duration_ms: int | None,
        cost_usd: Decimal,
        ended_at: datetime,
    ) -> None:
        await self._session.execute(
            update(TrialRow)
            .where(TrialRow.id == trial_id)
            .values(
                execution_status=execution_status.value,
                verdict=verdict.value if verdict else None,
                output=output,
                error=error,
                trace_id=trace_id,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                ended_at=ended_at,
            )
        )

    async def mark_running(self, trial_id: str, started_at: datetime) -> None:
        await self._session.execute(
            update(TrialRow)
            .where(TrialRow.id == trial_id)
            .values(execution_status=ExecutionStatus.RUNNING.value, started_at=started_at)
        )


class ScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_run(self, run_id: str) -> Sequence[ScoreRecord]:
        stmt = select(ScoreRow).where(ScoreRow.run_id == run_id).order_by(ScoreRow.created_at)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_score(row) for row in rows]

    async def list_for_trial(self, trial_id: str) -> Sequence[ScoreRecord]:
        stmt = select(ScoreRow).where(ScoreRow.trial_id == trial_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_score(row) for row in rows]

    def add(self, score: ScoreRecord) -> None:
        self._session.add(
            ScoreRow(
                id=score.id,
                trial_id=score.trial_id,
                run_id=score.run_id,
                workspace_id=score.workspace_id,
                tenant_id=score.tenant_id,
                metric=score.metric,
                metric_version=score.metric_version,
                value=score.value,
                status=score.status,
                reason=score.reason,
                duration_ms=score.duration_ms,
            )
        )


class RunResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: str) -> RunResult | None:
        row = await self._session.get(RunResultRow, run_id)
        if row is None:
            return None
        payload: Mapping[str, Any] = dict(row.payload or {})
        return RunResult(
            run_id=row.run_id,
            trial_counts=dict(payload.get("trial_counts") or {}),
            verdict_counts=dict(payload.get("verdict_counts") or {}),
            pass_rate=float(payload.get("pass_rate") or 0),
            avg_score=float(payload.get("avg_score") or 0),
            total_cost_usd=Decimal(str(payload.get("total_cost_usd") or 0)),
            total_duration_ms=int(payload.get("total_duration_ms") or 0),
            dimension_scores=dict(payload.get("dimension_scores") or {}),
            gate_decision=payload.get("gate_decision"),
            finalized_at=ensure_aware(row.finalized_at),
        )

    def add(self, result: RunResult) -> None:
        self._session.add(
            RunResultRow(
                run_id=result.run_id,
                workspace_id="",  # 由调用方在 payload 之外维护；此处仅占位
                payload={
                    "trial_counts": dict(result.trial_counts),
                    "verdict_counts": dict(result.verdict_counts),
                    "pass_rate": result.pass_rate,
                    "avg_score": result.avg_score,
                    "total_cost_usd": str(result.total_cost_usd),
                    "total_duration_ms": result.total_duration_ms,
                    "dimension_scores": dict(result.dimension_scores),
                    "gate_decision": result.gate_decision,
                },
                finalized_at=result.finalized_at,
            )
        )

"""execution 用例：创建 Run、推进 Trial、固化结果。

流程全部由命令驱动（`run.prepare` → `trial.execute` × N → `run.finalize`），
每个 handler 都必须**幂等**——队列是 at-least-once 投递。

**`expected_output` 只用于评分，绝不进 Runtime 的 payload。**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from ....contracts.asset import AssetQueryPort
from ....contracts.common import (
    Determinism,
    EvaluationStage,
    ExecutionStatus,
    GateAction,
    GateScope,
    Id,
    RunStage,
    RunStatus,
    Verdict,
)
from ....contracts.dataset import SampleReaderPort, SampleRef
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.evaluation import (
    GateEvaluatorPort,
    TemplateSnapshot,
    TemplateSnapshotPort,
)
from ....persistence import Command, UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.models import Run, RunResult, ScoreRecord, Trial, summarize
from ..infrastructure.evaluators import MetricOutcome, aggregate_verdict, evaluate_metric
from ..infrastructure.repositories import (
    RunRepository,
    RunResultRepository,
    ScoreRepository,
    TrialRepository,
)
from .ports import RunContext, RuntimePort, RuntimeSpec

RUN_PREPARE = "run.prepare"
TRIAL_EXECUTE = "trial.execute"
RUN_FINALIZE = "run.finalize"

DEFAULT_TIMEOUT_SECONDS = 60.0


# --------------------------------------------------------------------------- #
# 快照序列化
# --------------------------------------------------------------------------- #


def snapshot_to_dict(snapshot: TemplateSnapshot) -> dict[str, Any]:
    return {
        "template_id": snapshot.template_id,
        "template_name": snapshot.template_name,
        "stage": snapshot.stage.value,
        "dataset_version_id": snapshot.dataset_version_id,
        "snapshot_source": snapshot.snapshot_source,
        "evaluators": [
            {"name": item.name, "version": item.version, "determinism": item.determinism.value}
            for item in snapshot.evaluators
        ],
        "dimensions": [
            {
                "id": item.id,
                "name": item.name,
                "weight": item.weight,
                "threshold": item.threshold,
                "evaluator_names": list(item.evaluator_names),
            }
            for item in snapshot.dimensions
        ],
        "gates": [
            {
                "name": item.name,
                "metric_key": item.metric_key,
                "threshold": item.threshold,
                "unit": item.unit,
                "comparison": item.comparison,
                "scope": item.scope.value,
                "action": item.action.value,
                "required_determinism": (
                    item.required_determinism.value if item.required_determinism else None
                ),
                "min_samples": item.min_samples,
            }
            for item in snapshot.gates
        ],
    }


def snapshot_from_dict(raw: Mapping[str, Any]) -> TemplateSnapshot:
    from ....contracts.evaluation import DimensionSpecRef, EvaluatorSpecRef, GateRuleRef

    return TemplateSnapshot(
        template_id=raw.get("template_id"),
        template_name=str(raw.get("template_name") or ""),
        stage=EvaluationStage(raw.get("stage") or EvaluationStage.RELEASE),
        dataset_version_id=raw.get("dataset_version_id"),
        snapshot_source=raw.get("snapshot_source") or "explicit",  # type: ignore[arg-type]
        evaluators=tuple(
            EvaluatorSpecRef(
                name=item["name"],
                version=str(item.get("version") or "1.0.0"),
                determinism=Determinism(item.get("determinism") or Determinism.DETERMINISTIC),
            )
            for item in (raw.get("evaluators") or ())
        ),
        dimensions=tuple(
            DimensionSpecRef(
                id=item["id"],
                name=item["name"],
                weight=float(item["weight"]),
                threshold=float(item["threshold"]),
                evaluator_names=tuple(item.get("evaluator_names") or ()),
            )
            for item in (raw.get("dimensions") or ())
        ),
        gates=tuple(
            GateRuleRef(
                name=item["name"],
                metric_key=item["metric_key"],
                threshold=float(item["threshold"]),
                unit=item.get("unit") or "score",
                comparison=item.get("comparison") or "gte",
                scope=GateScope(item.get("scope") or GateScope.WORKSPACE),
                action=GateAction(item.get("action") or GateAction.BLOCK),
                required_determinism=(
                    Determinism(item["required_determinism"])
                    if item.get("required_determinism")
                    else None
                ),
                min_samples=int(item.get("min_samples") or 0),
            )
            for item in (raw.get("gates") or ())
        ),
    )


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #


class RunService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        assets: AssetQueryPort,
        datasets: SampleReaderPort,
        templates: TemplateSnapshotPort,
        gates: GateEvaluatorPort,
        runtime: RuntimePort,
    ) -> None:
        self._db = database
        self._clock = clock
        self.assets = assets
        self.datasets = datasets
        self._templates = templates
        self._gates = gates
        self.runtime = runtime

    async def create_run(
        self,
        *,
        workspace_id: Id,
        created_by: Id,
        name: str,
        asset_version_id: Id,
        dataset_version_id: Id,
        template_id: Id,
        concurrency: int = 1,
        cost_budget_usd: float = 0.0,
        tenant_scope: Sequence[Id] | None = None,
    ) -> Run:
        """冻结三件套：被测版本 + 数据集版本 + 策略快照。之后不可改。"""
        version = await self.assets.get_version_ref(asset_version_id, workspace_id)
        if version is None:
            raise NotFound("被测版本", asset_version_id)
        dataset = await self.datasets.get_version_ref(dataset_version_id, workspace_id)
        if dataset is None:
            raise NotFound("数据集版本", dataset_version_id)
        if not dataset.finalized:
            raise DomainError(
                Errors.RUN_SUBJECT_INCOMPLETE,
                f"数据集版本 {dataset.version_label} 尚未固化，不能用于评测",
            )
        snapshot = await self._templates.snapshot(template_id, workspace_id)
        if snapshot is None:
            raise NotFound("评测策略", template_id)

        sample_count = await self.datasets.count(dataset_version_id)
        if sample_count == 0:
            raise DomainError(Errors.RUN_SUBJECT_INCOMPLETE, "数据集版本里没有样本")

        run = Run(
            id=new_id("run"),
            workspace_id=workspace_id,
            name=name,
            subject_kind="agent",
            subject_asset_id=version.asset_id,
            subject_version_id=version.id,
            dataset_version_id=dataset_version_id,
            template_snapshot=snapshot_to_dict(snapshot),
            tenant_scope=tuple(tenant_scope) if tenant_scope else "all",
            status=RunStatus.QUEUED,
            stage=RunStage.PROVISIONING,
            concurrency=max(1, concurrency),
            cost_budget_usd=Decimal(str(cost_budget_usd)),
            total_trials=sample_count,
            created_by=created_by,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            RunRepository(uow.session).add(run)
            uow.enqueue(
                Command(
                    id=new_id("command"),
                    workspace_id=workspace_id,
                    command_type=RUN_PREPARE,
                    aggregate_type="run",
                    aggregate_id=run.id,
                    idempotency_key=f"{RUN_PREPARE}:{run.id}",
                    payload={"run_id": run.id, "workspace_id": workspace_id},
                    not_before=self._clock.now(),
                )
            )
            await uow.commit()
        return run

    async def list_runs(
        self, workspace_id: Id, status: RunStatus | None = None
    ) -> Sequence[Run]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await RunRepository(uow.session).list_for_workspace(workspace_id, status=status)
            )

    async def get_run(self, run_id: Id, workspace_id: Id) -> Run:
        async with UnitOfWork(self._db) as uow:
            run = await RunRepository(uow.session).get(run_id, workspace_id)
        if run is None:
            raise NotFound("运行", run_id)
        return run

    async def list_trials(self, run_id: Id, workspace_id: Id) -> Sequence[Trial]:
        await self.get_run(run_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await TrialRepository(uow.session).list_for_run(run_id))

    async def get_trial(self, trial_id: Id, workspace_id: Id) -> Trial:
        async with UnitOfWork(self._db) as uow:
            trial = await TrialRepository(uow.session).get(trial_id, workspace_id)
        if trial is None:
            raise NotFound("Trial", trial_id)
        return trial

    async def list_scores(self, run_id: Id, workspace_id: Id) -> Sequence[ScoreRecord]:
        await self.get_run(run_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await ScoreRepository(uow.session).list_for_run(run_id))

    async def get_result(self, run_id: Id, workspace_id: Id) -> RunResult | None:
        await self.get_run(run_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return await RunResultRepository(uow.session).get(run_id)

    async def control(self, run_id: Id, workspace_id: Id, action: str) -> Run:
        """暂停/恢复是协作式安全点：不再派发新 Trial，在途的跑完。"""
        run = await self.get_run(run_id, workspace_id)
        if run.is_terminal:
            raise DomainError(Errors.RUN_FINALIZED, f"运行 {run_id} 已结束")
        transitions = {
            "pause": (RunStatus.RUNNING, RunStatus.PAUSED),
            "resume": (RunStatus.PAUSED, RunStatus.RUNNING),
            "cancel": (None, RunStatus.CANCELLED),
        }
        if action not in transitions:
            raise DomainError(Errors.RUN_STATE_CONFLICT, f"未知操作 {action}")
        required, target = transitions[action]
        if required is not None and run.status is not required:
            raise DomainError(
                Errors.RUN_STATE_CONFLICT, f"当前状态 {run.status.value} 不能执行 {action}"
            )
        ended_at = self._clock.now() if target is RunStatus.CANCELLED else None
        async with UnitOfWork(self._db) as uow:
            await RunRepository(uow.session).set_state(
                run_id, status=target, ended_at=ended_at
            )
            await uow.commit()
        return await self.get_run(run_id, workspace_id)


# --------------------------------------------------------------------------- #
# 命令处理
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ExecutionHandlers:
    """命令处理器。Worker 按 `command_type` 分派到这里。"""

    database: Database
    clock: Clock
    assets: AssetQueryPort
    datasets: SampleReaderPort
    gates: GateEvaluatorPort
    runtime: RuntimePort

    @property
    def command_types(self) -> tuple[str, ...]:
        return (RUN_PREPARE, TRIAL_EXECUTE, RUN_FINALIZE)

    async def handle(self, command: Command, uow: UnitOfWork) -> None:
        if command.command_type == RUN_PREPARE:
            await self._prepare(command, uow)
        elif command.command_type == TRIAL_EXECUTE:
            await self._execute_trial(command, uow)
        elif command.command_type == RUN_FINALIZE:
            await self._finalize(command, uow)
        else:
            raise ValueError(f"未处理的命令类型 {command.command_type}")

    # -- run.prepare ---------------------------------------------------------

    async def _prepare(self, command: Command, uow: UnitOfWork) -> None:
        run_id = command.payload["run_id"]
        workspace_id = command.payload["workspace_id"]
        runs = RunRepository(uow.session)
        run = await runs.get(run_id, workspace_id)
        if run is None or run.is_terminal:
            return
        trials = TrialRepository(uow.session)
        if await trials.count_for_run(run_id) > 0:
            return  # 幂等：已经展开过

        samples = await self.datasets.read_page(run.dataset_version_id, limit=10_000)
        if not samples:
            await runs.set_state(run_id, status=RunStatus.FAILED, stage=RunStage.COMPLETED)
            return

        for sample in samples:
            trial = Trial(
                id=new_id("trial"),
                run_id=run_id,
                workspace_id=workspace_id,
                sample_id=sample.id,
                tenant_id=sample.tenant_id,
                attempt_no=1,
                execution_status=ExecutionStatus.PENDING,
                verdict=None,
                instruction=sample.instruction,
            )
            trials.add(trial)
            uow.enqueue(
                Command(
                    id=new_id("command"),
                    workspace_id=workspace_id,
                    command_type=TRIAL_EXECUTE,
                    aggregate_type="trial",
                    aggregate_id=trial.id,
                    idempotency_key=f"{TRIAL_EXECUTE}:{trial.id}",
                    payload={
                        "run_id": run_id,
                        "trial_id": trial.id,
                        "workspace_id": workspace_id,
                    },
                    not_before=self.clock.now(),
                )
            )
        await runs.set_state(
            run_id,
            status=RunStatus.RUNNING,
            stage=RunStage.EXECUTING,
            total_trials=len(samples),
        )

    # -- trial.execute -------------------------------------------------------

    async def _execute_trial(self, command: Command, uow: UnitOfWork) -> None:
        run_id = command.payload["run_id"]
        trial_id = command.payload["trial_id"]
        workspace_id = command.payload["workspace_id"]

        trials = TrialRepository(uow.session)
        trial = await trials.get(trial_id, workspace_id)
        runs = RunRepository(uow.session)
        run = await runs.get(run_id, workspace_id)
        if trial is None or run is None or trial.is_finished:
            return  # 幂等
        if run.status in {RunStatus.PAUSED, RunStatus.CANCELLED}:
            return  # 暂停/停止时不再执行新 Trial

        await trials.mark_running(trial_id, self.clock.now())

        version = await self.assets.get_version_ref(run.subject_version_id, workspace_id)
        if version is None or not version.entrypoint:
            await trials.set_outcome(
                trial_id,
                execution_status=ExecutionStatus.FAILED,
                verdict=None,
                output=None,
                error="被测版本没有 entrypoint，无法执行",
                trace_id=None,
                duration_ms=0,
                cost_usd=Decimal("0"),
                ended_at=self.clock.now(),
            )
            await self._maybe_finalize(run_id, workspace_id, uow)
            return

        sample = await self.datasets.get_sample(trial.sample_id)
        snapshot = snapshot_from_dict(run.template_snapshot)

        # **payload 只含公开输入**：expected_output 不在这里。
        payload: dict[str, Any] = {
            "__entrypoint__": version.entrypoint,
            "input": trial.instruction,
        }
        ctx = RunContext(
            run_id=run_id,
            trial_id=trial_id,
            workspace_id=workspace_id,
            tenant_id=trial.tenant_id,
            sample_id=trial.sample_id,
            attempt_no=trial.attempt_no,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            cost_budget_usd=float(run.cost_budget_usd),
        )
        handle = await self.runtime.provision(
            RuntimeSpec(
                asset_id=version.asset_id,
                asset_version_id=version.id,
                workspace_id=workspace_id,
                entrypoint=version.entrypoint,
                spec=version.spec,
            ),
            ctx,
        )
        try:
            result = await self.runtime.invoke(handle, payload, ctx)
        finally:
            await self.runtime.teardown(handle)

        expected = sample.expected_output if sample else None
        outcomes = [
            evaluate_metric(
                spec.name,
                expected=expected,
                output=result.output,
                execution_error=result.error,
            )
            for spec in snapshot.evaluators
        ]
        for outcome in outcomes:
            uow.session.add(
                self._score_row(outcome, trial, run)
            )

        execution_status = (
            ExecutionStatus.SUCCEEDED if result.error is None else ExecutionStatus.FAILED
        )
        verdict = aggregate_verdict(outcomes) if execution_status is ExecutionStatus.SUCCEEDED else None
        await trials.set_outcome(
            trial_id,
            execution_status=execution_status,
            verdict=Verdict(verdict) if verdict else None,
            output=result.output,
            error=result.error,
            trace_id=result.trace_id,
            duration_ms=result.duration_ms,
            cost_usd=Decimal(str(result.cost_usd)),
            ended_at=self.clock.now(),
        )
        await uow.session.flush()
        await self._maybe_finalize(run_id, workspace_id, uow)

    def _score_row(self, outcome: MetricOutcome, trial: Trial, run: Run) -> Any:
        from ..infrastructure.tables import ScoreRow

        return ScoreRow(
            id=new_id("score"),
            trial_id=trial.id,
            run_id=run.id,
            workspace_id=run.workspace_id,
            tenant_id=trial.tenant_id,
            metric=outcome.metric,
            metric_version=outcome.metric_version,
            value=outcome.value,
            status=outcome.status,
            reason=outcome.reason,
            duration_ms=None,
        )

    async def _maybe_finalize(self, run_id: str, workspace_id: str, uow: UnitOfWork) -> None:
        """全部 Trial 处理完才入队 finalize——避免重复触发。"""
        trials = TrialRepository(uow.session)
        all_trials = list(await trials.list_for_run(run_id))
        if not all_trials or any(not item.is_finished for item in all_trials):
            return
        uow.enqueue(
            Command(
                id=new_id("command"),
                workspace_id=workspace_id,
                command_type=RUN_FINALIZE,
                aggregate_type="run",
                aggregate_id=run_id,
                idempotency_key=f"{RUN_FINALIZE}:{run_id}",
                payload={"run_id": run_id, "workspace_id": workspace_id},
                not_before=self.clock.now(),
            )
        )

    # -- run.finalize --------------------------------------------------------

    async def _finalize(self, command: Command, uow: UnitOfWork) -> None:
        run_id = command.payload["run_id"]
        workspace_id = command.payload["workspace_id"]
        runs = RunRepository(uow.session)
        run = await runs.get(run_id, workspace_id)
        if run is None or run.status is RunStatus.COMPLETED:
            return
        results = RunResultRepository(uow.session)
        if await results.get(run_id) is not None:
            return  # 已固化

        trials = list(await TrialRepository(uow.session).list_for_run(run_id))
        scores = list(await ScoreRepository(uow.session).list_for_run(run_id))
        summary = summarize(trials, scores)

        metrics = {
            "task_success_rate": summary["pass_rate"],
            "avg_score": summary["avg_score"],
        }
        snapshot = snapshot_from_dict(run.template_snapshot)
        decision = _evaluate_gates(snapshot, metrics, scores, self.gates)
        total_cost = sum((item.cost_usd for item in trials), Decimal("0"))
        total_duration = sum(item.duration_ms or 0 for item in trials)

        result = RunResult(
            run_id=run_id,
            trial_counts=summary["trial_counts"],
            verdict_counts=summary["verdict_counts"],
            pass_rate=summary["pass_rate"],
            avg_score=summary["avg_score"],
            total_cost_usd=total_cost,
            total_duration_ms=total_duration,
            dimension_scores=_dimension_scores(snapshot, scores),
            gate_decision=decision,
            finalized_at=self.clock.now(),
        )
        results.add(result)
        await runs.set_state(
            run_id, status=RunStatus.COMPLETED, stage=RunStage.COMPLETED,
            ended_at=self.clock.now(),
        )


def _evaluate_gates(
    snapshot: TemplateSnapshot,
    metrics: Mapping[str, float],
    scores: Sequence[ScoreRecord],
    gates: GateEvaluatorPort,
) -> Mapping[str, Any] | None:
    """门禁经契约调用（`GateEvaluatorPort`），不直接 import evaluation 的领域代码。"""
    if not snapshot.gates:
        return None
    determinism = {spec.name: spec.determinism for spec in snapshot.evaluators}
    decision = gates.evaluate_gates(
        snapshot.gates,
        metrics,
        evaluator_determinism=determinism,
        sample_size=len(scores) or None,
    )
    return {
        "passed": decision.passed,
        "blocked_rules": list(decision.blocked_rules),
        "blocked_reasons": list(decision.blocked_reasons),
        "results": [
            {
                "rule": item.rule,
                "metric_key": item.metric_key,
                "actual": item.actual,
                "threshold": item.threshold,
                "unit": item.unit,
                "passed": item.passed,
                "action": item.action.value,
                "scope": item.scope.value,
                "skipped": item.skipped,
                "reason": item.reason,
            }
            for item in decision.results
        ],
    }


def _dimension_scores(
    snapshot: TemplateSnapshot, scores: Sequence[ScoreRecord]
) -> Mapping[str, float]:
    """按维度聚合：维度下的评估器分数取平均（权重留给展示层用）。"""
    by_metric: dict[str, list[float]] = {}
    for item in scores:
        if isinstance(item.value, (int, float)) and item.status in {"pass", "fail"}:
            by_metric.setdefault(item.metric, []).append(float(item.value))

    result: dict[str, float] = {}
    for dimension in snapshot.dimensions:
        values = [
            value
            for name in dimension.evaluator_names
            for value in by_metric.get(name, [])
        ]
        if values:
            result[dimension.id] = sum(values) / len(values)
    return result

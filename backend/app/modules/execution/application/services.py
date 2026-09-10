"""execution 用例：创建 Run、推进 Trial、固化结果。

流程全部由命令驱动（`run.prepare` → `trial.execute` × N → `run.finalize`），
每个 handler 都必须**幂等**——队列是 at-least-once 投递。

**`expected_output` 只用于评分，绝不进 Runtime 的 payload。**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Callable, Mapping, Sequence

from ....contracts.asset import AssetQueryPort, AssetVersionRef, SecretResolverPort
from ....contracts.memory import MemoryKey, MemorySessionPort
from ....contracts.common import (
    Channel,
    Determinism,
    EvaluationStage,
    ExecutionStatus,
    GateAction,
    GateScope,
    Id,
    RunStage,
    RunStatus,
    TraceOrigin,
    Verdict,
)
from ....contracts.dataset import SampleReaderPort, SampleRef
from ....contracts.execution import (
    ChannelInvocation,
    RunRef,
    InvokeEvent,
    InvokeResult,
    TrialRef,
)
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.evaluation import (
    GateEvaluatorPort,
    TemplateSnapshot,
    TemplateSnapshotPort,
)
from ....contracts.observability import InvocationTrace, TraceWriterPort
from ....persistence import Command, UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock, SystemClock
from ....shared.crypto import fingerprint
from ....shared.ids import new_id
from ..domain.models import Run, RunResult, ScoreRecord, Trial, summarize
from ..infrastructure.evaluators import MetricOutcome, aggregate_verdict, evaluate_metric
from ..infrastructure.repositories import (
    RunRepository,
    RunResultRepository,
    ScoreRepository,
    TrialRepository,
)
from .ports import InvocationContext, RunContext, RuntimePort, RuntimeSpec

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
        binding_overrides: Mapping[Id, Id] | None = None,
    ) -> Run:
        """冻结四件套：被测版本 + 数据集版本 + 策略快照 + 引用快照。之后不可改。

        `binding_overrides` 是能力资产 A/B 的入口：同一个 Agent 版本、同一份数据集，
        只换掉某个 Skill / MCP / 知识库的版本，跑两次 Run 做对比。
        """
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

        # 引用快照：把「跟随通道」解析成具体版本并冻住。此后资源晋级不影响这个 Run。
        overrides = dict(binding_overrides or {})
        binding_snapshot = dict(
            await self.assets.resolve_bindings(asset_version_id, workspace_id, overrides)
        )

        run = Run(
            id=new_id("run"),
            workspace_id=workspace_id,
            name=name,
            subject_kind="agent",
            subject_asset_id=version.asset_id,
            subject_version_id=version.id,
            dataset_version_id=dataset_version_id,
            template_snapshot=snapshot_to_dict(snapshot),
            binding_snapshot=binding_snapshot,
            binding_overrides=overrides,
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

    async def get_run_ref(self, run_id: Id, workspace_id: Id) -> RunRef | None:
        """实现 `contracts.execution.RunQueryPort`。"""
        async with UnitOfWork(self._db) as uow:
            run = await RunRepository(uow.session).get(run_id, workspace_id)
            if run is None:
                return None
            result = await RunResultRepository(uow.session).get(run_id)
        return self._to_run_ref(run, result)

    async def find_gate_run(
        self, version_id: Id, stage: EvaluationStage, workspace_id: Id
    ) -> RunRef | None:
        """该版本最近一次「该阶段 + 已完成 + 带门禁判定」的 Run。"""
        async with UnitOfWork(self._db) as uow:
            runs = await RunRepository(uow.session).list_for_version(workspace_id, version_id)
            for run in runs:
                if run.status is not RunStatus.COMPLETED:
                    continue
                snapshot = snapshot_from_dict(run.template_snapshot)
                if snapshot.stage is not stage:
                    continue
                result = await RunResultRepository(uow.session).get(run.id)
                if result is None or result.gate_decision is None:
                    continue
                return self._to_run_ref(run, result)
        return None

    @staticmethod
    def _to_run_ref(run: Run, result: RunResult | None) -> RunRef:
        snapshot = snapshot_from_dict(run.template_snapshot)
        return RunRef(
            id=run.id,
            workspace_id=run.workspace_id,
            name=run.name,
            subject_asset_id=run.subject_asset_id,
            subject_version_id=run.subject_version_id,
            dataset_version_id=run.dataset_version_id,
            stage=snapshot.stage,
            status=run.status,
            gate_decision=dict(result.gate_decision) if result and result.gate_decision else None,
            total_trials=run.total_trials,
        )

    async def get_trial_ref(self, trial_id: Id, workspace_id: Id) -> TrialRef | None:
        """实现 `contracts.execution.TrialQueryPort`：给回流提供只读投影。"""
        async with UnitOfWork(self._db) as uow:
            trial = await TrialRepository(uow.session).get(trial_id, workspace_id)
        if trial is None:
            return None
        return TrialRef(
            id=trial.id,
            run_id=trial.run_id,
            workspace_id=trial.workspace_id,
            tenant_id=trial.tenant_id,
            sample_id=trial.sample_id,
            execution_status=trial.execution_status,
            verdict=trial.verdict,
            instruction=trial.instruction,
            output=trial.output,
            error=trial.error,
        )

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
        # 能力资产走**冻结快照**，不重新解析：资源晋级不该改变这个 Run 的结果。
        capabilities: dict[Id, dict[str, Any]] = {}
        for provider_asset_id, provider_version_id in (run.binding_snapshot or {}).items():
            ref = await self.assets.get_version_ref(provider_version_id, workspace_id)
            if ref is not None:
                capabilities[provider_asset_id] = dict(ref.spec)
        if capabilities:
            payload["__capabilities__"] = capabilities
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
        # 能力资产走**冻结快照**，不重新解析：资源晋级不该改变这个 Run 的结果。
        capabilities: dict[Id, dict[str, Any]] = {}
        for provider_asset_id, provider_version_id in (run.binding_snapshot or {}).items():
            ref = await self.assets.get_version_ref(provider_version_id, workspace_id)
            if ref is not None:
                capabilities[provider_asset_id] = dict(ref.spec)

        handle = await self.runtime.provision(
            RuntimeSpec(
                asset_id=version.asset_id,
                asset_version_id=version.id,
                workspace_id=workspace_id,
                entrypoint=version.entrypoint,
                spec=version.spec,
                capabilities=capabilities,
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


# --------------------------------------------------------------------------- #
# 按通道调用（portal 消费）
# --------------------------------------------------------------------------- #

#: 通道 → Trace 来源。影子通道的调用就是影子流量，不能记成生产。
_ORIGIN_BY_CHANNEL = {
    Channel.TEST: TraceOrigin.EVALUATION,
    Channel.LIVESH: TraceOrigin.SHADOW,
    Channel.LIVE: TraceOrigin.PRODUCTION,
}

logger = logging.getLogger(__name__)


class InvokeService:
    """实现 `contracts.execution.InvokePort`：按通道打当前绑定的版本。

    与评测共用同一个 `RuntimePort`——所以线上调用和离线评测不会各维护一套协议。
    """

    def __init__(
        self,
        assets: AssetQueryPort,
        runtime: RuntimePort,
        *,
        traces: TraceWriterPort | None = None,
        clock: Clock | None = None,
        secrets: SecretResolverPort | None = None,
        memory_factory: Callable[[MemoryKey, Id], MemorySessionPort] | None = None,
    ) -> None:
        self._assets = assets
        self._runtime = runtime
        self._traces = traces
        self._clock = clock or SystemClock()
        #: 资源密钥解析。**可选**——没配的部署不注入密钥。
        self._secrets = secrets
        #: 记忆工厂：`(分区键, 工作区) → 句柄`。由组合根注入具体实现，
        #: execution 只认契约，不依赖 memory 模块。
        self._memory_factory = memory_factory

    async def invoke_channel(self, request: ChannelInvocation) -> InvokeResult:
        version, ctx, payload = await self._prepare(request)
        started_at = self._clock.now()
        handle = await self._provision(version, request, ctx)
        try:
            result = await self._runtime.invoke(handle, payload, ctx)
        finally:
            await self._runtime.teardown(handle)

        trace_id = await self._record(
            request,
            version,
            result,
            started_at,
            extra_metadata=_trace_metadata(payload),
        )
        return InvokeResult(
            output=result.output,
            error=result.error,
            trace_id=trace_id,
            duration_ms=result.duration_ms,
            cost_usd=result.cost_usd,
            version_label=version.version_label,
        )

    async def stream_channel(
        self, request: ChannelInvocation
    ) -> AsyncIterator[InvokeEvent]:
        """流式调用：**边产出边下发**。

        解析（通道→版本、entrypoint 校验）发生在产出第一个事件**之前**——
        这类错误调用方还能当普通 HTTP 错误处理，不必塞进流里。
        运行时失败则不同：那时流已经开始，只能作为 `error` 事件送出，
        并且**把已经吐出去的字一起带上**，前端才不会凭空丢半句话。
        """
        version, ctx, payload = await self._prepare(request)
        started_at = self._clock.now()
        handle = await self._provision(version, request, ctx)
        produced: list[str] = []
        failure: str | None = None
        try:
            async for piece in self._runtime.invoke_stream(handle, payload, ctx):
                produced.append(piece)
                yield InvokeEvent(delta=piece)
        except Exception as exc:  # noqa: BLE001 - 流已开始，只能作为事件送出
            logger.warning("流式调用中途失败", exc_info=True)
            failure = f"{type(exc).__name__}: {exc}"
        finally:
            await self._runtime.teardown(handle)

        text = "".join(produced)
        await self._record(
            request,
            version,
            InvokeResult(
                output=text or None,
                error=failure,
                version_label=version.version_label,
            ),
            started_at,
            extra_metadata={
                "secrets": payload.get("__secret_fingerprints__", {}),
                "thread_id": request.thread_id,
            },
        )

        if failure is not None:
            yield InvokeEvent(error=failure, finish_reason="error")
            return
        yield InvokeEvent(finish_reason="stop")

    # -- 内部：解析与装配（非流式/流式共用，避免两条路径慢慢跑偏）----------

    async def _prepare(
        self, request: ChannelInvocation
    ) -> tuple[AssetVersionRef, InvocationContext, dict[str, Any]]:
        version = await self._assets.version_of_channel(
            request.asset_id, request.channel, request.workspace_id
        )
        if version is None:
            raise DomainError(
                Errors.CHANNEL_UNBOUND,
                f"Agent {request.asset_id} 的 {request.channel.value} 通道没有绑定版本",
                channel=request.channel.value,
            )
        if not version.entrypoint:
            raise DomainError(
                Errors.RUN_SUBJECT_INCOMPLETE,
                f"版本 {version.version_label} 没有 entrypoint（sdk 接入不可调用）",
            )
        ctx = InvocationContext(
            workspace_id=request.workspace_id,
            tenant_id=request.tenant_id,
            timeout_seconds=request.timeout_seconds,
            cost_budget_usd=request.cost_budget_usd,
        )
        payload: dict[str, Any] = {
            "__entrypoint__": version.entrypoint,
            "input": request.input,
        }
        if request.messages:
            payload["messages"] = [dict(item) for item in request.messages]
        # 密钥按「版本 × 通道」解析成明文注入。**缺一把就失败**——不能静默少给，
        # 否则 Agent 会以「配置看起来对、行为很诡异」的形式暴露，比直接报错难查得多。
        secrets = await self._resolve_secrets(version, request)
        if secrets:
            payload["__secrets__"] = secrets
            # 只记**指纹**：出问题时能回答「当时用的是哪把钥匙」，
            # 但明文不进 Trace、不进导出、不进日志。
            payload["__secret_fingerprints__"] = {
                name: fingerprint(value) for name, value in secrets.items()
            }
        # 记忆句柄按「版本 × 租户 × 会话」分区——少一维都会读到别人的记忆。
        memory = self._build_memory(version, request)
        if memory is not None:
            payload["__memory__"] = memory
        return version, ctx, payload

    def _build_memory(
        self, version: AssetVersionRef, request: ChannelInvocation
    ) -> MemorySessionPort | None:
        """版本声明了 memory 作用域才给句柄；`stateless` 明确不要记忆。"""
        if self._memory_factory is None:
            return None
        declared = version.spec.get("memory")
        if not isinstance(declared, Mapping):
            return None
        scope = str(declared.get("scope") or "")
        if scope in ("", "stateless"):
            return None
        return self._memory_factory(
            MemoryKey(
                agent_version_id=version.id,
                tenant_id=request.tenant_id,
                thread_id=request.thread_id,
                scope=scope,  # type: ignore[arg-type]
            ),
            request.workspace_id,
        )

    async def _resolve_secrets(
        self, version: AssetVersionRef, request: ChannelInvocation
    ) -> dict[str, str]:
        """版本没声明 `secrets` 就跳过——绝大多数 Agent 不需要。"""
        if not _declares_secrets(version.spec) or self._secrets is None:
            return {}
        return dict(
            await self._secrets.resolve_secrets(
                asset_version_id=version.id,
                channel=request.channel,
                workspace_id=request.workspace_id,
            )
        )

    async def _provision(
        self,
        version: AssetVersionRef,
        request: ChannelInvocation,
        ctx: InvocationContext,
    ) -> RuntimeHandle:
        return await self._runtime.provision(
            RuntimeSpec(
                asset_id=version.asset_id,
                asset_version_id=version.id,
                workspace_id=request.workspace_id,
                entrypoint=version.entrypoint,
                spec=version.spec,
            ),
            ctx,
        )

    async def _record(
        self,
        request: ChannelInvocation,
        version: AssetVersionRef,
        result: InvokeResult,
        started_at: datetime,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> Id | None:
        """落一条 Trace。**记不上也不能让对话失败**——所以整体吞异常并降级。"""
        if self._traces is None:
            return None
        try:
            return await self._traces.record_invocation(
                InvocationTrace(
                    workspace_id=request.workspace_id,
                    tenant_id=request.tenant_id,
                    asset_id=version.asset_id,
                    asset_version_id=version.id,
                    channel=request.channel,
                    origin=_ORIGIN_BY_CHANNEL[request.channel],
                    external_trace_id=f"gw-{request.request_id or new_id('invocation')}",
                    name=f"{request.channel.value} 通道调用",
                    status="error" if result.error else "success",
                    started_at=started_at,
                    ended_at=self._clock.now(),
                    input=request.input,
                    output=result.output,
                    error=result.error,
                    usage=result.usage,
                    metadata=extra_metadata or {},
                )
            )
        except Exception:  # noqa: BLE001 - 观测失败不该影响业务调用
            logger.warning("记录调用 Trace 失败", exc_info=True)
            return None

def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _declares_secrets(spec: Mapping[str, Any]) -> bool:
    """版本 spec 里声明了密钥引用才去解析——省掉绝大多数调用的无用查询。"""
    declared = spec.get("secrets")
    return isinstance(declared, (list, tuple)) and len(declared) > 0

def _trace_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """落 Trace 时附带的补充事实——只有指纹与分区，没有明文。"""
    return {
        "secrets": payload.get("__secret_fingerprints__", {}),
        "thread_id": payload.get("__thread_id__"),
    }

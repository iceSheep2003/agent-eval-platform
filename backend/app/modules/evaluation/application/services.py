"""evaluation 用例：策略编排、绑定、门禁预览。

**策略与数据集的匹配是硬约束**：`template.stage ∈ dataset.stages`，不匹配直接拒绝，
避免把「只用于开发验证的宽松样本」绑到发布门禁上（docs/backend-dataset.md §2）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ....contracts.asset import AssetQueryPort
from ....contracts.common import Determinism, EvaluationStage, Id
from ....contracts.dataset import DatasetQueryPort
from ....contracts.errors import DomainError, Errors, NotFound
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.catalog import BUILTIN_EVALUATORS, resolve_evaluator
from ..domain.gate import GateDecision, evaluate_gate
from ..domain.models import (
    Capability,
    EvaluationTemplate,
    EvaluatorSpec,
    GateRule,
    ScoreDimension,
    TemplateBinding,
    gates_from_mapping,
)
from ..infrastructure.repositories import CapabilityRepository, TemplateRepository

#: 未指定 evaluators 时，按维度自动推导。
DEFAULT_EVALUATORS = ("answer_exact_match", "task_completion")


@dataclass(frozen=True, slots=True)
class CapabilityView:
    capability: Capability
    dimensions: tuple[ScoreDimension, ...]


class EvaluationService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        datasets: DatasetQueryPort,
        assets: AssetQueryPort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._datasets = datasets
        self._assets = assets

    # -- 目录 ----------------------------------------------------------------

    def evaluator_catalog(self) -> Sequence[EvaluatorSpec]:
        return BUILTIN_EVALUATORS

    async def list_capabilities(self, workspace_id: Id) -> Sequence[CapabilityView]:
        async with UnitOfWork(self._db) as uow:
            repo = CapabilityRepository(uow.session)
            capabilities = await repo.list_for_workspace(workspace_id)
            dimensions = await repo.list_dimensions(workspace_id)
        by_capability: dict[str, list[ScoreDimension]] = {}
        for dimension in dimensions:
            by_capability.setdefault(dimension.capability_id, []).append(dimension)
        return tuple(
            CapabilityView(capability=item, dimensions=tuple(by_capability.get(item.id, ())))
            for item in capabilities
        )

    # -- 策略 ----------------------------------------------------------------

    async def list_templates(
        self, workspace_id: Id, stage: EvaluationStage | None = None
    ) -> Sequence[EvaluationTemplate]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await TemplateRepository(uow.session).list_for_workspace(workspace_id, stage)
            )

    async def get_template(self, template_id: Id, workspace_id: Id) -> EvaluationTemplate:
        async with UnitOfWork(self._db) as uow:
            template = await TemplateRepository(uow.session).get(template_id, workspace_id)
        if template is None:
            raise NotFound("评测策略", template_id)
        return template

    async def list_templates_for_asset(
        self, asset_id: Id, workspace_id: Id
    ) -> Sequence[EvaluationTemplate]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await TemplateRepository(uow.session).list_for_asset(asset_id, workspace_id)
            )

    async def binding_counts(self, workspace_id: Id) -> Mapping[str, int]:
        async with UnitOfWork(self._db) as uow:
            return await TemplateRepository(uow.session).count_bindings(workspace_id)

    async def create_template(
        self,
        *,
        workspace_id: Id,
        created_by: Id,
        name: str,
        stage: EvaluationStage,
        trigger_type: str = "manual",
        dataset_version_id: Id | None = None,
        evaluator_names: Sequence[str] | None = None,
        dimension_ids: Sequence[Id] = (),
        gates: Mapping[str, float] | Sequence[GateRule] | None = None,
        enabled: bool = True,
    ) -> EvaluationTemplate:
        dataset_id = await self._validate_stage(workspace_id, stage, dataset_version_id)
        evaluators = self._resolve_evaluators(evaluator_names)
        rules = self._resolve_gates(gates)

        async with UnitOfWork(self._db) as uow:
            repo = TemplateRepository(uow.session)
            existing = await repo.find_by_name(workspace_id, name)
            if existing is not None:
                return existing
            template = EvaluationTemplate(
                id=new_id("template"),
                workspace_id=workspace_id,
                name=name,
                stage=stage,
                trigger_type=trigger_type,  # type: ignore[arg-type]
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
                evaluators=evaluators,
                dimension_ids=tuple(dimension_ids),
                gates=rules,
                enabled=enabled,
                created_by=created_by,
                created_at=self._clock.now(),
            )
            repo.add(template)
            await uow.commit()
        return template

    async def update_template(
        self,
        template_id: Id,
        workspace_id: Id,
        *,
        stage: EvaluationStage | None = None,
        dataset_version_id: Id | None = None,
        evaluator_names: Sequence[str] | None = None,
        dimension_ids: Sequence[Id] | None = None,
        gates: Mapping[str, float] | Sequence[GateRule] | None = None,
        enabled: bool | None = None,
        trigger_type: str | None = None,
    ) -> EvaluationTemplate:
        current = await self.get_template(template_id, workspace_id)
        resolved_stage = stage or current.stage
        resolved_version = (
            dataset_version_id if dataset_version_id is not None else current.dataset_version_id
        )
        dataset_id = await self._validate_stage(workspace_id, resolved_stage, resolved_version)

        fields: dict[str, Any] = {
            "stage": resolved_stage,
            "dataset_id": dataset_id,
            "dataset_version_id": resolved_version,
        }
        if evaluator_names is not None:
            fields["evaluators"] = self._resolve_evaluators(evaluator_names)
        if dimension_ids is not None:
            fields["dimension_ids"] = list(dimension_ids)
        if gates is not None:
            fields["gates"] = self._resolve_gates(gates)
        if enabled is not None:
            fields["enabled"] = enabled
        if trigger_type is not None:
            fields["trigger_type"] = trigger_type

        async with UnitOfWork(self._db) as uow:
            await TemplateRepository(uow.session).update_fields(template_id, **fields)
            await uow.commit()
        return await self.get_template(template_id, workspace_id)

    async def disable_template(self, template_id: Id, workspace_id: Id) -> EvaluationTemplate:
        """停用后不再被自动触发，也不参与门禁判定，但历史执行结果保留。"""
        return await self.update_template(template_id, workspace_id, enabled=False)

    # -- 绑定 ----------------------------------------------------------------

    async def bind(
        self, template_id: Id, asset_id: Id, workspace_id: Id
    ) -> TemplateBinding:
        await self.get_template(template_id, workspace_id)
        if await self._assets.get_asset(asset_id, workspace_id) is None:
            raise NotFound("资产", asset_id)
        binding = TemplateBinding(
            template_id=template_id,
            asset_id=asset_id,
            workspace_id=workspace_id,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            TemplateRepository(uow.session).add_binding(binding)
            await uow.commit()
        return binding

    async def unbind(self, template_id: Id, asset_id: Id, workspace_id: Id) -> None:
        await self.get_template(template_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            await TemplateRepository(uow.session).remove_binding(template_id, asset_id)
            await uow.commit()

    # -- 门禁 ----------------------------------------------------------------

    async def preview_gate(
        self,
        template_id: Id,
        workspace_id: Id,
        metrics: Mapping[str, float],
        *,
        sample_size: int | None = None,
    ) -> GateDecision:
        """用给定指标试跑门禁。纯函数 + 当前策略，不落库。"""
        template = await self.get_template(template_id, workspace_id)
        determinism = {
            spec.name: spec.determinism for spec in template.evaluators
        }
        return evaluate_gate(
            template.gates,
            metrics,
            evaluator_determinism=determinism,
            sample_size=sample_size,
            now=self._clock.now(),
        )

    # -- 内部 ----------------------------------------------------------------

    async def _validate_stage(
        self, workspace_id: Id, stage: EvaluationStage, dataset_version_id: Id | None
    ) -> Id | None:
        if dataset_version_id is None:
            return None
        ref = await self._datasets.get_version_ref(dataset_version_id, workspace_id)
        if ref is None:
            raise NotFound("数据集版本", dataset_version_id)
        if stage not in ref.stages:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                f"数据集「{ref.version_label}」不适用于 {stage.value} 阶段"
                f"（适用：{'、'.join(item.value for item in ref.stages)}）",
                stage=stage.value,
                allowed=[item.value for item in ref.stages],
            )
        return ref.dataset_id

    def _resolve_evaluators(
        self, names: Sequence[str] | None
    ) -> tuple[EvaluatorSpec, ...]:
        if not names:
            return tuple(
                item for item in BUILTIN_EVALUATORS if item.name in DEFAULT_EVALUATORS
            )
        resolved: list[EvaluatorSpec] = []
        for name in names:
            spec = resolve_evaluator(name)
            if spec is None:
                raise DomainError(Errors.EVALUATOR_UNKNOWN, f"未注册的评估器：{name}")
            resolved.append(spec)
        return tuple(resolved)

    def _resolve_gates(
        self, gates: Mapping[str, float] | Sequence[GateRule] | None
    ) -> tuple[GateRule, ...]:
        if gates is None:
            return ()
        if isinstance(gates, Mapping):
            return gates_from_mapping(gates)
        return tuple(gates)


__all__ = ["BUILTIN_EVALUATORS", "CapabilityView", "Determinism", "EvaluationService"]

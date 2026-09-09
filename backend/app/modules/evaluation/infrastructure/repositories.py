"""evaluation 仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import Determinism, EvaluationStage, GateAction, GateScope
from ....shared.clock import ensure_aware
from ..domain.models import (
    Capability,
    EvaluationTemplate,
    GateRule,
    ScoreDimension,
    TemplateBinding,
)
from .tables import BindingRow, CapabilityRow, DimensionRow, TemplateRow


def _capability(row: CapabilityRow) -> Capability:
    return Capability(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        description=row.description,
        enabled=bool(row.enabled),
        created_at=ensure_aware(row.created_at),
    )


def _dimension(row: DimensionRow) -> ScoreDimension:
    return ScoreDimension(
        id=row.id,
        capability_id=row.capability_id,
        workspace_id=row.workspace_id,
        name=row.name,
        weight=float(row.weight),
        threshold=float(row.threshold),
        evaluator_names=tuple(row.evaluator_names or ()),
        score=float(row.score) if row.score is not None else None,
        created_at=ensure_aware(row.created_at),
    )


def _gate(raw: Mapping[str, Any]) -> GateRule:
    return GateRule(
        name=str(raw.get("name") or raw.get("metric_key")),
        metric_key=str(raw.get("metric_key") or raw.get("name")),
        threshold=float(raw.get("threshold") or 0),
        unit=raw.get("unit") or "score",  # type: ignore[arg-type]
        comparison=raw.get("comparison") or "gte",  # type: ignore[arg-type]
        scope=GateScope(raw.get("scope") or GateScope.WORKSPACE),
        action=GateAction(raw.get("action") or GateAction.BLOCK),
        required_determinism=(
            Determinism(raw["required_determinism"]) if raw.get("required_determinism") else None
        ),
        min_samples=int(raw.get("min_samples") or 0),
    )


def _gate_dict(gate: GateRule) -> dict[str, Any]:
    return {
        "name": gate.name,
        "metric_key": gate.metric_key,
        "threshold": gate.threshold,
        "unit": gate.unit,
        "comparison": gate.comparison,
        "scope": gate.scope.value,
        "action": gate.action.value,
        "required_determinism": gate.required_determinism.value if gate.required_determinism else None,
        "min_samples": gate.min_samples,
    }


def _template(row: TemplateRow) -> EvaluationTemplate:
    from ..domain.models import EvaluatorSpec

    return EvaluationTemplate(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        stage=EvaluationStage(row.stage),
        trigger_type=row.trigger_type,  # type: ignore[arg-type]
        dataset_id=row.dataset_id,
        dataset_version_id=row.dataset_version_id,
        evaluators=tuple(
            EvaluatorSpec(
                name=item["name"],
                version=str(item.get("version") or "1.0.0"),
                determinism=Determinism(item.get("determinism") or Determinism.DETERMINISTIC),
                config=dict(item.get("config") or {}),
            )
            for item in (row.evaluators or ())
        ),
        dimension_ids=tuple(row.dimension_ids or ()),
        gates=tuple(_gate(item) for item in (row.gates or ())),
        enabled=bool(row.enabled),
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
    )


def _binding(row: BindingRow) -> TemplateBinding:
    return TemplateBinding(
        template_id=row.template_id,
        asset_id=row.asset_id,
        workspace_id=row.workspace_id,
        created_at=ensure_aware(row.created_at),
    )


class CapabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_workspace(self, workspace_id: str) -> Sequence[Capability]:
        stmt = (
            select(CapabilityRow)
            .where(CapabilityRow.workspace_id == workspace_id)
            .order_by(CapabilityRow.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_capability(row) for row in rows]

    async def get(self, capability_id: str, workspace_id: str) -> Capability | None:
        stmt = select(CapabilityRow).where(
            CapabilityRow.id == capability_id, CapabilityRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _capability(row) if row else None

    def add(self, capability: Capability) -> None:
        self._session.add(
            CapabilityRow(
                id=capability.id,
                workspace_id=capability.workspace_id,
                name=capability.name,
                description=capability.description,
                enabled=capability.enabled,
            )
        )

    async def list_dimensions(self, workspace_id: str) -> Sequence[ScoreDimension]:
        stmt = (
            select(DimensionRow)
            .where(DimensionRow.workspace_id == workspace_id)
            .order_by(DimensionRow.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_dimension(row) for row in rows]

    async def get_dimensions(self, ids: Sequence[str]) -> Sequence[ScoreDimension]:
        if not ids:
            return ()
        stmt = select(DimensionRow).where(DimensionRow.id.in_(list(ids)))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_dimension(row) for row in rows]

    def add_dimension(self, dimension: ScoreDimension) -> None:
        self._session.add(
            DimensionRow(
                id=dimension.id,
                capability_id=dimension.capability_id,
                workspace_id=dimension.workspace_id,
                name=dimension.name,
                weight=dimension.weight,
                threshold=dimension.threshold,
                evaluator_names=list(dimension.evaluator_names),
                score=dimension.score,
            )
        )


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, template_id: str, workspace_id: str) -> EvaluationTemplate | None:
        stmt = select(TemplateRow).where(
            TemplateRow.id == template_id, TemplateRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _template(row) if row else None

    async def find_by_name(self, workspace_id: str, name: str) -> EvaluationTemplate | None:
        stmt = select(TemplateRow).where(
            TemplateRow.workspace_id == workspace_id, TemplateRow.name == name
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _template(row) if row else None

    async def list_for_workspace(
        self, workspace_id: str, stage: EvaluationStage | None = None
    ) -> Sequence[EvaluationTemplate]:
        stmt = select(TemplateRow).where(TemplateRow.workspace_id == workspace_id)
        if stage is not None:
            stmt = stmt.where(TemplateRow.stage == stage.value)
        stmt = stmt.order_by(TemplateRow.created_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_template(row) for row in rows]

    async def list_for_asset(self, asset_id: str, workspace_id: str) -> Sequence[EvaluationTemplate]:
        stmt = (
            select(TemplateRow)
            .join(BindingRow, BindingRow.template_id == TemplateRow.id)
            .where(BindingRow.asset_id == asset_id, TemplateRow.workspace_id == workspace_id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_template(row) for row in rows]

    def add(self, template: EvaluationTemplate) -> None:
        self._session.add(
            TemplateRow(
                id=template.id,
                workspace_id=template.workspace_id,
                name=template.name,
                stage=template.stage.value,
                trigger_type=template.trigger_type,
                dataset_id=template.dataset_id,
                dataset_version_id=template.dataset_version_id,
                evaluators=[
                    {
                        "name": item.name,
                        "version": item.version,
                        "determinism": item.determinism.value,
                        "config": dict(item.config),
                    }
                    for item in template.evaluators
                ],
                dimension_ids=list(template.dimension_ids),
                gates=[_gate_dict(gate) for gate in template.gates],
                enabled=template.enabled,
                created_by=template.created_by,
            )
        )

    async def update_fields(self, template_id: str, **fields: Any) -> None:
        if "evaluators" in fields:
            fields["evaluators"] = [
                {
                    "name": item.name,
                    "version": item.version,
                    "determinism": item.determinism.value,
                    "config": dict(item.config),
                }
                for item in fields["evaluators"]
            ]
        if "gates" in fields:
            fields["gates"] = [_gate_dict(gate) for gate in fields["gates"]]
        if "stage" in fields:
            fields["stage"] = fields["stage"].value
        await self._session.execute(
            update(TemplateRow).where(TemplateRow.id == template_id).values(**fields)
        )

    async def bindings_for_template(self, template_id: str) -> Sequence[TemplateBinding]:
        stmt = select(BindingRow).where(BindingRow.template_id == template_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_binding(row) for row in rows]

    async def count_bindings(self, workspace_id: str) -> Mapping[str, int]:
        from sqlalchemy import func

        stmt = (
            select(BindingRow.template_id, func.count())
            .where(BindingRow.workspace_id == workspace_id)
            .group_by(BindingRow.template_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {str(key): int(count) for key, count in rows}

    def add_binding(self, binding: TemplateBinding) -> None:
        self._session.add(
            BindingRow(
                id=f"{binding.template_id}:{binding.asset_id}",
                template_id=binding.template_id,
                asset_id=binding.asset_id,
                workspace_id=binding.workspace_id,
            )
        )

    async def remove_binding(self, template_id: str, asset_id: str) -> None:
        await self._session.execute(
            delete(BindingRow).where(
                BindingRow.template_id == template_id, BindingRow.asset_id == asset_id
            )
        )

"""evaluation 的 HTTP 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import EvaluationStage
from ....contracts.identity import Permission
from ....schemas.response import list_response, ok
from ..application.services import CapabilityView, EvaluationService
from ..domain.models import EvaluationTemplate, gates_as_mapping
from .schemas import (
    BindRequest,
    CapabilityDTO,
    CreatePolicyRequest,
    DimensionDTO,
    EvaluatorDTO,
    PolicyDTO,
    PreviewGateRequest,
    UpdatePolicyRequest,
    gate_decision_dto,
)

router = APIRouter(tags=["evaluation"])


def get_evaluation_service(
    container: Annotated[Container, Depends(get_container)],
) -> EvaluationService:
    return container.evaluations


def _policy_dto(template: EvaluationTemplate, binding_count: int) -> PolicyDTO:
    return PolicyDTO(
        id=template.id,
        name=template.name,
        lifecycle=template.stage.value,
        stage=template.stage.value,
        trigger_type=template.trigger_type,
        dataset_id=template.dataset_id,
        dataset_version_id=template.dataset_version_id,
        evaluators=[item.name for item in template.evaluators],
        dimension_ids=list(template.dimension_ids),
        gates=gates_as_mapping(template.gates),  # type: ignore[arg-type]
        enabled=template.enabled,
        binding_count=binding_count,
    )


def _capability_dto(view: CapabilityView) -> CapabilityDTO:
    return CapabilityDTO(
        id=view.capability.id,
        name=view.capability.name,
        description=view.capability.description,
        enabled=view.capability.enabled,
        dimensions=[
            DimensionDTO(
                id=item.id,
                name=item.name,
                score=item.score,
                threshold=item.threshold,
                weight=item.weight,
                evaluators=list(item.evaluator_names),
            )
            for item in view.dimensions
        ],
    )


@router.get("/capabilities")
async def list_capabilities(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_READ)
    views = await service.list_capabilities(actor.workspace_id)
    return list_response([_capability_dto(view).model_dump() for view in views])


@router.get("/dimensions")
async def list_dimensions(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_READ)
    views = await service.list_capabilities(actor.workspace_id)
    items = [
        {**_capability_dto(view).model_dump()["dimensions"][index], "capability": view.capability.name}
        for view in views
        for index in range(len(view.dimensions))
    ]
    return list_response(items)


@router.get("/evaluators")
async def list_evaluators(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_READ)
    return list_response(
        [
            EvaluatorDTO(
                name=item.name,
                version=item.version,
                determinism=item.determinism.value,
                description=item.description,
            ).model_dump()
            for item in service.evaluator_catalog()
        ]
    )


@router.get("/policies")
async def list_policies(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
    stage: EvaluationStage | None = None,
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_READ)
    counts = await service.binding_counts(actor.workspace_id)
    templates = await service.list_templates(actor.workspace_id, stage)
    return list_response(
        [_policy_dto(item, counts.get(item.id, 0)).model_dump() for item in templates]
    )


@router.post("/policies")
async def create_policy(
    payload: CreatePolicyRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_CREATE)
    template = await service.create_template(
        workspace_id=actor.workspace_id,
        created_by=actor.user_id,
        name=payload.name,
        stage=payload.stage,
        trigger_type=payload.trigger_type,
        dataset_version_id=payload.dataset_version_id,
        evaluator_names=payload.evaluators,
        dimension_ids=payload.dimension_ids,
        gates=payload.gates,
        enabled=payload.enabled,
    )
    return ok(_policy_dto(template, 0).model_dump())


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    payload: UpdatePolicyRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_UPDATE)
    template = await service.update_template(
        policy_id,
        actor.workspace_id,
        stage=payload.stage,
        dataset_version_id=payload.dataset_version_id,
        evaluator_names=payload.evaluators,
        dimension_ids=payload.dimension_ids,
        gates=payload.gates,
        enabled=payload.enabled,
        trigger_type=payload.trigger_type,
    )
    counts = await service.binding_counts(actor.workspace_id)
    return ok(_policy_dto(template, counts.get(template.id, 0)).model_dump())


@router.post("/policies/{policy_id}/bindings")
async def bind_policy(
    policy_id: str,
    payload: BindRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_BIND)
    await service.bind(policy_id, payload.asset_id, actor.workspace_id)
    counts = await service.binding_counts(actor.workspace_id)
    return ok({"template_id": policy_id, "asset_id": payload.asset_id,
               "binding_count": counts.get(policy_id, 0)})


@router.delete("/policies/{policy_id}/bindings/{asset_id}")
async def unbind_policy(
    policy_id: str,
    asset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    assert_permission(container, actor, Permission.TEMPLATE_BIND)
    await service.unbind(policy_id, asset_id, actor.workspace_id)
    return ok({"template_id": policy_id, "asset_id": asset_id})


@router.post("/policies/{policy_id}/preview-gate")
async def preview_gate(
    policy_id: str,
    payload: PreviewGateRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    """用给定指标试跑门禁——纯函数，不落库。前端用来解释「为什么被阻断」。"""
    assert_permission(container, actor, Permission.TEMPLATE_READ)
    decision = await service.preview_gate(
        policy_id, actor.workspace_id, payload.metrics, sample_size=payload.sample_size
    )
    return ok(gate_decision_dto(decision).model_dump())

"""delivery 的 HTTP 路由。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import Channel, GateScope
from ....contracts.errors import DomainError, Errors
from ....contracts.identity import Permission, ResourceRef
from ....schemas.response import list_response, ok
from ..application.services import DeliveryService
from ..domain.models import Promotion, Rollback, ShadowRoute

router = APIRouter(tags=["delivery"])

#: 目标通道 → 需要的权限点。LIVE 是生产发布，单独收紧。
PROMOTE_PERMISSION = {
    Channel.LIVESH: Permission.VERSION_PROMOTE_LIVESH,
    Channel.LIVE: Permission.VERSION_PROMOTE_LIVE,
}


class PromoteRequest(BaseModel):
    asset_id: str
    version_id: str
    to_channel: Literal["livesh", "live"]
    run_id: str | None = None
    #: 高风险动作的二次确认占位。真正的 re-auth ticket 见架构文档 §5.1.5。
    confirm: bool = False


class RollbackRequest(BaseModel):
    channel: Literal["test", "livesh", "live"]
    to_version_id: str
    reason: str = Field(min_length=1, max_length=512)
    confirm: bool = False


class ShadowRouteRequest(BaseModel):
    candidate_version_id: str
    baseline_version_id: str | None = None
    sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    enabled: bool = True


class PromotionDTO(BaseModel):
    id: str
    asset_id: str
    version_id: str
    from_channel: str
    to_channel: str
    run_id: str
    gate_passed: bool
    requested_by: str
    created_at: str


class RollbackDTO(BaseModel):
    id: str
    channel: str
    from_version_id: str | None
    to_version_id: str
    reason: str
    actor_id: str
    created_at: str


class ShadowRouteDTO(BaseModel):
    id: str
    candidate_version_id: str
    baseline_version_id: str | None
    sample_rate: float
    direction: str
    enabled: bool
    created_at: str


def get_delivery_service(
    container: Annotated[Container, Depends(get_container)],
) -> DeliveryService:
    return container.delivery


def _assert_confirm(container: Container, actor, permission: Permission) -> None:
    """`requires_reauth` 的动作需要显式确认。

    这是**占位实现**：真正的 re-auth ticket（跳 IdP 重新认证）见架构文档 §5.1.5。
    在此之前至少让「需要再认证」这个判定产生实际效果，而不是只在权限表里躺着。
    """
    decision = container.authorizer.decide(actor.subject, permission, None)
    if not decision.allowed:
        from ....contracts.errors import PermissionDenied

        raise PermissionDenied(permission.value, decision.reason)
    if decision.requires_reauth:
        raise DomainError(Errors.REAUTH_REQUIRED, "该操作需要二次确认（confirm=true）")


def _promotion_dto(item: Promotion) -> PromotionDTO:
    return PromotionDTO(
        id=item.id,
        asset_id=item.asset_id,
        version_id=item.version_id,
        from_channel=item.from_channel.value,
        to_channel=item.to_channel.value,
        run_id=item.run_id,
        gate_passed=item.gate_passed,
        requested_by=item.requested_by,
        created_at=item.created_at.isoformat(),
    )


def _rollback_dto(item: Rollback) -> RollbackDTO:
    return RollbackDTO(
        id=item.id,
        channel=item.channel.value,
        from_version_id=item.from_version_id,
        to_version_id=item.to_version_id,
        reason=item.reason,
        actor_id=item.actor_id,
        created_at=item.created_at.isoformat(),
    )


def _shadow_dto(item: ShadowRoute) -> ShadowRouteDTO:
    return ShadowRouteDTO(
        id=item.id,
        candidate_version_id=item.candidate_version_id,
        baseline_version_id=item.baseline_version_id,
        sample_rate=item.sample_rate,
        direction=item.direction,
        enabled=item.enabled,
        created_at=item.created_at.isoformat(),
    )


@router.post("/promotions")
async def create_promotion(
    payload: PromoteRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    target = Channel(payload.to_channel)
    permission = PROMOTE_PERMISSION[target]
    if payload.confirm:
        assert_permission(container, actor, permission)
    else:
        _assert_confirm(container, actor, permission)
    promotion = await service.request_promotion(
        asset_id=payload.asset_id,
        version_id=payload.version_id,
        to_channel=target,
        run_id=payload.run_id,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
    )
    return ok(_promotion_dto(promotion).model_dump())


@router.get("/agents/{agent_id}/promotions")
async def list_promotions(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.ASSET_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    items = await service.list_promotions(agent_id, actor.workspace_id)
    return list_response([_promotion_dto(item).model_dump() for item in items])


@router.get("/agents/{agent_id}/versions/{version_id}/shadow-comparison")
async def shadow_comparison(
    agent_id: str,
    version_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    """候选（shadow）vs 基线（production）的原始指标。

    前端用它解释「LIVESH → LIVE 为什么被阻断」——只给一句「门禁未通过」没法排查。
    """
    assert_permission(
        container,
        actor,
        Permission.ASSET_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    comparison = await service.shadow_comparison(agent_id, version_id, actor.workspace_id)

    def _metrics(item):
        if item is None:
            return None
        return {
            "version_id": item.asset_version_id,
            "origin": item.origin.value,
            "trace_count": item.trace_count,
            "success_rate": item.success_rate,
            "p95_latency_ms": item.p95_latency_ms,
            "average_cost_usd": float(item.average_cost_usd),
        }

    return ok(
        {
            "window_days": comparison["window_days"],
            "min_samples": comparison["min_samples"],
            "candidate": _metrics(comparison["candidate"]),
            "baseline": _metrics(comparison["baseline"]),
        }
    )


@router.post("/agents/{agent_id}/rollback")
async def rollback(
    agent_id: str,
    payload: RollbackRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    if payload.confirm:
        assert_permission(container, actor, Permission.VERSION_ROLLBACK)
    else:
        _assert_confirm(container, actor, Permission.VERSION_ROLLBACK)
    item = await service.rollback(
        asset_id=agent_id,
        channel=Channel(payload.channel),
        to_version_id=payload.to_version_id,
        reason=payload.reason,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
    )
    return ok(_rollback_dto(item).model_dump())


@router.get("/agents/{agent_id}/rollbacks")
async def list_rollbacks(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.ASSET_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    items = await service.list_rollbacks(agent_id, actor.workspace_id)
    return list_response([_rollback_dto(item).model_dump() for item in items])


@router.get("/agents/{agent_id}/shadow-route")
async def get_shadow_route(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.ASSET_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    route = await service.get_shadow(agent_id, actor.workspace_id)
    return ok(_shadow_dto(route).model_dump() if route else None)


@router.post("/agents/{agent_id}/shadow-route")
async def configure_shadow_route(
    agent_id: str,
    payload: ShadowRouteRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.SHADOW_CONFIGURE,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    route = await service.configure_shadow(
        asset_id=agent_id,
        candidate_version_id=payload.candidate_version_id,
        baseline_version_id=payload.baseline_version_id,
        sample_rate=payload.sample_rate,
        workspace_id=actor.workspace_id,
        enabled=payload.enabled,
    )
    return ok(_shadow_dto(route).model_dump())


__all__ = ["GateScope", "router"]

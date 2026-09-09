"""observability 的控制台路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import TraceOrigin
from ....contracts.errors import NotFound, PermissionDenied
from ....contracts.identity import Permission, ResourceRef
from ....schemas.response import list_response, ok
from ..application.services import TraceQuery, TraceService
from .schemas import (
    metrics_dto,
    resource_metrics_dto,
    trace_dto,
    trace_summary_dto,
)

router = APIRouter(tags=["observability"])


def get_trace_service(container: Annotated[Container, Depends(get_container)]) -> TraceService:
    return container.traces


def _visible_tenants(container: Container, actor) -> tuple[str, ...] | None:
    """返回 None 表示「全部可见」。**租户过滤在 SQL 层做**，不在应用层筛。"""
    if actor.subject.tenant_scope == "all":
        return None
    return actor.subject.tenant_scope


@router.get("/agents/{agent_id}/traces")
async def list_traces(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[TraceService, Depends(get_trace_service)],
    origin: TraceOrigin | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.TRACE_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    traces, total = await service.list_traces(
        actor.workspace_id,
        TraceQuery(
            asset_id=agent_id,
            origin=origin,
            status=status,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
        _visible_tenants(container, actor),
    )
    return list_response(
        [trace_summary_dto(trace).model_dump() for trace in traces], total=total
    )


@router.get("/traces/{trace_id}")
async def get_trace(
    trace_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[TraceService, Depends(get_trace_service)],
) -> dict:
    trace = await service.get_trace(trace_id, actor.workspace_id)
    assert_permission(
        container,
        actor,
        Permission.TRACE_READ,
        ResourceRef(
            kind="asset",
            id=trace.asset_id,
            workspace_id=trace.workspace_id,
            tenant_id=trace.tenant_id,
        ),
    )
    nodes = await service.span_tree(trace.id)
    return ok(trace_dto(trace, nodes).model_dump())


@router.get("/agents/{agent_id}/metrics")
async def agent_metrics(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[TraceService, Depends(get_trace_service)],
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.METRICS_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    metrics = await service.agent_metrics(
        actor.workspace_id,
        agent_id,
        window_hours=window_hours,
        tenant_ids=_visible_tenants(container, actor),
    )
    return ok(metrics_dto(metrics).model_dump())


@router.get("/assets/{asset_id}/versions/{version_id}/metrics")
async def resource_metrics(
    asset_id: str,
    version_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[TraceService, Depends(get_trace_service)],
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> dict:
    """能力资产版本的用量与质量（N3）。

    放在 observability 而不是 asset：指标是 Trace/Span 的产物，
    让 asset 去查 obs 的表会破坏表所有权。
    """
    assert_permission(
        container,
        actor,
        Permission.METRICS_READ,
        ResourceRef(kind="asset", id=asset_id, workspace_id=actor.workspace_id),
    )
    asset = await container.assets.get_asset(asset_id, actor.workspace_id)
    if asset is None:
        raise NotFound("资产", asset_id)
    consumers = await container.assets.consumers_of_resource(
        workspace_id=actor.workspace_id, resource_asset_id=asset_id
    )
    metrics = await service.resource_metrics(
        workspace_id=actor.workspace_id,
        resource_asset_id=asset_id,
        resource_version_id=version_id,
        kind=asset.kind.value,
        window_hours=window_hours,
        consumer_asset_ids=consumers,
    )
    return ok(resource_metrics_dto(metrics).model_dump())


__all__ = ["PermissionDenied", "router"]

"""deployment 的 HTTP 路由：运行实例的启停。

**发布通道和运行实例是两条独立的生命周期**——冻结版本不启动，晋级也不启动
（LIVE 除外：发布即生效）。所以这里是一组独立的启停接口，不是晋级接口的附属。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.errors import NotFound, PermissionDenied
from ....contracts.identity import Permission, ResourceRef
from ....schemas.response import list_response, ok
from ..application.services import DeploymentService
from .schemas import StartInstanceRequest, action_dto, instance_dto

router = APIRouter(tags=["deployment"])


def get_deployment_service(
    container: Annotated[Container, Depends(get_container)],
) -> DeploymentService:
    return container.deployments


async def _authorize_on_agent(
    container: Container, actor, agent_id: str, permission: Permission
) -> None:
    """资源级鉴权：先取 Agent 拿到 owner，再判权。

    不 import asset 模块的 api/deps——那是跨模块依赖实现；这里只依赖契约。
    """
    asset = await container.assets.get_asset(agent_id, actor.workspace_id)
    if asset is None:
        raise NotFound("Agent", agent_id)
    decision = container.authorizer.decide(
        actor.subject,
        permission,
        ResourceRef(
            kind="asset",
            id=asset.id,
            workspace_id=asset.workspace_id,
            owner_id=asset.owner_id,
        ),
    )
    if not decision.allowed:
        raise PermissionDenied(permission.value, decision.reason)


@router.get("/agents/{agent_id}/instances")
async def list_instances(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeploymentService, Depends(get_deployment_service)],
) -> dict:
    await _authorize_on_agent(container, actor, agent_id, Permission.INSTANCE_READ)
    instances = await service.list_instances(agent_id, actor.workspace_id)
    return list_response([instance_dto(item).model_dump() for item in instances])


@router.post("/agents/{agent_id}/instances")
async def start_instance(
    agent_id: str,
    payload: StartInstanceRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeploymentService, Depends(get_deployment_service)],
) -> dict:
    """启动实例。前提是该通道已绑定版本——没版本可启会明确报错。"""
    from ....contracts.common import Channel

    await _authorize_on_agent(container, actor, agent_id, Permission.INSTANCE_START)
    instance = await service.start(
        asset_id=agent_id,
        channel=Channel(payload.channel),
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
    )
    return ok(action_dto(instance, f"{payload.channel.upper()} 实例已启动").copy())


@router.post("/agents/{agent_id}/instances/{instance_id}/stop")
async def stop_instance(
    agent_id: str,
    instance_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeploymentService, Depends(get_deployment_service)],
) -> dict:
    await _authorize_on_agent(container, actor, agent_id, Permission.INSTANCE_STOP)
    instance = await service.stop(
        instance_id=instance_id, workspace_id=actor.workspace_id, actor_id=actor.user_id
    )
    return ok(action_dto(instance, "实例已停止"))


@router.post("/agents/{agent_id}/instances/{instance_id}/restart")
async def restart_instance(
    agent_id: str,
    instance_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[DeploymentService, Depends(get_deployment_service)],
) -> dict:
    await _authorize_on_agent(container, actor, agent_id, Permission.INSTANCE_START)
    instance = await service.restart(
        instance_id=instance_id, workspace_id=actor.workspace_id, actor_id=actor.user_id
    )
    return ok(action_dto(instance, "实例已重启"))

"""asset 的资源级鉴权依赖。

`asset:version:create` / `asset:credential:*` 对 developer 角色是**资源级**权限：
只能操作自己负责的 Agent。这需要先加载资源，所以不能只靠路由上的 `require()`。

通用部分（会话解析、无资源鉴权）在 `app/api/deps.py`——它是共享 HTTP 设施，
不属于任何业务模块。
"""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends

from ....api.deps import Actor, get_container
from ....container import Container
from ....contracts.errors import PermissionDenied
from ....contracts.identity import Permission, ResourceRef
from ..application.services import AssetService
from ..domain.models import Asset


def get_asset_service(container: Annotated[Container, Depends(get_container)]) -> AssetService:
    return container.assets


async def load_agent(
    agent_id: str,
    actor: Actor,
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> Asset:
    return await assets.get_agent(agent_id, actor.workspace_id)


def require_on_agent(permission: Permission) -> Callable[..., Asset]:
    """加载 Agent 并按资源归属判权，返回该 Agent。"""

    async def dependency(
        container: Annotated[Container, Depends(get_container)],
        actor: Actor,
        agent: Annotated[Asset, Depends(load_agent)],
    ) -> Asset:
        resource = ResourceRef(
            kind="asset",
            id=agent.id,
            workspace_id=agent.workspace_id,
            tenant_id=agent.tenant_id,
            owner_id=agent.owner_id,
        )
        decision = container.authorizer.decide(actor.subject, permission, resource)
        if not decision.allowed:
            raise PermissionDenied(permission.value, decision.reason)
        return agent

    return dependency


__all__ = ["get_asset_service", "load_agent", "require_on_agent"]

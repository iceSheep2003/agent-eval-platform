"""asset 的资源级鉴权依赖。

`asset:version:create` / `asset:credential:*` 对 developer 角色是**资源级**权限：
只能操作自己负责的 Agent。这需要先加载资源，所以不能只靠路由上的 `require()`。

通用部分（会话解析、无资源鉴权）在 `app/api/deps.py`——它是共享 HTTP 设施，
不属于任何业务模块。
"""

# 注意：**不要**加 `from __future__ import annotations`。
# 本模块在 `_require_on` 里用局部变量 `loader` 构造 `Depends(loader)`，
# 惰性求值会把它变成字符串前向引用（ForwardRef），FastAPI 解析不了，
# 于是把 `asset` 当成必填查询参数，接口直接 422。
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


async def load_agent_including_archived(
    agent_id: str,
    actor: Actor,
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> Asset:
    """连**已归档**的 Agent 一起加载。

    恢复接口必须用它：`get_agent` 会过滤软删除，用默认 loader 的话
    「归档了就再也恢复不了」——鉴权依赖自己先把请求 404 掉了。
    """
    return await assets.get_agent(
        agent_id, actor.workspace_id, include_archived=True
    )


async def load_capability(
    asset_id: str,
    actor: Actor,
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> Asset:
    return await assets.get_capability(asset_id, actor.workspace_id)


def _require_on(permission: Permission, loader: Callable[..., Asset]) -> Callable[..., Asset]:
    async def dependency(
        container: Annotated[Container, Depends(get_container)],
        actor: Actor,
        asset: Annotated[Asset, Depends(loader)],
    ) -> Asset:
        resource = ResourceRef(
            kind="asset",
            id=asset.id,
            workspace_id=asset.workspace_id,
            tenant_id=asset.tenant_id,
            owner_id=asset.owner_id,
        )
        decision = container.authorizer.decide(actor.subject, permission, resource)
        if not decision.allowed:
            raise PermissionDenied(permission.value, decision.reason)
        return asset

    return dependency


def require_on_agent(
    permission: Permission, *, include_archived: bool = False
) -> Callable[..., Asset]:
    """加载 Agent 并按资源归属判权，返回该 Agent。

    `include_archived=True` 供恢复接口用——否则软删除的资源连判权的门都进不去。
    """
    return _require_on(
        permission,
        load_agent_including_archived if include_archived else load_agent,
    )


def require_on_capability(permission: Permission) -> Callable[..., Asset]:
    """加载能力资产（Skill / MCP / 知识库）并按资源归属判权。"""
    return _require_on(permission, load_capability)


__all__ = [
    "get_asset_service",
    "load_agent",
    "load_agent_including_archived",
    "load_capability",
    "require_on_agent",
    "require_on_capability",
]

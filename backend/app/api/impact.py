"""影响面：改动一个能力资产会影响谁。

**组合层读模型**：要同时读 asset（谁引用了我）与 delivery（我现在绑在哪些通道），
放进任一模块都会让那个模块反向依赖另一个。

回答的是改之前必须先看的问题：**这个改动会打到多少人**。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..container import Container
from ..contracts.common import Channel
from ..contracts.identity import Permission, ResourceRef
from ..contracts.improvement import ImpactReport
from ..schemas.response import ok
from .deps import Actor, assert_permission, get_container

router = APIRouter(tags=["improvement"])


@router.get("/assets/{asset_id}/impact")
async def asset_impact(
    asset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """改动这个资产会影响谁：直接引用者 + 它们各自的引用关系 + 当前通道指针。"""
    ref = await container.assets.get_asset(asset_id, actor.workspace_id)
    if ref is None:
        from ..contracts.errors import NotFound

        raise NotFound("资产", asset_id)
    assert_permission(
        container,
        actor,
        Permission.ASSET_READ,
        ResourceRef(
            kind="asset",
            id=ref.id,
            workspace_id=ref.workspace_id,
            owner_id=ref.owner_id,
        ),
    )
    report = await container.impact.impact_of(asset_id, actor.workspace_id)
    return ok(
        {
            "asset_id": report.asset_id,
            "direct_consumers": list(report.direct_consumers),
            "transitive_consumers": list(report.transitive_consumers),
            "total_consumers": report.total_consumers,
            "channels": {key: value for key, value in report.channels.items()},
        }
    )

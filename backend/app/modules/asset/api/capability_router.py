"""能力资产（Skill / MCP / 知识库）的 HTTP 路由。

与 `/agents` 分文件，但共用同一个 `AssetService`——四类资产的落库路径完全相同，
差异只在 spec 校验器。**通道与版本是两组接口**：`/channels` 只给指针，
版本详情走 `/versions`，前端不要把两者混成一个字段。
"""

from __future__ import annotations

from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, Query

from ....container import Container
from ....contracts.common import AssetKind, Channel, VersionLifecycle
from ....contracts.errors import DomainError, Errors
from ....contracts.identity import Permission, ResourceRef
from ....schemas.response import list_response, ok
from ....api.deps import Actor, assert_permission, get_container
from ..application.services import AssetService
from ..domain.models import Asset, AssetBinding, AssetVersion
from .deps import get_asset_service, require_on_agent, require_on_capability
from .schemas import (
    CapabilityAssetDTO,
    CapabilityBindingDTO,
    CapabilityChannelDTO,
    CapabilityVersionDTO,
    CreateBindingRequest,
    CreateVersionRequest,
    RegisterCapabilityRequest,
    PromoteCapabilityRequest,
    RollbackCapabilityRequest,
)

router = APIRouter(tags=["capability-assets"])

#: 前端历史值 → 规范枚举值。`knowledge` 是页面上用的字面量，库里恒为 `knowledge_base`。
_KIND_ALIASES = {"knowledge": AssetKind.KNOWLEDGE_BASE}

_CHANNEL_PERMISSION = {
    Channel.TEST: Permission.ASSET_UPDATE,
    Channel.LIVESH: Permission.VERSION_PROMOTE_LIVESH,
    Channel.LIVE: Permission.VERSION_PROMOTE_LIVE,
}


def _skill_only(asset: Asset) -> None:
    if asset.kind is not AssetKind.SKILL:
        raise DomainError(Errors.VALIDATION_FAILED, "只有 Skill 支持版本发布和回退")


def _normalize_kind(raw: str) -> AssetKind:
    if raw in _KIND_ALIASES:
        return _KIND_ALIASES[raw]
    try:
        kind = AssetKind(raw)
    except ValueError as exc:
        raise DomainError(Errors.VALIDATION_FAILED, f"未知的资产类型 {raw!r}") from exc
    if kind is AssetKind.AGENT:
        raise DomainError(Errors.VALIDATION_FAILED, "Agent 走 /agents 接口，不是能力资产")
    return kind


def _version_dto(version: AssetVersion) -> CapabilityVersionDTO:
    return CapabilityVersionDTO(
        id=version.id,
        version_label=version.version_label,
        lifecycle=version.lifecycle.value,
        spec=dict(version.spec),
        created_by=version.created_by,
        created_at=version.created_at,
    )


def _channel_dtos(
    states: dict[Channel, object], versions: Sequence[AssetVersion]
) -> list[CapabilityChannelDTO]:
    labels = {version.id: version.version_label for version in versions}
    return [
        CapabilityChannelDTO(
            channel=channel.value,
            version_id=state.version_id,  # type: ignore[attr-defined]
            version_label=labels.get(state.version_id or ""),  # type: ignore[attr-defined]
            bound_at=state.bound_at,  # type: ignore[attr-defined]
            bound_by=state.bound_by,  # type: ignore[attr-defined]
        )
        for channel, state in states.items()
    ]


async def _asset_dto(
    assets: AssetService, asset: Asset, binding_count: int = 0
) -> CapabilityAssetDTO:
    versions = await assets.list_versions(asset.id, asset.workspace_id)
    states = await assets.channel_states(asset.id, asset.workspace_id)
    latest = versions[0] if versions else None
    return CapabilityAssetDTO(
        id=asset.id,
        kind=asset.kind.value,
        name=asset.name,
        description=asset.description,
        owner=asset.owner_id,
        lifecycle=asset.lifecycle,
        tenant_scope=asset.tenant_scope,
        tenant_id=asset.tenant_id,
        version_count=len(versions),
        binding_count=binding_count,
        created_at=asset.created_at,
        updated_at=latest.created_at if latest else asset.created_at,
        latest_version=_version_dto(latest) if latest else None,
        channels=_channel_dtos(dict(states), versions),
    )


def _binding_dto(
    binding: AssetBinding,
    *,
    consumer_name: str | None = None,
    resolved: AssetVersion | None = None,
) -> CapabilityBindingDTO:
    return CapabilityBindingDTO(
        id=binding.id,
        consumer_asset_id=binding.consumer_asset_id,
        consumer_asset_name=consumer_name,
        consumer_version_id=binding.consumer_version_id,
        provider_asset_id=binding.provider_asset_id,
        provider_kind=binding.provider_kind.value,
        resolve_mode=binding.resolve_mode,
        provider_channel=(
            binding.target_channel().value if binding.target_channel() else None
        ),
        provider_version_id=binding.provider_version_id,
        resolved_version_id=resolved.id if resolved else None,
        resolved_version_label=resolved.version_label if resolved else None,
        tenant_scope=binding.tenant_scope,
        created_at=binding.created_at,
    )


# --------------------------------------------------------------------------- #
# 资源台账
# --------------------------------------------------------------------------- #


@router.post("/assets")
async def register_capability(
    payload: RegisterCapabilityRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_CREATE)
    asset = await assets.register_capability(
        workspace_id=actor.workspace_id,
        owner_id=actor.user_id,
        kind=_normalize_kind(payload.kind),
        name=payload.name,
        description=payload.description,
        spec=payload.spec,
        tenant_id=payload.tenant_id,
    )
    return ok((await _asset_dto(assets, asset)).model_dump())


@router.get("/assets")
async def list_capabilities(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
    kind: Annotated[str | None, Query()] = None,
) -> dict:
    assert_permission(container, actor, Permission.ASSET_READ)
    resolved = _normalize_kind(kind) if kind else None
    found = await assets.list_assets(actor.workspace_id, resolved)
    items = [await _asset_dto(assets, asset) for asset in found]
    return list_response([item.model_dump() for item in items])


@router.get("/assets/{asset_id}")
async def get_capability(
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    bindings = await assets.list_bindings_of_provider(asset.id, asset.workspace_id)
    return ok((await _asset_dto(assets, asset, len(bindings))).model_dump())


@router.get("/assets/{asset_id}/versions")
async def list_capability_versions(
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    versions = await assets.list_versions(asset.id, asset.workspace_id)
    return list_response([_version_dto(version).model_dump() for version in versions])


@router.post("/assets/{asset_id}/versions")
async def create_capability_version(
    payload: CreateVersionRequest,
    asset: Annotated[
        Asset, Depends(require_on_capability(Permission.ASSET_VERSION_CREATE))
    ],
    actor: Actor,
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    version = await assets.create_version(
        asset_id=asset.id,
        workspace_id=asset.workspace_id,
        created_by=actor.user_id,
        spec=payload.spec,
        version_label=payload.version_label,
    )
    return ok(_version_dto(version).model_dump())


def _assert_channel_permission(container: Container, actor: Actor, asset: Asset, channel: Channel) -> None:
    assert_permission(
        container,
        actor,
        _CHANNEL_PERMISSION[channel],
        ResourceRef(
            kind="asset",
            id=asset.id,
            workspace_id=asset.workspace_id,
            tenant_id=asset.tenant_id,
            owner_id=asset.owner_id,
        ),
    )


@router.post("/assets/{asset_id}/versions/{version_id}/promote")
async def promote_skill_version(
    version_id: str,
    payload: PromoteCapabilityRequest,
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_READ))],
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    _skill_only(asset)
    channel = Channel(payload.channel)
    _assert_channel_permission(container, actor, asset, channel)
    version = await assets.get_version(version_id, asset.workspace_id)
    if version is None or version.asset_id != asset.id:
        raise DomainError(Errors.NOT_FOUND, "Skill 版本不存在")
    await assets.set_version_lifecycle(version.id, VersionLifecycle.READY, asset.workspace_id)
    await assets.bind_channel(
        asset_id=asset.id,
        channel=channel,
        version_id=version.id,
        workspace_id=asset.workspace_id,
        actor_id=actor.user_id,
    )
    return ok((await _asset_dto(assets, asset)).model_dump())


@router.post("/assets/{asset_id}/rollback")
async def rollback_skill_version(
    payload: RollbackCapabilityRequest,
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_READ))],
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    _skill_only(asset)
    channel = Channel(payload.channel)
    _assert_channel_permission(container, actor, asset, channel)
    version = await assets.get_version(payload.target_version_id, asset.workspace_id)
    if version is None or version.asset_id != asset.id:
        raise DomainError(Errors.NOT_FOUND, "回退目标版本不存在")
    await assets.bind_channel(
        asset_id=asset.id,
        channel=channel,
        version_id=version.id,
        workspace_id=asset.workspace_id,
        actor_id=actor.user_id,
    )
    return ok((await _asset_dto(assets, asset)).model_dump())


@router.put("/assets/{asset_id}/config")
async def update_capability_config(
    payload: CreateVersionRequest,
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_UPDATE))],
    actor: Actor,
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """更新 MCP/知识库当前配置。

    底层仍冻结修订供评测复现，但管理面不向用户暴露版本与发布通道。
    Skill 必须继续走版本接口。
    """
    if asset.kind is AssetKind.SKILL:
        raise DomainError(Errors.VALIDATION_FAILED, "Skill 配置必须通过创建新版本修改")
    version = await assets.create_version(
        asset_id=asset.id,
        workspace_id=asset.workspace_id,
        created_by=actor.user_id,
        spec=payload.spec,
    )
    await assets.bind_channel(
        asset_id=asset.id,
        channel=Channel.LIVE,
        version_id=version.id,
        workspace_id=asset.workspace_id,
        actor_id=actor.user_id,
    )
    return ok((await _asset_dto(assets, asset)).model_dump())


@router.get("/assets/{asset_id}/channels")
async def get_capability_channels(
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    versions = await assets.list_versions(asset.id, asset.workspace_id)
    states = await assets.channel_states(asset.id, asset.workspace_id)
    return ok([item.model_dump() for item in _channel_dtos(dict(states), versions)])


# --------------------------------------------------------------------------- #
# 引用关系
# --------------------------------------------------------------------------- #


@router.get("/assets/{asset_id}/bindings")
async def list_provider_bindings(
    asset: Annotated[Asset, Depends(require_on_capability(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """影响面：这个能力资产被哪些 Agent 引用。"""
    bindings = await assets.list_bindings_of_provider(asset.id, asset.workspace_id)
    items: list[dict] = []
    for binding in bindings:
        consumer = await assets.get_asset_or_404(binding.consumer_asset_id, asset.workspace_id)
        resolved_id = await assets.resolve_binding_version(binding, asset.workspace_id)
        resolved = (
            await assets.get_version(resolved_id, asset.workspace_id) if resolved_id else None
        )
        items.append(
            _binding_dto(binding, consumer_name=consumer.name, resolved=resolved).model_dump()
        )
    return list_response(items)


@router.get("/agents/{agent_id}/capabilities")
async def list_agent_bindings(
    agent: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """这个 Agent 引用了哪些能力资产。"""
    bindings = await assets.list_bindings_of_consumer(agent.id, agent.workspace_id)
    items = []
    for binding in bindings:
        resolved_id = await assets.resolve_binding_version(binding, agent.workspace_id)
        resolved = (
            await assets.get_version(resolved_id, agent.workspace_id) if resolved_id else None
        )
        items.append(_binding_dto(binding, resolved=resolved).model_dump())
    return list_response(items)


@router.post("/agents/{agent_id}/capabilities")
async def create_agent_binding(
    payload: CreateBindingRequest,
    agent: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_BIND))],
    actor: Actor,
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    binding = await assets.bind_capability(
        workspace_id=agent.workspace_id,
        actor_id=actor.user_id,
        consumer_asset_id=agent.id,
        provider_asset_id=payload.provider_asset_id,
        resolve_mode=payload.resolve_mode,
        provider_channel=Channel(payload.provider_channel) if payload.provider_channel else None,
        provider_version_id=payload.provider_version_id,
        consumer_version_id=payload.consumer_version_id,
        tenant_scope=payload.tenant_scope,
    )
    resolved_id = await assets.resolve_binding_version(binding, agent.workspace_id)
    resolved = await assets.get_version(resolved_id, agent.workspace_id) if resolved_id else None
    return ok(_binding_dto(binding, resolved=resolved).model_dump())


@router.delete("/agents/{agent_id}/capabilities/{binding_id}")
async def delete_agent_binding(
    binding_id: str,
    agent: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_BIND))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    await assets.unbind_capability(binding_id, agent.workspace_id)
    return ok({"id": binding_id, "deleted": True})


__all__ = ["router"]

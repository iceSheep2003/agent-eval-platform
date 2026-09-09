"""asset 的 HTTP 路由。

响应形状对齐前端 `frontend-pro/src/services/eval/index.ts` 与
`examples/customer_support_agent/register.py`——两者已经在调这些路径。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....container import Container
from ....contracts.common import Channel, CredentialKind
from ....contracts.errors import NotFound
from ....contracts.identity import Permission
from ....schemas.response import list_response, ok
from ....api.deps import Actor, assert_permission, get_container
from ..application.services import AssetService
from ..domain.models import Asset, AssetVersion, Credential
from .deps import get_asset_service, require_on_agent
from .schemas import (
    AgentDTO,
    AgentVersionDTO,
    ChannelDTO,
    CreateVersionRequest,
    CredentialDTO,
    IssuedCredentialDTO,
    RegisterAgentRequest,
    SdkKeyRequest,
)

router = APIRouter(tags=["asset"])

#: SDK 事件上报地址。Gateway/Ingest 属机器面，不走 /api 前缀。
INGEST_PATH = "/v1/traces"


async def _agent_dto(assets: AssetService, asset: Asset) -> AgentDTO:
    versions = await assets.list_versions(asset.id, asset.workspace_id)
    channels = await assets.channel_states(asset.id, asset.workspace_id)
    credentials = await assets.list_credentials(asset.workspace_id)
    mine = [item for item in credentials if item.asset_id == asset.id]
    active = [item for item in mine if item.status != "revoked"]
    by_version = {version.id: version.version_label for version in versions}
    return AgentDTO(
        id=asset.id,
        name=asset.name,
        description=asset.description,
        owner=asset.owner_id,
        connect_type=asset.connect_type,
        status=asset.lifecycle,
        environment=asset.connect_type,
        lifecycle=asset.lifecycle,
        version=versions[0].version_label if versions else None,
        test_version=by_version.get(channels[Channel.TEST].version_id or ""),
        livesh_version=by_version.get(channels[Channel.LIVESH].version_id or ""),
        live_version=by_version.get(channels[Channel.LIVE].version_id or ""),
        credential_state="ready" if active else "missing",
    )


def _version_dto(version: AssetVersion) -> AgentVersionDTO:
    return AgentVersionDTO(
        id=version.id,
        version=version.version_label,
        status=version.lifecycle.value,
        source_type=version.spec.get("connect_type"),  # type: ignore[arg-type]
        source_uri=version.spec.get("repository") or version.spec.get("artifact_id"),  # type: ignore[arg-type]
        created_at=version.created_at,
    )


def _credential_dto(credential: Credential) -> CredentialDTO:
    return CredentialDTO(
        id=credential.id,
        name=credential.name,
        prefix=credential.prefix,
        last_four=credential.last_four,
        kind=credential.kind.value,
        agent_id=credential.asset_id,
        tenant_id=credential.tenant_id,
        status=credential.status,
        expires_at=credential.expires_at,
        last_used_at=credential.last_used_at,
        created_at=credential.created_at,
    )


@router.post("/agents")
async def register_agent(
    payload: RegisterAgentRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_CREATE)
    asset = await assets.register_agent(
        workspace_id=actor.workspace_id,
        owner_id=actor.user_id,
        name=payload.name,
        description=payload.description,
        connect_type=payload.connect_type,
        environment=payload.environment,
        source=payload.source,
    )
    return ok((await _agent_dto(assets, asset)).model_dump())


@router.get("/agents")
async def list_agents(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_READ)
    items = [
        (await _agent_dto(assets, asset)).model_dump()
        for asset in await assets.list_agents(actor.workspace_id)
    ]
    return list_response(items)


@router.get("/agents/{agent_id}")
async def get_agent(
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    return ok((await _agent_dto(assets, asset)).model_dump())


@router.get("/agents/{agent_id}/versions")
async def list_versions(
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    versions = await assets.list_versions(asset.id, asset.workspace_id)
    return list_response([_version_dto(version).model_dump() for version in versions])


@router.post("/agents/{agent_id}/versions")
async def create_version(
    payload: CreateVersionRequest,
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_VERSION_CREATE))],
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


@router.get("/agents/{agent_id}/channels")
async def get_channels(
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    states = await assets.channel_states(asset.id, asset.workspace_id)
    versions = {
        version.id: version.version_label
        for version in await assets.list_versions(asset.id, asset.workspace_id)
    }
    return ok(
        [
            ChannelDTO(
                channel=channel.value,
                version_id=state.version_id,
                version=versions.get(state.version_id or ""),
                bound_at=state.bound_at,
                bound_by=state.bound_by,
            ).model_dump()
            for channel, state in states.items()
        ]
    )


@router.post("/agents/{agent_id}/sdk-keys")
async def mint_sdk_key(
    payload: SdkKeyRequest,
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_CREDENTIAL_CREATE))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    issued = await assets.mint_credential(
        workspace_id=asset.workspace_id,
        kind=CredentialKind.TRACE,
        asset_id=asset.id,
        name=payload.name,
        expires_at=payload.expires_at,
    )
    dto = IssuedCredentialDTO(
        id=issued.credential.id,
        key=issued.secret,
        ingest_url=INGEST_PATH,
        prefix=issued.credential.prefix,
        last_four=issued.credential.last_four,
        agent_id=issued.credential.asset_id,
        tenant_id=issued.credential.tenant_id,
        name=issued.credential.name,
        created_at=issued.credential.created_at,
    )
    return ok(dto.model_dump())


@router.get("/agent-credentials")
async def list_credentials(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_READ)
    credentials = await assets.list_credentials(actor.workspace_id)
    return list_response([_credential_dto(item).model_dump() for item in credentials])


@router.post("/agent-credentials/{credential_id}/revoke")
async def revoke_credential(
    credential_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_CREDENTIAL_REVOKE)
    await assets.revoke_credential(credential_id, actor.workspace_id)
    credentials = await assets.list_credentials(actor.workspace_id)
    target = next((item for item in credentials if item.id == credential_id), None)
    if target is None:
        raise NotFound("凭证", credential_id)
    return ok(_credential_dto(target).model_dump())


@router.post("/agent-credentials/{credential_id}/rotate")
async def rotate_credential(
    credential_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_CREDENTIAL_CREATE)
    issued = await assets.rotate_credential(credential_id, actor.workspace_id)
    return ok(
        IssuedCredentialDTO(
            id=issued.credential.id,
            key=issued.secret,
            ingest_url=INGEST_PATH,
            prefix=issued.credential.prefix,
            last_four=issued.credential.last_four,
            agent_id=issued.credential.asset_id,
            tenant_id=issued.credential.tenant_id,
            name=issued.credential.name,
            created_at=issued.credential.created_at,
        ).model_dump()
    )

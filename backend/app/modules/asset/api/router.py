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
from ....contracts.identity import Permission, ResourceRef
from ....schemas.response import list_response, ok
from ....api.deps import Actor, assert_permission, get_container
from ..application.services import AssetService
from ..domain.models import Asset, AssetVersion, Credential
from .deps import get_asset_service, require_on_agent
from .schemas import (
    AgentDTO,
    CreateCredentialRequest,
    AgentVersionDTO,
    BindChannelRequest,
    ChannelDTO,
    CreateVersionRequest,
    CredentialDTO,
    DeploymentKeyDTO,
    DeploymentKeyRequest,
    IssuedCredentialDTO,
    RegisterAgentRequest,
    SdkKeyRequest,
    SecretDTO,
    PutSecretRequest,
    BindSecretRequest,
    SecretBindingDTO,
)

router = APIRouter(tags=["asset"])

#: SDK 事件上报地址。Gateway/Ingest 属机器面，不走 /api 前缀。
INGEST_PATH = "/v1/traces"

#: 按通道调用地址。前端展示平台与外部集成都打这个。
INVOKE_PATH = "/v1/agents/{agent_id}/invoke"

#: 通道 → 绑定该通道所需的权限。复用已有权限点，不新造。
_CHANNEL_PERMISSION = {
    Channel.TEST: Permission.ASSET_UPDATE,
    Channel.LIVESH: Permission.VERSION_PROMOTE_LIVESH,
    Channel.LIVE: Permission.VERSION_PROMOTE_LIVE,
}


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
        channel=credential.channel.value if credential.channel else None,
        scopes=["trace:write"] if credential.kind is CredentialKind.TRACE else ["agent:invoke"],
        agent_ids=[credential.asset_id] if credential.asset_id else [],
        environment=credential.channel.value if credential.channel else None,
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
        owner_id=payload.owner_id or actor.user_id,
        name=payload.name,
        description=payload.description,
        connect_type=payload.connect_type,
        environment=payload.environment,
        source=payload.source,
    )
    return ok((await _agent_dto(assets, asset)).model_dump())


@router.delete("/agents/{agent_id}")
async def archive_agent(
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_ARCHIVE))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """归档（软删除）。历史与证据全部保留——可用 restore 撤销。"""
    await assets.archive_agent(asset.id, asset.workspace_id)
    return ok({"id": asset.id, "archived": True})


@router.post("/agents/{agent_id}/restore")
async def restore_agent(
    asset: Annotated[
        Asset, Depends(require_on_agent(Permission.ASSET_UPDATE, include_archived=True))
    ],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """撤销归档。**必须用 include_archived 的 loader**——默认的会把它 404 掉。"""
    restored = await assets.restore_agent(asset.id, asset.workspace_id)
    return ok((await _agent_dto(assets, restored)).model_dump())


@router.get("/agents/{agent_id}/versions")
async def list_versions(
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    versions = await assets.list_versions(asset.id, asset.workspace_id)
    return list_response([_version_dto(version).model_dump() for version in versions])


@router.get("/agents/{agent_id}/versions/{version_id}/conformance")
async def version_conformance(
    version_id: str,
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
    require_streaming: bool = False,
) -> dict:
    """开发规范验收：这个版本能不能被平台托管。

    静态检查在冻结版本时就跑过了；这里补上**需要真的 import 进来看签名**的那半
    （入口是否接受 `input` / `messages`、是不是异步生成器）。

    `require_streaming=true` 时额外要求是异步生成器——绑 LIVE 前用这个口径查。
    """
    result = await assets.check_conformance(
        version_id, asset.workspace_id, require_streaming=require_streaming
    )
    return ok(
        {
            "passed": result.ok,
            "issues": [
                {"field": item.field, "code": item.code, "message": item.message}
                for item in result.issues
            ],
        }
    )


@router.get("/secrets")
async def list_secrets(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """列出工作区的资源密钥。**永远不返回明文**，只有指纹。"""
    assert_permission(container, actor, Permission.ASSET_READ)
    items = await assets.list_secrets(actor.workspace_id)
    return list_response(
        [
            SecretDTO(
                id=item.id,
                name=item.name,
                fingerprint=item.fingerprint,
                description=item.description,
                created_at=item.created_at,
            ).model_dump()
            for item in items
        ]
    )


@router.post("/secrets")
async def put_secret(
    payload: PutSecretRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """存一把资源密钥（LLM Key / MCP Token）。密文入库，明文只在请求体里出现一次。"""
    assert_permission(container, actor, Permission.ASSET_CREDENTIAL_CREATE)
    secret = await assets.put_secret(
        workspace_id=actor.workspace_id,
        name=payload.name,
        plaintext=payload.value,
        created_by=actor.user_id,
        description=payload.description,
    )
    return ok(
        SecretDTO(
            id=secret.id,
            name=secret.name,
            fingerprint=secret.fingerprint,
            description=secret.description,
            created_at=secret.created_at,
        ).model_dump()
    )


@router.post("/agents/{agent_id}/versions/{version_id}/secrets/{channel}/bind")
async def bind_secret(
    version_id: str,
    channel: Channel,
    payload: BindSecretRequest,
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_CREDENTIAL_CREATE))],
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """把某个版本+通道上的密钥名绑定到一把具体的密钥。

    **TEST 与 LIVE 可以绑不同的密钥**——这是「测试/生产分离」的落点。
    """
    binding = await assets.bind_secret(
        asset_version_id=version_id,
        channel=channel,
        secret_name=payload.secret_name,
        resource_secret_id=payload.resource_secret_id,
        workspace_id=asset.workspace_id,
        bound_by=actor.user_id,
    )
    return ok(
        SecretBindingDTO(
            id=binding.id,
            asset_version_id=binding.asset_version_id,
            channel=binding.channel.value,
            secret_name=binding.secret_name,
            resource_secret_id=binding.resource_secret_id,
            bound_at=binding.created_at,
        ).model_dump()
    )


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


@router.post("/agents/{agent_id}/channels/{channel}/bind")
async def bind_channel(
    channel: Channel,
    payload: BindChannelRequest,
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_READ))],
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """把某个版本挂到通道上。**回退就是重新绑一个旧版本**，不删版本。"""
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
    # `bind_channel` 是 `ChannelWritePort` 的实现，返回 None——绑完回读指针。
    await assets.bind_channel(
        asset_id=asset.id,
        channel=channel,
        version_id=payload.version_id,
        workspace_id=asset.workspace_id,
        actor_id=actor.user_id,
    )
    binding = (await assets.channel_states(asset.id, asset.workspace_id))[channel]
    versions = {
        version.id: version.version_label
        for version in await assets.list_versions(asset.id, asset.workspace_id)
    }
    return ok(
        ChannelDTO(
            channel=binding.channel.value,
            version_id=binding.version_id,
            version=versions.get(binding.version_id or ""),
            bound_at=binding.bound_at,
            bound_by=binding.bound_by,
        ).model_dump()
    )


@router.post("/agents/{agent_id}/deployment-keys")
async def mint_deployment_key(
    payload: DeploymentKeyRequest,
    asset: Annotated[Asset, Depends(require_on_agent(Permission.ASSET_CREDENTIAL_CREATE))],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """签发限定通道的 `evl_` 部署密钥。明文只在本响应里出现一次。"""
    issued = await assets.mint_credential(
        workspace_id=asset.workspace_id,
        kind=CredentialKind.DEPLOY,
        asset_id=asset.id,
        channel=Channel(payload.channel),
        name=payload.name,
        expires_at=payload.expires_at,
    )
    dto = DeploymentKeyDTO(
        id=issued.credential.id,
        key=issued.secret,
        prefix=issued.credential.prefix,
        last_four=issued.credential.last_four,
        agent_id=asset.id,
        channel=payload.channel,
        invoke_url=INVOKE_PATH.format(agent_id=asset.id),
        name=issued.credential.name,
        expires_at=issued.credential.expires_at,
        created_at=issued.credential.created_at,
    )
    return ok(dto.model_dump())


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


@router.get("/agents/{agent_id}/artifacts")
async def list_artifacts(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    assert_permission(container, actor, Permission.ASSET_READ)
    artifacts = await assets.list_artifacts(agent_id, actor.workspace_id)
    return list_response(
        [
            {
                "id": item.id,
                "agent_id": item.asset_id,
                "source_kind": item.source_kind,
                "version": item.version_label,
                "source_ref": item.source_ref,
                "checksum_sha256": item.checksum_sha256,
                "build_status": item.build_status,
                "created_at": item.created_at.isoformat(),
            }
            for item in artifacts
        ]
    )


@router.post("/agent-credentials")
async def create_credential(
    payload: CreateCredentialRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    assets: Annotated[AssetService, Depends(get_asset_service)],
) -> dict:
    """签发机器凭证。明文只在本响应里出现一次。"""
    assert_permission(container, actor, Permission.ASSET_CREDENTIAL_CREATE)
    issued = await assets.mint_credential(
        workspace_id=actor.workspace_id,
        kind=CredentialKind(payload.kind),
        asset_id=payload.agent_id,
        channel=Channel(payload.channel) if payload.channel else None,
        name=payload.name,
        expires_at=payload.expires_at,
    )
    dto = _credential_dto(issued.credential).model_dump()
    dto["secret"] = issued.secret
    dto["scopes"] = payload.scopes or ["trace:write"]
    return ok(dto)


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

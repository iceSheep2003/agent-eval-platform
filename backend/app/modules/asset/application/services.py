"""asset 用例：接入 Agent、冻结版本、签发/吊销凭证。

**凭证明文只在创建响应里出现一次**——库里存 sha256 与末四位，
泄露数据库也拿不到可用凭证。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from ....contracts.asset import AssetRef, AssetVersionRef, CredentialContext
from ....contracts.common import AssetKind, Channel, CredentialKind, VersionLifecycle
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.identity import TenantProvisioningPort
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ....shared.secrets import hash_secret, last_four, new_secret
from ..domain import spec as spec_registry
from ..domain.models import (
    Asset,
    AssetVersion,
    ChannelBinding,
    Credential,
    default_version_label,
)
from ..infrastructure.repositories import (
    AssetRepository,
    AssetVersionRepository,
    ChannelBindingRepository,
    CredentialRepository,
)

#: 每种凭证的密钥前缀。
_PREFIX: Mapping[CredentialKind, str] = {
    CredentialKind.DEPLOY: "evl_",
    CredentialKind.TRACE: "evk_",
    CredentialKind.TENANT_SYNC: "evs_",
}

DEFAULT_TENANT_KEY = "default"
DEFAULT_TENANT_NAME = "默认租户"


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    """签发结果。`secret` 只在这里出现一次，之后任何接口都不再返回。"""

    credential: Credential
    secret: str


class AssetService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        tenants: TenantProvisioningPort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._tenants = tenants

    # -- 查询 ----------------------------------------------------------------

    async def list_agents(self, workspace_id: str) -> Sequence[Asset]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await AssetRepository(uow.session).list_for_workspace(
                    workspace_id, AssetKind.AGENT
                )
            )

    async def get_agent(self, asset_id: str, workspace_id: str) -> Asset:
        async with UnitOfWork(self._db) as uow:
            asset = await AssetRepository(uow.session).get(asset_id, workspace_id)
        if asset is None:
            raise NotFound("Agent", asset_id)
        return asset

    async def get_version_ref(
        self, version_id: str, workspace_id: str
    ) -> AssetVersionRef | None:
        """实现 `contracts.asset.AssetQueryPort`：给执行面提供 entrypoint。"""
        async with UnitOfWork(self._db) as uow:
            version = await AssetVersionRepository(uow.session).get(version_id, workspace_id)
        if version is None:
            return None
        return AssetVersionRef(
            id=version.id,
            asset_id=version.asset_id,
            workspace_id=version.workspace_id,
            version_label=version.version_label,
            lifecycle=version.lifecycle.value,
            entrypoint=version.spec.get("entrypoint"),  # type: ignore[arg-type]
            spec=dict(version.spec),
        )

    async def version_of_channel(
        self, asset_id: str, channel: Channel, workspace_id: str
    ) -> AssetVersionRef | None:
        """通道 → 当前绑定的版本。调用方**不能**自己指定版本。"""
        binding = await self.channel_states(asset_id, workspace_id)
        version_id = binding[channel].version_id
        if version_id is None:
            return None
        return await self.get_version_ref(version_id, workspace_id)

    async def get_asset(self, asset_id: str, workspace_id: str) -> AssetRef | None:
        """实现 `contracts.asset.AssetQueryPort`：只返回投影，不抛错。"""
        async with UnitOfWork(self._db) as uow:
            asset = await AssetRepository(uow.session).get(asset_id, workspace_id)
        if asset is None:
            return None
        return AssetRef(
            id=asset.id,
            workspace_id=asset.workspace_id,
            kind=asset.kind,
            name=asset.name,
            owner_id=asset.owner_id,
            lifecycle=asset.lifecycle,
        )

    async def list_versions(self, asset_id: str, workspace_id: str) -> Sequence[AssetVersion]:
        await self.get_agent(asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await AssetVersionRepository(uow.session).list_for_asset(asset_id))

    async def channel_states(self, asset_id: str, workspace_id: str) -> Mapping[Channel, ChannelBinding]:
        await self.get_agent(asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            bindings = await ChannelBindingRepository(uow.session).list_for_asset(asset_id)
        by_channel = {binding.channel: binding for binding in bindings}
        return {
            channel: by_channel.get(
                channel, ChannelBinding(asset_id, channel, None, None, None)
            )
            for channel in Channel
        }

    async def list_credentials(self, workspace_id: str) -> Sequence[Credential]:
        async with UnitOfWork(self._db) as uow:
            return list(await CredentialRepository(uow.session).list_for_workspace(workspace_id))

    # -- 写入 ----------------------------------------------------------------

    async def register_agent(
        self,
        *,
        workspace_id: str,
        owner_id: str,
        name: str,
        description: str = "",
        connect_type: str = "sdk",
        environment: str | None = None,
        source: Mapping[str, Any] | None = None,
    ) -> Asset:
        """接入 Agent。名称在（工作区, 类型）内唯一，重复接入返回既有资产。

        `source` 携带接入方式特有的字段（github 的 repository/ref、
        package 的 artifact_id/entrypoint），由 `spec/agent.py` 校验。
        """
        spec_body: dict[str, Any] = {"kind": AssetKind.AGENT.value, "connect_type": connect_type}
        if environment:
            spec_body["environment"] = environment
        if source:
            spec_body.update(source)
        result = spec_registry.validator_for(AssetKind.AGENT).validate(spec_body)
        if not result.ok:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                "；".join(result.messages()),
                issues=[issue.code for issue in result.issues],
            )

        async with UnitOfWork(self._db) as uow:
            assets = AssetRepository(uow.session)
            existing = await assets.find_by_name(workspace_id, AssetKind.AGENT, name)
            if existing is not None:
                return existing

            now = self._clock.now()
            asset = Asset(
                id=new_id("asset"),
                workspace_id=workspace_id,
                kind=AssetKind.AGENT,
                name=name,
                description=description,
                owner_id=owner_id,
                lifecycle="draft",
                connect_type=connect_type,  # type: ignore[arg-type]
                tenant_scope="workspace_shared",
                tenant_id=None,
                created_at=now,
            )
            assets.add(asset)

            versions = AssetVersionRepository(uow.session)
            validator = spec_registry.validator_for(AssetKind.AGENT)
            version = AssetVersion(
                id=new_id("version"),
                asset_id=asset.id,
                workspace_id=workspace_id,
                version_label=default_version_label(0),
                spec=spec_body,
                spec_digest=validator.digest(spec_body),
                lifecycle=VersionLifecycle.DRAFT,
                created_by=owner_id,
                created_at=now,
            )
            versions.add(version)
            await uow.session.flush()

            ChannelBindingRepository(uow.session).upsert(
                ChannelBinding(asset.id, Channel.TEST, version.id, now, owner_id),
                workspace_id,
            )
            await uow.commit()
        return asset

    async def create_version(
        self,
        *,
        asset_id: str,
        workspace_id: str,
        created_by: str,
        spec: Mapping[str, object],
        version_label: str | None = None,
    ) -> AssetVersion:
        """冻结一个不可变版本。相同内容重复提交返回既有版本，不产生新行。"""
        asset = await self.get_agent(asset_id, workspace_id)
        validator = spec_registry.validator_for(asset.kind)
        result = validator.validate(spec)
        if not result.ok:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                "；".join(result.messages()),
                issues=[issue.code for issue in result.issues],
            )

        spec_digest = validator.digest(spec)
        async with UnitOfWork(self._db) as uow:
            versions = AssetVersionRepository(uow.session)
            duplicate = await versions.find_by_digest(asset_id, spec_digest)
            if duplicate is not None:
                return duplicate
            existing = await versions.count_for_asset(asset_id)
            version = AssetVersion(
                id=new_id("version"),
                asset_id=asset_id,
                workspace_id=workspace_id,
                version_label=version_label or default_version_label(existing),
                spec=dict(spec),
                spec_digest=spec_digest,
                lifecycle=VersionLifecycle.DRAFT,
                created_by=created_by,
                created_at=self._clock.now(),
            )
            versions.add(version)
            await uow.commit()
        return version

    async def mint_credential(
        self,
        *,
        workspace_id: str,
        kind: CredentialKind,
        asset_id: str | None = None,
        tenant_id: str | None = None,
        channel: Channel | None = None,
        name: str = "default",
        expires_at: datetime | None = None,
    ) -> IssuedCredential:
        """签发机器凭证。

        - SDK 上报密钥（`evk_`）必须绑定到 `(agent, tenant)`
        - 部署凭证（`evl_`）可限定通道，调用方不能拿它去打别的通道
        """
        if asset_id is not None:
            await self.get_agent(asset_id, workspace_id)
        if kind is CredentialKind.TRACE and (asset_id is None or tenant_id is None):
            tenant_id = tenant_id or await self._tenants.ensure_tenant(
                workspace_id, DEFAULT_TENANT_KEY, DEFAULT_TENANT_NAME
            )

        raw = f"{_PREFIX[kind]}{new_secret()}"
        credential = Credential(
            id=new_id("credential"),
            workspace_id=workspace_id,
            asset_id=asset_id,
            tenant_id=tenant_id,
            kind=kind,
            name=name,
            channel=channel,
            prefix=_PREFIX[kind],
            secret_hash=hash_secret(raw),
            last_four=last_four(raw),
            status="active",
            expires_at=expires_at,
            last_used_at=None,
            revoked_at=None,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            CredentialRepository(uow.session).add(credential)
            await uow.commit()
        return IssuedCredential(credential=credential, secret=raw)

    async def rotate_credential(self, credential_id: str, workspace_id: str) -> IssuedCredential:
        """轮换 = 新建一把 + 吊销旧的，不原地改密钥。"""
        async with UnitOfWork(self._db) as uow:
            existing = await CredentialRepository(uow.session).get(credential_id, workspace_id)
        if existing is None:
            raise NotFound("凭证", credential_id)

        issued = await self.mint_credential(
            workspace_id=workspace_id,
            kind=existing.kind,
            asset_id=existing.asset_id,
            tenant_id=existing.tenant_id,
            channel=existing.channel,
            name=existing.name,
            expires_at=existing.expires_at,
        )
        await self.revoke_credential(credential_id, workspace_id)
        return issued

    async def revoke_credential(self, credential_id: str, workspace_id: str) -> None:
        async with UnitOfWork(self._db) as uow:
            repo = CredentialRepository(uow.session)
            if await repo.get(credential_id, workspace_id) is None:
                raise NotFound("凭证", credential_id)
            await repo.revoke(credential_id, self._clock.now())
            await uow.commit()

    async def resolve_credential(self, raw_key: str) -> CredentialContext | None:
        """上报/调用时用密钥换上下文。**asset_id / tenant_id 只认这里的结果。**"""
        if not raw_key:
            return None
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            repo = CredentialRepository(uow.session)
            credential = await repo.get_by_hash(hash_secret(raw_key))
            if credential is None or not credential.is_usable(now):
                return None
            await repo.touch(credential.id, now)
            await uow.commit()
        return CredentialContext(
            credential_id=credential.id,
            workspace_id=credential.workspace_id,
            asset_id=credential.asset_id,
            tenant_id=credential.tenant_id,
            kind=credential.kind,
            name=credential.name,
        )


__all__ = ["AssetService", "IssuedCredential"]

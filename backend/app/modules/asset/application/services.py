"""asset 用例：接入 Agent、冻结版本、签发/吊销凭证。

**凭证明文只在创建响应里出现一次**——库里存 sha256 与末四位，
泄露数据库也拿不到可用凭证。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from ....contracts.asset import (
    AssetRef,
    AssetVersionRef,
    CapabilityAttributionRef,
    CredentialContext,
)
from ....contracts.common import (
    AssetKind,
    Channel,
    CredentialKind,
    ValidationResult,
    VersionLifecycle,
)
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.execution import EntrypointProbePort
from ....contracts.identity import MembershipQueryPort, TenantProvisioningPort
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ....shared.crypto import fingerprint, open_sealed, seal
from ....shared.secrets import hash_secret, last_four, new_secret
from ..domain import spec as spec_registry
from ..domain.models import (
    Artifact,
    Asset,
    AssetBinding,
    AssetVersion,
    ChannelBinding,
    Credential,
    ResolveMode,
    ResourceSecret,
    SecretBinding,
    default_version_label,
)
from ..infrastructure.repositories import (
    AssetBindingRepository,
    ResourceSecretRepository,
    SecretBindingRepository,
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
        members: MembershipQueryPort,
        prober: EntrypointProbePort | None = None,
        master_key: str = "",
    ) -> None:
        self._db = database
        self._clock = clock
        self._tenants = tenants
        self._members = members
        #: 执行面的探针。**可选**——纯离线场景（只建资产不跑）可以不接。
        self._prober = prober
        #: 加解密资源密钥用。为空时相关接口直接报错，不静默降级。
        self._master_key = master_key

    # -- 开发规范验收 --------------------------------------------------------

    async def check_conformance(
        self, version_id: str, workspace_id: str, *, require_streaming: bool = False
    ) -> ValidationResult:
        """对一个已冻结的版本跑**完整的**开发规范验收。

        静态部分在冻结时就查过了；这里补上需要真的把 Agent import 进来看签名的那半。
        返回不合规清单，调用方据此决定是否放行到 LIVE。
        """
        version = await self.get_version(version_id, workspace_id)
        if version is None:
            raise NotFound("版本", version_id)
        conformance = spec_registry.conformance_for(AssetKind.AGENT)
        connect_type = str(version.spec.get("connect_type") or "")
        entrypoint = str(version.spec.get("entrypoint") or "")

        if connect_type == "sdk" or not entrypoint or self._prober is None:
            # 不适用（sdk 接入 / 无 entrypoint / 没接探针）：静态结果为准。
            return conformance.check_spec(version.spec)

        report = self._prober.probe(entrypoint)
        return conformance.check_entrypoint(
            report, connect_type=connect_type, require_streaming=require_streaming
        )

    # -- 查询 ----------------------------------------------------------------

    async def list_agents(self, workspace_id: str) -> Sequence[Asset]:
        return await self.list_assets(workspace_id, AssetKind.AGENT)

    async def get_asset_or_404(self, asset_id: str, workspace_id: str) -> Asset:
        """四类资产通用加载。调用方需要限定 kind 时用 `_require_kind`。"""
        async with UnitOfWork(self._db) as uow:
            asset = await AssetRepository(uow.session).get(asset_id, workspace_id)
        if asset is None:
            raise NotFound("资产", asset_id)
        return asset

    async def get_agent(self, asset_id: str, workspace_id: str) -> Asset:
        """`/agents/{id}` 与资源级鉴权用。**必须是 agent**——否则 Skill 的 id 能打到 Agent 接口上。"""
        return self._require_kind(
            await self.get_asset_or_404(asset_id, workspace_id), AssetKind.AGENT
        )

    async def get_capability(self, asset_id: str, workspace_id: str) -> Asset:
        """加载一个能力资产（Skill / MCP / 知识库）。Agent 走 `get_agent`。"""
        asset = await self.get_asset_or_404(asset_id, workspace_id)
        if not spec_registry.is_capability(asset.kind):
            raise NotFound("能力资产", asset_id)
        return asset

    @staticmethod
    def _require_kind(asset: Asset, kind: AssetKind) -> Asset:
        if asset.kind is not kind:
            raise NotFound(kind.value, asset.id)
        return asset

    async def list_assets(
        self, workspace_id: str, kind: AssetKind | None = None
    ) -> Sequence[Asset]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await AssetRepository(uow.session).list_for_workspace(workspace_id, kind)
            )

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

    async def channel_map(self, asset_id: str, workspace_id: str) -> Mapping[Channel, str | None]:
        states = await self.channel_states(asset_id, workspace_id)
        return {channel: state.version_id for channel, state in states.items()}

    async def version_of_channel(
        self, asset_id: str, channel: Channel, workspace_id: str
    ) -> AssetVersionRef | None:
        """通道 → 当前绑定的版本。调用方**不能**自己指定版本。"""
        binding = await self.channel_states(asset_id, workspace_id)
        version_id = binding[channel].version_id
        if version_id is None:
            return None
        return await self.get_version_ref(version_id, workspace_id)

    async def get_credential_context(
        self, credential_id: str, workspace_id: str
    ) -> CredentialContext | None:
        """按 ID 取凭证上下文。**已撤销/过期的返回 None**——引用有效不等于钥匙有效。"""
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            credential = await CredentialRepository(uow.session).get(credential_id, workspace_id)
        if credential is None or not credential.is_usable(now):
            return None
        return CredentialContext(
            credential_id=credential.id,
            workspace_id=credential.workspace_id,
            asset_id=credential.asset_id,
            tenant_id=credential.tenant_id,
            kind=credential.kind,
            name=credential.name,
            channel=credential.channel,
        )

    async def bind_channel(
        self,
        *,
        asset_id: str,
        channel: Channel,
        version_id: str | None,
        workspace_id: str,
        actor_id: str,
    ) -> None:
        """改通道指针。**不删除任何版本与证据**——回退就是改这里。"""
        if version_id is not None:
            version = await self.get_version_ref(version_id, workspace_id)
            if version is None or version.asset_id != asset_id:
                raise NotFound("版本", version_id)
        async with UnitOfWork(self._db) as uow:
            await ChannelBindingRepository(uow.session).upsert(
                ChannelBinding(asset_id, channel, version_id, self._clock.now(), actor_id),
                workspace_id,
            )
            await uow.commit()

    async def set_version_lifecycle(
        self, version_id: str, lifecycle: VersionLifecycle, workspace_id: str
    ) -> None:
        async with UnitOfWork(self._db) as uow:
            await AssetVersionRepository(uow.session).set_lifecycle(version_id, lifecycle)
            await uow.commit()

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
            description=asset.description,
        )

    async def get_version(self, version_id: str, workspace_id: str) -> AssetVersion | None:
        async with UnitOfWork(self._db) as uow:
            return await AssetVersionRepository(uow.session).get(version_id, workspace_id)

    async def list_versions(self, asset_id: str, workspace_id: str) -> Sequence[AssetVersion]:
        await self.get_asset_or_404(asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await AssetVersionRepository(uow.session).list_for_asset(asset_id))

    async def channel_states(self, asset_id: str, workspace_id: str) -> Mapping[Channel, ChannelBinding]:
        await self.get_asset_or_404(asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            bindings = await ChannelBindingRepository(uow.session).list_for_asset(asset_id)
        by_channel = {binding.channel: binding for binding in bindings}
        return {
            channel: by_channel.get(
                channel, ChannelBinding(asset_id, channel, None, None, None)
            )
            for channel in Channel
        }

    async def list_artifacts(self, asset_id: str, workspace_id: str) -> Sequence[Artifact]:
        await self.get_agent(asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await ArtifactRepository(uow.session).list_for_asset(asset_id))

    async def list_credentials(self, workspace_id: str) -> Sequence[Credential]:
        async with UnitOfWork(self._db) as uow:
            return list(await CredentialRepository(uow.session).list_for_workspace(workspace_id))

    # -- 资源密钥 ------------------------------------------------------------

    async def put_secret(
        self,
        *,
        workspace_id: str,
        name: str,
        plaintext: str,
        created_by: str,
        description: str = "",
    ) -> ResourceSecret:
        """存一把密钥。**同名可以有多把**——轮换就是再存一把，旧的不动。

        这样「回滚」只是把指针改回旧的那把，不需要任何恢复操作。
        """
        if not plaintext.strip():
            raise DomainError(Errors.VALIDATION_FAILED, "密钥明文不能为空")
        if not self._master_key:
            raise DomainError(Errors.VALIDATION_FAILED, "未配置主密钥，无法加密资源密钥")
        secret = ResourceSecret(
            id=new_id("secret"),
            workspace_id=workspace_id,
            name=name,
            ciphertext=seal(self._master_key, plaintext),
            fingerprint=fingerprint(plaintext),
            description=description,
            created_by=created_by,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            ResourceSecretRepository(uow.session).add(secret)
            await uow.commit()
        return secret

    async def list_secrets(self, workspace_id: str) -> Sequence[ResourceSecret]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await ResourceSecretRepository(uow.session).list_for_workspace(workspace_id)
            )

    async def bind_secret(
        self,
        *,
        asset_version_id: str,
        channel: Channel,
        secret_name: str,
        resource_secret_id: str,
        workspace_id: str,
        bound_by: str,
    ) -> SecretBinding:
        """把某个版本 + 通道上的某个密钥名绑定到一把具体的密钥。"""
        async with UnitOfWork(self._db) as uow:
            secrets = ResourceSecretRepository(uow.session)
            secret = await secrets.get(resource_secret_id, workspace_id)
            if secret is None:
                raise NotFound("密钥", resource_secret_id)
            if secret.name != secret_name:
                raise DomainError(
                    Errors.VALIDATION_FAILED,
                    f"密钥名字对不上：引用 {secret_name!r}，拿到的是 {secret.name!r}",
                )
            binding = SecretBinding(
                id=new_id("secret_binding"),
                workspace_id=workspace_id,
                asset_version_id=asset_version_id,
                channel=channel,
                secret_name=secret_name,
                resource_secret_id=resource_secret_id,
                bound_by=bound_by,
                created_at=self._clock.now(),
            )
            await SecretBindingRepository(uow.session).upsert(binding)
            await uow.commit()
        return binding

    async def secret_bindings_of(
        self, asset_version_id: str, workspace_id: str
    ) -> Sequence[SecretBinding]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await SecretBindingRepository(uow.session).list_for_version(
                    asset_version_id
                )
            )

    async def resolve_secrets(
        self, *, asset_version_id: str, channel: Channel, workspace_id: str
    ) -> Mapping[str, str]:
        """解析出**该版本该通道**要注入的密钥明文。

        缺一把就报错——**不能静默少给**：Agent 拿到空密钥却继续跑，
        会以「配置正确但行为诡异」的形式暴露，比直接失败难查得多。
        """
        async with UnitOfWork(self._db) as uow:
            version = await AssetVersionRepository(uow.session).get(
                asset_version_id, workspace_id
            )
            if version is None:
                raise NotFound("版本", asset_version_id)
            bindings = await SecretBindingRepository(uow.session).list_for_version(
                asset_version_id
            )
            by_channel = {
                item.secret_name: item
                for item in bindings
                if item.channel is channel
            }
            secrets = ResourceSecretRepository(uow.session)
            resolved: dict[str, str] = {}
            for item in _as_list(version.spec.get("secrets")):
                if not isinstance(item, Mapping):
                    continue
                secret_name = str(item.get("name") or "")
                if not secret_name:
                    continue
                binding = by_channel.get(secret_name)
                if binding is None:
                    if item.get("required", True):
                        raise DomainError(
                            Errors.CHANNEL_UNBOUND,
                            f"密钥 {secret_name!r} 在 {channel.value} 通道上未绑定",
                            secret_name=secret_name,
                        )
                    continue
                record = await secrets.get(binding.resource_secret_id, workspace_id)
                if record is None:
                    raise NotFound("密钥", binding.resource_secret_id)
                resolved[secret_name] = open_sealed(self._master_key, record.ciphertext)
            return resolved

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
        # 负责人必须是本工作区成员——它决定变更责任，不能收任意字符串
        if not await self._members.is_member(owner_id, workspace_id):
            raise DomainError(
                Errors.VALIDATION_FAILED, "负责人必须是本工作区成员", owner_id=owner_id
            )

        spec_body: dict[str, Any] = {"kind": AssetKind.AGENT.value, "connect_type": connect_type}
        if environment:
            spec_body["environment"] = environment
        if source:
            spec_body.update(source)
        return await self._register(
            workspace_id=workspace_id,
            owner_id=owner_id,
            kind=AssetKind.AGENT,
            name=name,
            description=description,
            spec=spec_body,
            connect_type=connect_type,
        )

    async def register_capability(
        self,
        *,
        workspace_id: str,
        owner_id: str,
        kind: AssetKind,
        name: str,
        description: str = "",
        spec: Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> Asset:
        """接入一个能力资产（Skill / MCP / 知识库）。

        与 Agent 共用「资产 + 首个 draft 版本 + TEST 指针」的落库路径，
        差异只有 spec 校验器与 `tenant_scope`（知识库常按租户隔离）。
        """
        if not spec_registry.is_capability(kind):
            raise DomainError(Errors.VALIDATION_FAILED, f"{kind.value} 不是能力资产类型")
        spec_body: dict[str, Any] = {"kind": kind.value, **(spec or {})}
        return await self._register(
            workspace_id=workspace_id,
            owner_id=owner_id,
            kind=kind,
            name=name,
            description=description,
            spec=spec_body,
            connect_type=None,
            tenant_id=tenant_id,
        )

    async def _register(
        self,
        *,
        workspace_id: str,
        owner_id: str,
        kind: AssetKind,
        name: str,
        description: str,
        spec: Mapping[str, Any],
        connect_type: str | None,
        tenant_id: str | None = None,
    ) -> Asset:
        """四类资产共用的落库路径：校验 spec → 建资产 → 冻结首个版本 → 绑 TEST。"""
        validator = spec_registry.validator_for(kind)
        result = validator.validate(spec)
        if not result.ok:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                "；".join(result.messages()),
                issues=[issue.code for issue in result.issues],
            )

        async with UnitOfWork(self._db) as uow:
            assets = AssetRepository(uow.session)
            existing = await assets.find_by_name(workspace_id, kind, name)
            if existing is not None:
                return existing

            now = self._clock.now()
            asset = Asset(
                id=new_id("asset"),
                workspace_id=workspace_id,
                kind=kind,
                name=name,
                description=description,
                owner_id=owner_id,
                lifecycle="draft",
                connect_type=connect_type,  # type: ignore[arg-type]
                tenant_scope="tenant_bound" if tenant_id else "workspace_shared",
                tenant_id=tenant_id,
                created_at=now,
            )
            assets.add(asset)

            version = AssetVersion(
                id=new_id("version"),
                asset_id=asset.id,
                workspace_id=workspace_id,
                version_label=default_version_label(0),
                spec=dict(spec),
                spec_digest=validator.digest(spec),
                lifecycle=VersionLifecycle.DRAFT,
                created_by=owner_id,
                created_at=now,
            )
            AssetVersionRepository(uow.session).add(version)
            await uow.session.flush()

            await ChannelBindingRepository(uow.session).upsert(
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
        asset = await self.get_asset_or_404(asset_id, workspace_id)
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
            await uow.session.flush()
            # 新冻结的版本就是 TEST 候选——TEST 通道始终指向当前候选，
            # 否则「晋级」连起点都没有。
            await ChannelBindingRepository(uow.session).upsert(
                ChannelBinding(
                    asset_id, Channel.TEST, version.id, self._clock.now(), created_by
                ),
                workspace_id,
            )
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

    # -- 引用关系（Agent → 能力资产）------------------------------------------

    async def bind_capability(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        consumer_asset_id: str,
        provider_asset_id: str,
        resolve_mode: ResolveMode = "channel",
        provider_channel: Channel | None = None,
        provider_version_id: str | None = None,
        consumer_version_id: str | None = None,
        tenant_scope: str = "workspace_shared",
    ) -> AssetBinding:
        """把能力资产引用到 Agent 上。同 `(consumer, provider, consumer_version)` 是 upsert。"""
        consumer = await self.get_agent(consumer_asset_id, workspace_id)
        provider = await self.get_capability(provider_asset_id, workspace_id)

        if resolve_mode not in ("channel", "pinned"):
            raise DomainError(Errors.VALIDATION_FAILED, f"未知的解析方式 {resolve_mode!r}")

        if consumer_version_id is not None:
            version = await self.get_version_ref(consumer_version_id, workspace_id)
            if version is None or version.asset_id != consumer.id:
                raise NotFound("版本", consumer_version_id)

        if resolve_mode == "pinned":
            if provider_version_id is None:
                raise DomainError(Errors.VALIDATION_FAILED, "锁定版本模式必须提供 provider_version_id")
            pinned = await self.get_version_ref(provider_version_id, workspace_id)
            if pinned is None or pinned.asset_id != provider.id:
                raise NotFound("版本", provider_version_id)
            provider_channel = None
        else:
            provider_channel = provider_channel or Channel.LIVE
            provider_version_id = None

        binding = AssetBinding(
            id=new_id("binding"),
            workspace_id=workspace_id,
            consumer_asset_id=consumer.id,
            consumer_version_id=consumer_version_id,
            provider_asset_id=provider.id,
            provider_kind=provider.kind,
            resolve_mode=resolve_mode,
            provider_channel=provider_channel,
            provider_version_id=provider_version_id,
            tenant_scope=tenant_scope,
            created_by=actor_id,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            repo = AssetBindingRepository(uow.session)
            existing = await repo.find(consumer.id, provider.id, consumer_version_id)
            if existing is not None:
                # upsert：同一条引用只保留一行，改配置即覆盖指针语义。
                await repo.delete(existing.id, workspace_id)
            repo.add(binding)
            await uow.commit()
        return binding

    async def unbind_capability(self, binding_id: str, workspace_id: str) -> None:
        async with UnitOfWork(self._db) as uow:
            removed = await AssetBindingRepository(uow.session).delete(binding_id, workspace_id)
            if not removed:
                raise NotFound("引用", binding_id)
            await uow.commit()

    async def list_bindings_of_provider(
        self, provider_asset_id: str, workspace_id: str
    ) -> Sequence[AssetBinding]:
        """影响面：这个能力资产被哪些 Agent 引用。"""
        await self.get_capability(provider_asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(await AssetBindingRepository(uow.session).list_for_provider(provider_asset_id))

    async def list_bindings_of_consumer(
        self, consumer_asset_id: str, workspace_id: str, consumer_version_id: str | None = None
    ) -> Sequence[AssetBinding]:
        await self.get_agent(consumer_asset_id, workspace_id)
        async with UnitOfWork(self._db) as uow:
            return list(
                await AssetBindingRepository(uow.session).list_for_consumer(
                    consumer_asset_id, consumer_version_id
                )
            )

    async def resolve_bindings(
        self,
        consumer_version_id: str,
        workspace_id: str,
        overrides: Mapping[str, str] | None = None,
    ) -> Mapping[str, str]:
        """把 Agent 版本的引用解析成 `provider_asset_id → provider_version_id`。

        **这是「通道 / 锁定」两种模式唯一分支的地方**：下游（Run 冻结、Span 归因）
        看到的是同一个映射。解析不到版本的引用会被跳过——调用方据此决定是失败还是告警。
        """
        async with UnitOfWork(self._db) as uow:
            version = await AssetVersionRepository(uow.session).get(consumer_version_id, workspace_id)
        if version is None:
            raise NotFound("版本", consumer_version_id)

        bindings = await self.list_bindings_of_consumer(
            version.asset_id, workspace_id, consumer_version_id
        )
        # 版本级绑定优先于 Agent 级绑定：先处理版本级，先到先得，后者不覆盖。
        ordered = sorted(bindings, key=lambda item: item.consumer_version_id is None)
        declared = {binding.provider_asset_id for binding in bindings}

        resolved: dict[str, str] = {}
        for binding in ordered:
            if binding.provider_asset_id in resolved:
                continue
            version_id = await self._resolve_one(binding, workspace_id)
            if version_id is not None:
                resolved[binding.provider_asset_id] = version_id

        # 覆盖只对**已声明**的引用生效：不能靠 override 引用一个 Agent 没绑定的资源。
        for provider_asset_id, version_id in (overrides or {}).items():
            if provider_asset_id in declared:
                resolved[provider_asset_id] = version_id
        return resolved

    async def resolve_binding_version(
        self, binding: AssetBinding, workspace_id: str
    ) -> str | None:
        """单条引用的解析结果。列表接口用它把「跟随通道」显示成具体版本。"""
        return await self._resolve_one(binding, workspace_id)

    async def _resolve_one(self, binding: AssetBinding, workspace_id: str) -> str | None:
        if binding.resolve_mode == "pinned":
            return binding.provider_version_id
        channel = binding.target_channel()
        if channel is None:
            return None
        version = await self.version_of_channel(binding.provider_asset_id, channel, workspace_id)
        return version.id if version is not None else None

    async def attribution_targets(
        self, *, workspace_id: str, asset_id: str, version_id: str | None = None
    ) -> Sequence[CapabilityAttributionRef]:
        """实现 `contracts.asset.AttributionTargetPort`：给 ingest 提供归因候选。

        `version_id` 为空 = SDK 上报的生产 Trace，回退到该资产的 LIVE 版本。
        回退也解析不出引用时返回空列表——**归因不上就不归因**，不猜。
        """
        resolved_version_id = version_id
        if resolved_version_id is None:
            live = await self.version_of_channel(asset_id, Channel.LIVE, workspace_id)
            if live is None:
                return ()
            resolved_version_id = live.id

        bindings = await self.list_bindings_of_consumer(asset_id, workspace_id, resolved_version_id)
        targets: list[CapabilityAttributionRef] = []
        seen: set[str] = set()
        for binding in bindings:
            if binding.provider_asset_id in seen:
                continue
            seen.add(binding.provider_asset_id)
            provider_version_id = await self._resolve_one(binding, workspace_id)
            if provider_version_id is None:
                continue
            ref = await self.get_version_ref(provider_version_id, workspace_id)
            if ref is None:
                continue
            names = await self._attribution_names(binding, ref.spec, workspace_id)
            if not names:
                continue
            targets.append(
                CapabilityAttributionRef(
                    asset_id=binding.provider_asset_id,
                    version_id=provider_version_id,
                    kind=binding.provider_kind,
                    names=frozenset(names),
                )
            )
        return targets

    async def consumers_of_resource(
        self, *, workspace_id: str, resource_asset_id: str
    ) -> Sequence[str]:
        """实现 `contracts.asset.AttributionTargetPort`：谁引用了这个能力资产。"""
        bindings = await self.list_bindings_of_provider(resource_asset_id, workspace_id)
        return tuple(dict.fromkeys(binding.consumer_asset_id for binding in bindings))

    async def _attribution_names(
        self, binding: AssetBinding, spec: Mapping[str, Any], workspace_id: str
    ) -> set[str]:
        """按 kind 取「能在 Span 上认出来的标识」。取不到就说明这类资源还归不了因。"""
        if binding.provider_kind is AssetKind.MCP:
            tools = spec.get("tools") or []
            return {
                str(tool.get("name"))
                for tool in tools
                if isinstance(tool, Mapping) and tool.get("name")
            }
        if binding.provider_kind is AssetKind.KNOWLEDGE_BASE:
            index_name = spec.get("index_name")
            return {str(index_name)} if index_name else set()
        if binding.provider_kind is AssetKind.SKILL:
            provider = await self.get_asset_or_404(binding.provider_asset_id, workspace_id)
            return {provider.name}
        return set()

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
            channel=credential.channel,
        )


__all__ = ["AssetService", "IssuedCredential"]


def _as_list(value: object) -> list[object]:
    """spec 里的列表字段，容忍 None 与单值。"""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]

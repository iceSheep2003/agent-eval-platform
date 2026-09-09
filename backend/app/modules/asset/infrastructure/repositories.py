"""asset 仓储：ORM 行 ↔ 领域实体。"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import AssetKind, Channel, CredentialKind, VersionLifecycle
from ....shared.clock import ensure_aware
from ..domain.models import (
    Artifact,
    Asset,
    AssetBinding,
    AssetVersion,
    ChannelBinding,
    Credential,
)
from .tables import (
    ArtifactRow,
    AssetBindingRow,
    AssetRow,
    AssetVersionRow,
    ChannelBindingRow,
    CredentialRow,
)


def _asset(row: AssetRow) -> Asset:
    return Asset(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=AssetKind(row.kind),
        name=row.name,
        description=row.description,
        owner_id=row.owner_id,
        lifecycle=row.lifecycle,  # type: ignore[arg-type]
        connect_type=row.connect_type,  # type: ignore[arg-type]
        tenant_scope=row.tenant_scope,  # type: ignore[arg-type]
        tenant_id=row.tenant_id,
        created_at=ensure_aware(row.created_at),
    )


def _version(row: AssetVersionRow) -> AssetVersion:
    return AssetVersion(
        id=row.id,
        asset_id=row.asset_id,
        workspace_id=row.workspace_id,
        version_label=row.version_label,
        spec=dict(row.spec or {}),
        spec_digest=row.spec_digest,
        lifecycle=VersionLifecycle(row.lifecycle),
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
    )


def _binding(row: ChannelBindingRow) -> ChannelBinding:
    return ChannelBinding(
        asset_id=row.asset_id,
        channel=Channel(row.channel),
        version_id=row.version_id,
        bound_at=ensure_aware(row.bound_at) if row.bound_at else None,
        bound_by=row.bound_by,
    )


def _credential(row: CredentialRow) -> Credential:
    return Credential(
        id=row.id,
        workspace_id=row.workspace_id,
        asset_id=row.asset_id,
        tenant_id=row.tenant_id,
        kind=CredentialKind(row.kind),
        name=row.name,
        channel=Channel(row.channel) if row.channel else None,
        prefix=row.prefix,
        secret_hash=row.secret_hash,
        last_four=row.last_four,
        status=row.status,  # type: ignore[arg-type]
        expires_at=ensure_aware(row.expires_at) if row.expires_at else None,
        last_used_at=ensure_aware(row.last_used_at) if row.last_used_at else None,
        revoked_at=ensure_aware(row.revoked_at) if row.revoked_at else None,
        created_at=ensure_aware(row.created_at),
    )


def _artifact(row: ArtifactRow) -> Artifact:
    return Artifact(
        id=row.id,
        workspace_id=row.workspace_id,
        asset_id=row.asset_id,
        source_kind=row.source_kind,  # type: ignore[arg-type]
        version_label=row.version_label,
        source_ref=row.source_ref,
        checksum_sha256=row.checksum_sha256,
        build_status=row.build_status,  # type: ignore[arg-type]
        created_at=ensure_aware(row.created_at),
    )


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, asset_id: str, workspace_id: str) -> Asset | None:
        stmt = select(AssetRow).where(
            AssetRow.id == asset_id, AssetRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _asset(row) if row else None

    async def find_by_name(self, workspace_id: str, kind: AssetKind, name: str) -> Asset | None:
        stmt = select(AssetRow).where(
            AssetRow.workspace_id == workspace_id,
            AssetRow.kind == kind.value,
            AssetRow.name == name,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _asset(row) if row else None

    async def list_for_workspace(
        self, workspace_id: str, kind: AssetKind | None = None
    ) -> Sequence[Asset]:
        stmt = select(AssetRow).where(AssetRow.workspace_id == workspace_id)
        if kind is not None:
            stmt = stmt.where(AssetRow.kind == kind.value)
        stmt = stmt.order_by(AssetRow.created_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_asset(row) for row in rows]

    def add(self, asset: Asset) -> None:
        self._session.add(
            AssetRow(
                id=asset.id,
                workspace_id=asset.workspace_id,
                kind=asset.kind.value,
                name=asset.name,
                description=asset.description,
                owner_id=asset.owner_id,
                lifecycle=asset.lifecycle,
                connect_type=asset.connect_type,
                tenant_scope=asset.tenant_scope,
                tenant_id=asset.tenant_id,
            )
        )

    async def set_lifecycle(self, asset_id: str, lifecycle: str) -> None:
        await self._session.execute(
            update(AssetRow).where(AssetRow.id == asset_id).values(lifecycle=lifecycle)
        )

    async def set_owner(self, asset_id: str, owner_id: str) -> None:
        await self._session.execute(
            update(AssetRow).where(AssetRow.id == asset_id).values(owner_id=owner_id)
        )


class AssetVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, version_id: str, workspace_id: str) -> AssetVersion | None:
        stmt = select(AssetVersionRow).where(
            AssetVersionRow.id == version_id, AssetVersionRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _version(row) if row else None

    async def list_for_asset(self, asset_id: str) -> Sequence[AssetVersion]:
        stmt = (
            select(AssetVersionRow)
            .where(AssetVersionRow.asset_id == asset_id)
            .order_by(AssetVersionRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_version(row) for row in rows]

    async def count_for_asset(self, asset_id: str) -> int:
        stmt = select(func.count()).select_from(AssetVersionRow).where(
            AssetVersionRow.asset_id == asset_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def find_by_digest(self, asset_id: str, spec_digest: str) -> AssetVersion | None:
        stmt = select(AssetVersionRow).where(
            AssetVersionRow.asset_id == asset_id, AssetVersionRow.spec_digest == spec_digest
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _version(row) if row else None

    def add(self, version: AssetVersion) -> None:
        self._session.add(
            AssetVersionRow(
                id=version.id,
                asset_id=version.asset_id,
                workspace_id=version.workspace_id,
                version_label=version.version_label,
                spec=dict(version.spec),
                spec_digest=version.spec_digest,
                lifecycle=version.lifecycle.value,
                created_by=version.created_by,
            )
        )

    async def set_lifecycle(self, version_id: str, lifecycle: VersionLifecycle) -> None:
        await self._session.execute(
            update(AssetVersionRow)
            .where(AssetVersionRow.id == version_id)
            .values(lifecycle=lifecycle.value)
        )


class ChannelBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_asset(self, asset_id: str) -> Sequence[ChannelBinding]:
        stmt = select(ChannelBindingRow).where(ChannelBindingRow.asset_id == asset_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_binding(row) for row in rows]

    async def get(self, asset_id: str, channel: Channel) -> ChannelBinding | None:
        stmt = select(ChannelBindingRow).where(
            ChannelBindingRow.asset_id == asset_id, ChannelBindingRow.channel == channel.value
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _binding(row) if row else None

    async def upsert(self, binding: ChannelBinding, workspace_id: str) -> None:
        """真正的 upsert：`(asset_id, channel)` 唯一，重复调用只改指针。"""
        stmt = select(ChannelBindingRow).where(
            ChannelBindingRow.asset_id == binding.asset_id,
            ChannelBindingRow.channel == binding.channel.value,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            self._session.add(
                ChannelBindingRow(
                    id=f"{binding.asset_id}:{binding.channel.value}",
                    asset_id=binding.asset_id,
                    workspace_id=workspace_id,
                    channel=binding.channel.value,
                    version_id=binding.version_id,
                    bound_at=binding.bound_at,
                    bound_by=binding.bound_by,
                )
            )
            return
        row.version_id = binding.version_id
        row.bound_at = binding.bound_at
        row.bound_by = binding.bound_by


def _binding_ref(row: AssetBindingRow) -> AssetBinding:
    return AssetBinding(
        id=row.id,
        workspace_id=row.workspace_id,
        consumer_asset_id=row.consumer_asset_id,
        consumer_version_id=row.consumer_version_id,
        provider_asset_id=row.provider_asset_id,
        provider_kind=AssetKind(row.provider_kind),
        resolve_mode=row.resolve_mode,  # type: ignore[arg-type]
        provider_channel=Channel(row.provider_channel) if row.provider_channel else None,
        provider_version_id=row.provider_version_id,
        tenant_scope=row.tenant_scope,
        created_by=row.created_by,
        created_at=ensure_aware(row.created_at),
    )


class AssetBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, binding_id: str, workspace_id: str) -> AssetBinding | None:
        stmt = select(AssetBindingRow).where(
            AssetBindingRow.id == binding_id, AssetBindingRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _binding_ref(row) if row else None

    async def find(
        self,
        consumer_asset_id: str,
        provider_asset_id: str,
        consumer_version_id: str | None,
    ) -> AssetBinding | None:
        stmt = select(AssetBindingRow).where(
            AssetBindingRow.consumer_asset_id == consumer_asset_id,
            AssetBindingRow.provider_asset_id == provider_asset_id,
            AssetBindingRow.consumer_version_id.is_(consumer_version_id)
            if consumer_version_id is None
            else AssetBindingRow.consumer_version_id == consumer_version_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _binding_ref(row) if row else None

    async def list_for_consumer(
        self, consumer_asset_id: str, consumer_version_id: str | None = None
    ) -> Sequence[AssetBinding]:
        """消费方视角：这个 Agent 引用了哪些能力资产。

        Agent 版本级绑定与 Agent 级绑定（`consumer_version_id IS NULL`）都算数——
        后者对所有版本生效，查询时不能漏。
        """
        stmt = select(AssetBindingRow).where(
            AssetBindingRow.consumer_asset_id == consumer_asset_id
        )
        if consumer_version_id is not None:
            stmt = stmt.where(
                (AssetBindingRow.consumer_version_id == consumer_version_id)
                | (AssetBindingRow.consumer_version_id.is_(None))
            )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_binding_ref(row) for row in rows]

    async def list_for_provider(self, provider_asset_id: str) -> Sequence[AssetBinding]:
        """被引用视角：谁在用这个能力资产（影响面查询）。"""
        stmt = (
            select(AssetBindingRow)
            .where(AssetBindingRow.provider_asset_id == provider_asset_id)
            .order_by(AssetBindingRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_binding_ref(row) for row in rows]

    async def count_for_provider(self, provider_asset_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(AssetBindingRow)
            .where(AssetBindingRow.provider_asset_id == provider_asset_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_for_providers(self, provider_asset_ids: Sequence[str]) -> dict[str, int]:
        """列表页用：一次查出多个资源的引用数，避免 N+1。"""
        if not provider_asset_ids:
            return {}
        stmt = (
            select(AssetBindingRow.provider_asset_id, func.count())
            .where(AssetBindingRow.provider_asset_id.in_(list(provider_asset_ids)))
            .group_by(AssetBindingRow.provider_asset_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {provider_id: int(count) for provider_id, count in rows}

    def add(self, binding: AssetBinding) -> None:
        self._session.add(
            AssetBindingRow(
                id=binding.id,
                workspace_id=binding.workspace_id,
                consumer_asset_id=binding.consumer_asset_id,
                consumer_version_id=binding.consumer_version_id,
                provider_asset_id=binding.provider_asset_id,
                provider_kind=binding.provider_kind.value,
                resolve_mode=binding.resolve_mode,
                provider_channel=(
                    binding.provider_channel.value if binding.provider_channel else None
                ),
                provider_version_id=binding.provider_version_id,
                tenant_scope=binding.tenant_scope,
                created_by=binding.created_by,
            )
        )

    async def delete(self, binding_id: str, workspace_id: str) -> bool:
        result = await self._session.execute(
            delete(AssetBindingRow).where(
                AssetBindingRow.id == binding_id,
                AssetBindingRow.workspace_id == workspace_id,
            )
        )
        return bool(result.rowcount)


class CredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, credential_id: str, workspace_id: str) -> Credential | None:
        stmt = select(CredentialRow).where(
            CredentialRow.id == credential_id, CredentialRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _credential(row) if row else None

    async def get_by_hash(self, secret_hash: str) -> Credential | None:
        stmt = select(CredentialRow).where(CredentialRow.secret_hash == secret_hash)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _credential(row) if row else None

    async def list_for_workspace(self, workspace_id: str) -> Sequence[Credential]:
        stmt = (
            select(CredentialRow)
            .where(CredentialRow.workspace_id == workspace_id)
            .order_by(CredentialRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_credential(row) for row in rows]

    async def list_for_asset(self, asset_id: str) -> Sequence[Credential]:
        stmt = select(CredentialRow).where(CredentialRow.asset_id == asset_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_credential(row) for row in rows]

    def add(self, credential: Credential) -> None:
        self._session.add(
            CredentialRow(
                id=credential.id,
                workspace_id=credential.workspace_id,
                asset_id=credential.asset_id,
                tenant_id=credential.tenant_id,
                kind=credential.kind.value,
                name=credential.name,
                channel=credential.channel.value if credential.channel else None,
                prefix=credential.prefix,
                secret_hash=credential.secret_hash,
                last_four=credential.last_four,
                status=credential.status,
                expires_at=credential.expires_at,
            )
        )

    async def revoke(self, credential_id: str, now: datetime) -> None:
        await self._session.execute(
            update(CredentialRow)
            .where(CredentialRow.id == credential_id, CredentialRow.revoked_at.is_(None))
            .values(status="revoked", revoked_at=now)
        )

    async def touch(self, credential_id: str, now: datetime) -> None:
        await self._session.execute(
            update(CredentialRow)
            .where(CredentialRow.id == credential_id)
            .values(last_used_at=now)
        )


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_asset(self, asset_id: str) -> Sequence[Artifact]:
        stmt = (
            select(ArtifactRow)
            .where(ArtifactRow.asset_id == asset_id)
            .order_by(ArtifactRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_artifact(row) for row in rows]

    def add(self, artifact: Artifact) -> None:
        self._session.add(
            ArtifactRow(
                id=artifact.id,
                workspace_id=artifact.workspace_id,
                asset_id=artifact.asset_id,
                source_kind=artifact.source_kind,
                version_label=artifact.version_label,
                source_ref=artifact.source_ref,
                checksum_sha256=artifact.checksum_sha256,
                build_status=artifact.build_status,
            )
        )

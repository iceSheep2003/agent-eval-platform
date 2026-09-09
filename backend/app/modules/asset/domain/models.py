"""资产领域实体。

四类资产（Agent / Skill / MCP / 知识库）共用「身份 + 不可变版本 + 通道指针」骨架；
差异收敛到 `spec/` 下的校验器。M1 只实现 `kind=agent`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping

from ....contracts.common import AssetKind, Channel, CredentialKind, Id, VersionLifecycle

AssetLifecycle = Literal["draft", "active", "archived"]
ConnectType = Literal["sdk", "github", "package"]
TenantScope = Literal["workspace_shared", "tenant_bound"]
CredentialStatus = Literal["active", "expiring", "revoked"]


@dataclass(frozen=True, slots=True)
class Asset:
    """长期存在的业务身份。不是一次运行，也不等于某个代码包。"""

    id: Id
    workspace_id: Id
    kind: AssetKind
    name: str
    description: str
    owner_id: Id
    lifecycle: AssetLifecycle
    connect_type: ConnectType | None
    tenant_scope: TenantScope
    tenant_id: Id | None
    created_at: datetime

    def is_owned_by(self, user_id: Id) -> bool:
        return self.owner_id == user_id


@dataclass(frozen=True, slots=True)
class AssetVersion:
    """不可变实现快照。落库后 `spec` 与 `spec_digest` 不再改动。"""

    id: Id
    asset_id: Id
    workspace_id: Id
    version_label: str
    spec: Mapping[str, Any]
    spec_digest: str
    lifecycle: VersionLifecycle
    created_by: Id
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChannelBinding:
    """指针：某通道当前指向哪个版本。回退就是改这个指针，不删版本。"""

    asset_id: Id
    channel: Channel
    version_id: Id | None
    bound_at: datetime | None
    bound_by: Id | None


@dataclass(frozen=True, slots=True)
class Credential:
    """机器凭证。明文只在创建响应里出现一次，库里只存 sha256 与末四位。"""

    id: Id
    workspace_id: Id
    asset_id: Id | None
    tenant_id: Id | None
    kind: CredentialKind
    name: str
    #: 部署凭证（`evl_`）限定的通道。None = 不限通道（SDK 上报密钥就是 None）。
    channel: Channel | None
    prefix: str
    secret_hash: str
    last_four: str
    status: CredentialStatus
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    def is_usable(self, now: datetime) -> bool:
        if self.status == "revoked" or self.revoked_at is not None:
            return False
        return self.expires_at is None or now < self.expires_at


@dataclass(frozen=True, slots=True)
class Artifact:
    """接入制品（代码包 / Git 构建产物）。"""

    id: Id
    workspace_id: Id
    asset_id: Id
    source_kind: ConnectType
    version_label: str
    source_ref: str
    checksum_sha256: str | None
    build_status: Literal["queued", "building", "ready", "failed"]
    created_at: datetime


def default_version_label(existing: int) -> str:
    """首个版本 0.1.0，之后 0.1.N —— 保持语义化版本且可排序。"""
    return "0.1.0" if existing == 0 else f"0.1.{existing}"

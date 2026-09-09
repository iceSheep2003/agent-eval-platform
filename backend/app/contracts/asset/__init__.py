"""资产与凭证契约。

定义方：消费方（observability 需要把上报密钥换成 `(asset, tenant)`）。
实现方：asset。

只发布当前真正被消费的项（G2/G3）。`AssetQueryPort` 等留到 execution 需要时再加。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from typing import Any, Mapping

from ..common import AssetKind, Channel, CredentialKind, Id


@dataclass(frozen=True, slots=True)
class AssetRef:
    """资产的最小投影。消费方只需要知道「它存在、属于哪个工作区、谁负责」。"""

    id: Id
    workspace_id: Id
    kind: AssetKind
    name: str
    owner_id: Id
    lifecycle: str
    #: 展示用说明。portal 要把它渲染在 Agent 卡片上。
    description: str = ""


@dataclass(frozen=True, slots=True)
class CredentialContext:
    """密钥解析结果。

    **`asset_id` / `tenant_id` 只能来自这里**：上报体里自带的这两个值一律不采信，
    否则任何持有密钥的租户都能伪造别的租户写入。
    """

    credential_id: Id
    workspace_id: Id
    asset_id: Id | None
    tenant_id: Id | None
    kind: CredentialKind
    name: str
    #: 部署密钥限定的通道；未限定时为 None（SDK 上报密钥，或不限通道的部署密钥）。
    channel: Channel | None = None


@runtime_checkable
class CredentialResolverPort(Protocol):
    """由 asset 实现；observability 在 ingest 时调用。"""

    async def resolve_credential(self, raw_key: str) -> CredentialContext | None: ...


@dataclass(frozen=True, slots=True)
class AssetVersionRef:
    """版本投影。`entrypoint` 是执行面启动被测对象所需的最小信息。"""

    id: Id
    asset_id: Id
    workspace_id: Id
    version_label: str
    lifecycle: str
    entrypoint: str | None
    spec: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AssetQueryPort(Protocol):
    """由 asset 实现；evaluation 校验资产存在，execution 取版本启动 Runtime。"""

    async def get_asset(self, asset_id: Id, workspace_id: Id) -> AssetRef | None: ...

    async def get_version_ref(
        self, version_id: Id, workspace_id: Id
    ) -> AssetVersionRef | None: ...

    async def version_of_channel(
        self, asset_id: Id, channel: Channel, workspace_id: Id
    ) -> AssetVersionRef | None: ...

    async def get_credential_context(
        self, credential_id: Id, workspace_id: Id
    ) -> CredentialContext | None:
        """按 ID 取凭证上下文（不校验明文）。已撤销/过期的一律返回 None。

        portal 只存凭证**引用**，所以每次对话前都要用它确认这把钥匙还作数。
        """
        ...


__all__ = [
    "AssetQueryPort",
    "AssetRef",
    "AssetVersionRef",
    "CredentialContext",
    "CredentialResolverPort",
]

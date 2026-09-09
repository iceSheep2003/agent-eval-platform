"""资产与凭证契约。

定义方：消费方（observability 需要把上报密钥换成 `(asset, tenant)`）。
实现方：asset。

只发布当前真正被消费的项（G2/G3）。`AssetQueryPort` 等留到 execution 需要时再加。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from typing import Any, Mapping

from ..common import AssetKind, Channel, CredentialKind, Id, VersionLifecycle


@dataclass(frozen=True, slots=True)
class AssetRef:
    """资产的最小投影。消费方只需要知道「它存在、属于哪个工作区、谁负责」。"""

    id: Id
    workspace_id: Id
    kind: AssetKind
    name: str
    owner_id: Id
    lifecycle: str


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

    async def channel_map(
        self, asset_id: Id, workspace_id: Id
    ) -> Mapping[Channel, Id | None]:
        """三通道 → 当前绑定的版本 ID。晋级/回退据此判断「版本现在在哪」。"""
        ...


__all__ = [
    "AssetQueryPort",
    "ChannelWritePort",
    "AssetRef",
    "AssetVersionRef",
    "CredentialContext",
    "CredentialResolverPort",
]


@runtime_checkable
class ChannelWritePort(Protocol):
    """由 asset 实现；delivery 晋级/回退时改通道指针与版本生命周期。

    晋级 = 改指针 + 写审计行，**不删除任何版本与证据**（需求说明 §9.12）。
    """

    async def bind_channel(
        self,
        *,
        asset_id: Id,
        channel: Channel,
        version_id: Id | None,
        workspace_id: Id,
        actor_id: Id,
    ) -> None: ...

    async def set_version_lifecycle(
        self, version_id: Id, lifecycle: VersionLifecycle, workspace_id: Id
    ) -> None: ...

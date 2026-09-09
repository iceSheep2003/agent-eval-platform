"""资产与凭证契约。

定义方：消费方（observability 需要把上报密钥换成 `(asset, tenant)`）。
实现方：asset。

只发布当前真正被消费的项（G2/G3）。`AssetQueryPort` 等留到 execution 需要时再加。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..common import CredentialKind, Id


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


__all__ = ["CredentialContext", "CredentialResolverPort"]

"""improvement 自己的端口。

**刻意不放进 contracts/**：只被 improvement 消费，按契约生长规则（G2/G3）
属于模块内部。等第二个消费方出现再提升。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from ....contracts.common import Id
from ....contracts.improvement import ImpactReport


@runtime_checkable
class ImpactQueryPort(Protocol):
    """由组合层实现：把「谁引用了我」拼成影响面报告。

    之所以放在组合层：它同时要读 asset（引用关系）与 delivery（通道指针），
    放进任一模块都会让那个模块反向依赖其余模块。
    """

    async def impact_of(self, asset_id: Id, workspace_id: Id) -> ImpactReport: ...


@runtime_checkable
class AssetEvolutionPort(Protocol):
    """由 asset 实现：提案应用时真正落新版本、改可见性。"""

    async def get_asset_ref(self, asset_id: Id, workspace_id: Id) -> Any: ...

    async def create_version_from_proposal(
        self,
        *,
        asset_id: Id,
        workspace_id: Id,
        created_by: Id,
        spec: Mapping[str, Any],
    ) -> Id:
        """按提案的 spec 冻一个新版本，返回版本 ID。"""
        ...

    async def promote_asset(self, asset_id: Id, workspace_id: Id) -> None:
        """把资产提为**公共**（`tenant_scope=workspace_shared`），供他人派生。"""
        ...


__all__ = ["AssetEvolutionPort", "ImpactQueryPort"]

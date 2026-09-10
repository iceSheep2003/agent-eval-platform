"""影响面实现：谁引用了这个资产，以及引用了它的那些 Agent 还引用了什么。

**只读、不写**。放在组合层实现是因为它要同时读 asset 与 delivery——
放进 asset 会让 asset 反向依赖 delivery。
"""

from __future__ import annotations

from typing import Sequence

from ....contracts.asset import AssetQueryPort
from ....contracts.common import Channel, Id
from ....contracts.errors import NotFound
from ....contracts.improvement import ImpactReport


class ImpactService:
    def __init__(self, assets: AssetQueryPort) -> None:
        self._assets = assets

    async def impact_of(self, asset_id: Id, workspace_id: Id) -> ImpactReport:
        asset = await self._assets.get_asset(asset_id, workspace_id)
        if asset is None:
            raise NotFound("资产", asset_id)

        # 只有**能力资产**会被别人引用；Agent 是消费方，没人「引用」它。
        # 这时候返回空报告而不是报错——用户查了就该得到「没人受影响」这个答案。
        if asset.kind.value == "agent":
            return ImpactReport(asset_id=asset_id)

        direct = tuple(await self._assets.consumers_of_asset(asset_id, workspace_id))

        # 间接：引用了这个资产的 Agent，各自又引用了什么。
        # 用户真正想知道的下一层是「我改这个，那些 Agent 的**其他**引用会不会跟着变」，
        # 所以这里收集的是它们引用的**别的**资产。
        transitive: set[Id] = set()
        for consumer_id in direct:
            for provider_id in await self._assets.providers_of_asset(
                consumer_id, workspace_id
            ):
                if provider_id != asset_id:
                    transitive.add(provider_id)

        try:
            channels = await self._assets.channel_map(asset_id, workspace_id)
        except Exception:  # noqa: BLE001 - 没有通道概念的类型就返回空
            channels = {}
        return ImpactReport(
            asset_id=asset_id,
            direct_consumers=direct,
            transitive_consumers=tuple(sorted(transitive)),
            channels={channel.value: version_id for channel, version_id in channels.items()},
        )


__all__ = ["ImpactService"]

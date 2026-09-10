"""运行实例契约。

**发布通道和运行实例是两条独立的生命周期**：

    发布通道  test / liversh / live      晋级、回退        改的是"用哪个版本"
    运行实例  stopped / starting / running / stopping / failed   启动、停止、重启   改的是"跑没跑起来"

冻结版本不等于启动，晋级也不等于启动。生产调用只认运行中的实例。

定义方：消费方（execution 路由调用、delivery 晋级后启动）。
实现方：deployment。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..common import Channel, Id


@dataclass(frozen=True, slots=True)
class InstanceRef:
    """实例的只读投影。`handle_id` / `endpoint` 是调用方重建 RuntimeHandle 所需的全部信息。"""

    id: Id
    workspace_id: Id
    asset_id: Id
    asset_version_id: Id
    channel: Channel
    state: str
    runtime_type: str
    handle_id: str | None = None
    endpoint: str | None = None
    error: str | None = None

    @property
    def is_running(self) -> bool:
        return self.state == "running"


@runtime_checkable
class InstanceLookupPort(Protocol):
    """由 deployment 实现；execution 在网关调用时查「这个通道有没有在跑的实例」。"""

    async def running_for(
        self, asset_id: Id, channel: Channel, workspace_id: Id
    ) -> InstanceRef | None: ...


@runtime_checkable
class InstanceControlPort(Protocol):
    """由 deployment 实现；delivery 在晋级到 LIVE 时自动拉起实例。"""

    async def start(
        self, *, asset_id: Id, channel: Channel, workspace_id: Id, actor_id: Id
    ) -> InstanceRef: ...


__all__ = ["InstanceControlPort", "InstanceLookupPort", "InstanceRef"]

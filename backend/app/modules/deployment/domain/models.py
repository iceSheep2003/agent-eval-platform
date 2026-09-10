"""运行实例：把某个版本的 Agent 真正跑起来。

**和发布通道是两条独立的生命周期**：

    发布通道  test / liversh / live                    改的是「用哪个版本」
    运行实例  stopped / starting / running / ...        改的是「跑没跑起来」

冻结版本不等于启动，晋级也不等于启动——**启动是显式动作**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from ....contracts.common import Channel, Id
from ....shared.state_machine import StateMachine, verify_machine


class InstanceState(StrEnum):
    STOPPED = "stopped"
    #: 拉镜像 / 注入凭证 / 等健康检查
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    #: 起不来或健康检查失败。**不自动重启**——沉默的重试会掩盖真实故障。
    FAILED = "failed"


#: 没有终态：停掉的实例还能再启动，失败的可以重试或清掉。
ALLOWED_TRANSITIONS: Mapping[InstanceState, frozenset[InstanceState]] = {
    InstanceState.STOPPED: frozenset({InstanceState.STARTING}),
    InstanceState.STARTING: frozenset({InstanceState.RUNNING, InstanceState.FAILED}),
    InstanceState.RUNNING: frozenset({InstanceState.STOPPING, InstanceState.FAILED}),
    InstanceState.STOPPING: frozenset({InstanceState.STOPPED, InstanceState.FAILED}),
    # 失败后可以重试，也可以清掉（回到未启动）
    InstanceState.FAILED: frozenset({InstanceState.STARTING, InstanceState.STOPPED}),
}

#: 已经有实例在途或已就绪——此时不允许重复启动。
ACTIVE_STATES: frozenset[InstanceState] = frozenset(
    {InstanceState.STARTING, InstanceState.RUNNING}
)

#: 只有 LIVE 和 LIVESH 有常驻实例。
#: TEST 是候选通道，调试走临时沙箱，不需要（也不该）占着常驻资源。
INSTANCE_CHANNELS: frozenset[Channel] = frozenset({Channel.LIVESH, Channel.LIVE})

verify_machine(InstanceState, ALLOWED_TRANSITIONS)


@dataclass
class InstanceMachine(StateMachine[InstanceState]):
    """实例启停的状态机。"""

    transitions: Mapping[InstanceState, frozenset[InstanceState]] = field(
        default_factory=lambda: ALLOWED_TRANSITIONS
    )
    terminal: frozenset[InstanceState] = field(default_factory=frozenset)
    initial: InstanceState = InstanceState.STOPPED
    state: InstanceState = InstanceState.STOPPED
    history: list[InstanceState] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Instance:
    """一个 (资产, 通道) 上的运行实例。同一通道至多一个。"""

    id: Id
    workspace_id: Id
    asset_id: Id
    asset_version_id: Id
    channel: Channel
    state: InstanceState
    runtime_type: str
    handle_id: str | None
    endpoint: str | None
    error: str | None
    started_at: datetime | None
    stopped_at: datetime | None
    last_health_at: datetime | None
    created_at: datetime

    @property
    def is_running(self) -> bool:
        return self.state is InstanceState.RUNNING


__all__ = [
    "ACTIVE_STATES",
    "ALLOWED_TRANSITIONS",
    "INSTANCE_CHANNELS",
    "Instance",
    "InstanceMachine",
    "InstanceState",
]

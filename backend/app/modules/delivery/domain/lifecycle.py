"""资产治理状态机（声明式）。

通道（TEST / LIVESH / LIVE）是**状态**，晋级是**迁移**。每条迁移声明三件事：

1. 从哪到哪
2. 要过哪些检查（有序，附各自的参数）
3. 需要什么权限、是否要二次确认

这样「加一个通道」「换检查组合」「调阈值」「改谁能操作」都是改**数据**，
不用同时动 domain / application / api / Permission 四个地方。

本模块是**纯数据 + 纯函数**：不碰 IO、不认识数据库。
检查怎么执行在 `application/checks.py`，策略怎么持久化在 infrastructure。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from ....contracts.common import Channel
from ....contracts.identity import Permission


class CheckName(StrEnum):
    """可用的检查项。新增检查 = 在 `application/checks.py` 注册同名实现。"""

    #: 必须有该版本一次「指定阶段 + 已完成 + 门禁通过」的 Run
    PROMOTION_GATE = "promotion_gate"
    #: 影子路由已配置、启用，且指向本次要晋级的版本
    SHADOW_ROUTE = "shadow_route"
    #: 影子指标不劣于基线（成功率、P95 延迟）
    SHADOW_VERIFICATION = "shadow_verification"


#: 通道由低到高。**一个版本可以同时占据多个通道**——晋级到 LIVESH 后它仍绑在 TEST 上
#: （TEST 始终指向最新候选），所以判断「当前在哪个通道」必须取最高的那个。
CHANNELS_ASCENDING: tuple[Channel, ...] = (Channel.TEST, Channel.LIVESH, Channel.LIVE)


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """一条检查声明。`params` 是该项检查自己的可配参数。"""

    name: CheckName
    enabled: bool = True
    params: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name.value, "enabled": self.enabled, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CheckSpec":
        return cls(
            name=CheckName(raw["name"]),
            enabled=bool(raw.get("enabled", True)),
            params=dict(raw.get("params") or {}),
        )


@dataclass(frozen=True, slots=True)
class TransitionRule:
    """一条晋级边。"""

    from_channel: Channel
    to_channel: Channel
    permission: Permission
    requires_reauth: bool = False
    checks: tuple[CheckSpec, ...] = ()

    def enabled_checks(self) -> tuple[CheckSpec, ...]:
        return tuple(spec for spec in self.checks if spec.enabled)

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_channel": self.from_channel.value,
            "to_channel": self.to_channel.value,
            "permission": self.permission.value,
            "requires_reauth": self.requires_reauth,
            "checks": [spec.as_dict() for spec in self.checks],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TransitionRule":
        return cls(
            from_channel=Channel(raw["from_channel"]),
            to_channel=Channel(raw["to_channel"]),
            permission=Permission(raw["permission"]),
            requires_reauth=bool(raw.get("requires_reauth", False)),
            checks=tuple(CheckSpec.from_dict(item) for item in (raw.get("checks") or ())),
        )


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    """一套治理策略。可以有多个——工作区可以覆盖默认值。"""

    transitions: tuple[TransitionRule, ...]

    def rule_for(self, from_channel: Channel, to_channel: Channel) -> TransitionRule | None:
        return next(
            (
                rule
                for rule in self.transitions
                if rule.from_channel is from_channel and rule.to_channel is to_channel
            ),
            None,
        )

    def next_channel(self, current: Channel) -> Channel | None:
        return next(
            (
                rule.to_channel
                for rule in self.transitions
                if rule.from_channel is current
            ),
            None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"transitions": [rule.as_dict() for rule in self.transitions]}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LifecyclePolicy":
        transitions = raw.get("transitions")
        if not transitions:
            raise ValueError("策略必须至少有一条迁移")
        return cls(transitions=tuple(TransitionRule.from_dict(item) for item in transitions))


def current_channel(
    version_id: str, bindings: Mapping[Channel, str | None]
) -> Channel | None:
    """该版本占据的**最高**通道。

    用 `bindings.items()` 的顺序会先撞上 TEST，导致已经到 LIVESH 的版本被判成
    「从 TEST 跳到 LIVE」而拒绝。
    """
    return next(
        (
            channel
            for channel in reversed(CHANNELS_ASCENDING)
            if bindings.get(channel) == version_id
        ),
        None,
    )


#: 默认策略。改这里就等于改全平台的治理规则；工作区可以覆盖。
DEFAULT_POLICY = LifecyclePolicy(
    transitions=(
        TransitionRule(
            from_channel=Channel.TEST,
            to_channel=Channel.LIVESH,
            permission=Permission.VERSION_PROMOTE_LIVESH,
            checks=(
                # 离线验证：门禁过了才进影子；没配影子路由就进 LIVESH 等于没验证
                CheckSpec(CheckName.PROMOTION_GATE, params={"stage": "release"}),
                CheckSpec(CheckName.SHADOW_ROUTE),
            ),
        ),
        TransitionRule(
            from_channel=Channel.LIVESH,
            to_channel=Channel.LIVE,
            permission=Permission.VERSION_PROMOTE_LIVE,
            requires_reauth=True,
            checks=(
                CheckSpec(CheckName.PROMOTION_GATE, params={"stage": "release"}),
                # 影子验证：在真实流量分布下不劣于当前 LIVE 版本
                CheckSpec(
                    CheckName.SHADOW_VERIFICATION,
                    params={
                        "window_days": 7,
                        "min_samples": 30,
                        "success_rate_tolerance": 0.02,
                        "latency_tolerance": 0.20,
                    },
                ),
            ),
        ),
    )
)


__all__ = [
    "CHANNELS_ASCENDING",
    "DEFAULT_POLICY",
    "CheckName",
    "CheckSpec",
    "LifecyclePolicy",
    "TransitionRule",
    "current_channel",
]

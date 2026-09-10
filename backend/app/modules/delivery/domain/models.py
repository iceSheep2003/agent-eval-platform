"""发布控制领域实体。

三条业务底线（需求说明 §9）：

- 版本只能按 `TEST → LIVESH → LIVE` 顺序晋级，不能跳级；
- 门禁未通过**不能**晋级——这是硬约束，权限也绕不过去；
- 回退只改通道指针，**不删除**问题版本与证据。

`LIVESH` 只做影子执行：候选版本的输出永不返回给真实用户。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping

from ....contracts.common import Channel, Id

#: 晋级路径。不在表里的组合一律拒绝。
PROMOTION_PATH: Mapping[Channel, Channel] = {
    Channel.TEST: Channel.LIVESH,
    Channel.LIVESH: Channel.LIVE,
}

#: 目标通道 → 该通道晋级时必须持有的评测阶段。
#: 发布门禁只看 `release` 阶段的结果，开发验证的宽松样本不能拿来放行。
REQUIRED_STAGE: Mapping[Channel, str] = {
    Channel.LIVESH: "release",
    Channel.LIVE: "release",
}

ShadowDirection = Literal["copy_in_only"]


@dataclass(frozen=True, slots=True)
class Promotion:
    """一次晋级记录。不可变审计行。"""

    id: Id
    workspace_id: Id
    asset_id: Id
    version_id: Id
    from_channel: Channel
    to_channel: Channel
    run_id: Id
    gate_passed: bool
    blocked_rules: tuple[str, ...]
    requested_by: Id
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Rollback:
    """一次回退记录。指针改回去，问题版本与证据保留。"""

    id: Id
    workspace_id: Id
    asset_id: Id
    channel: Channel
    from_version_id: Id | None
    to_version_id: Id
    reason: str
    actor_id: Id
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ShadowRoute:
    """影子路由。`sample_rate` 只表示「复制进影子的比例」，不是从 LIVE 切走。"""

    id: Id
    workspace_id: Id
    asset_id: Id
    candidate_version_id: Id
    baseline_version_id: Id | None
    sample_rate: float
    direction: ShadowDirection
    enabled: bool
    created_at: datetime

    def __post_init__(self) -> None:
        if not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("sample_rate 必须在 [0, 1] 内")


def next_channel(current: Channel) -> Channel | None:
    return PROMOTION_PATH.get(current)


def resolve_promotion(
    version_id: Id, bindings: Mapping[Channel, Id | None], target: Channel
) -> Channel:
    """返回该版本当前所在通道；不满足晋级条件时抛 ValueError。

    三条校验：目标必须是下一级、版本必须正绑定在上一级、不能跳级。
    """
    if target not in PROMOTION_PATH.values():
        raise ValueError(f"{target.value} 不是可晋级的通道")

    current = next(
        (channel for channel, bound in bindings.items() if bound == version_id), None
    )
    if current is None:
        raise ValueError(f"版本 {version_id} 当前没有绑定任何通道，不能晋级")

    expected = PROMOTION_PATH.get(current)
    if expected is None:
        raise ValueError(f"{current.value} 已经是最高通道，不能再晋级")
    if expected is not target:
        raise ValueError(
            f"版本只能按 TEST → LIVESH → LIVE 顺序晋级，不能从 {current.value} 直接到 {target.value}"
        )
    return current

"""提案领域逻辑。**纯函数**——状态机与校验都不碰 IO，便于穷举测试。"""

from __future__ import annotations

from ....contracts.improvement import ProposalKind, ProposalStatus

#: 允许的状态迁移。**只进不退**：已批准的不能退回草稿，已应用的更不能改。
_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted"}),
    "submitted": frozenset({"approved", "rejected"}),
    "approved": frozenset({"applied"}),
    "rejected": frozenset(),
    "applied": frozenset(),
}

#: 能应用的状态。**只有 approved 能应用**——不能自己批自己。
_APPLICABLE: frozenset[str] = frozenset({"approved"})


def can_transition(current: ProposalStatus, target: ProposalStatus) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def can_apply(status: ProposalStatus) -> bool:
    return status in _APPLICABLE


def requires_spec(kind: ProposalKind) -> bool:
    """`promote` 只改可见性，不改内容——所以不要求 proposed_spec。"""
    return kind in ("revise", "fork")


__all__ = ["can_apply", "can_transition", "requires_spec"]

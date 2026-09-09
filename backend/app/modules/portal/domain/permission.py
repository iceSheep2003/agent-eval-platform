"""portal 的角色 → 动作矩阵（纯数据 + 纯函数）。

**刻意不复用平台的 `Authorizer`**：那是给平台资源与平台账号用的，
`Subject.kind` / `WorkspaceRole` 都不该知道「展示平台用户」这个概念。
portal 的判定只需要回答两件事：你是不是这个门户的成员、你的门户角色允不允许这个动作。

判定顺序（fail-closed）：
1. 不是成员 → 拒绝（调用方应把它呈现为 404，避免门户枚举）；
2. 角色不在矩阵里 → 拒绝；
3. 动作不在该角色的动作集里 → 拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .models import HubMember, HubRole

#: 门户角色能做的事。当前 owner 与 member 相同——展示平台是只读+对话；
#: 差别留在这里，第一个 owner-only 动作出现时只改这张表。
PORTAL_ROLE_ACTIONS: Mapping[HubRole, frozenset[str]] = {
    "owner": frozenset({"hub:read", "agent:chat"}),
    "member": frozenset({"hub:read", "agent:chat"}),
}

PROJECT_READ = "hub:read"
AGENT_CHAT = "agent:chat"


@dataclass(frozen=True, slots=True)
class PortalDecision:
    allowed: bool
    reason: str | None = None

    @classmethod
    def allow(cls) -> "PortalDecision":
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> "PortalDecision":
        return cls(allowed=False, reason=reason)


def decide_portal(
    membership: HubMember | None, action: str, hub_id: str
) -> PortalDecision:
    """纯函数，无 IO——便于把 portal 的权限矩阵穷举单测。"""
    if membership is None or membership.hub_id != hub_id:
        return PortalDecision.deny("不是该门户的成员")
    actions = PORTAL_ROLE_ACTIONS.get(membership.role, frozenset())
    if action not in actions:
        return PortalDecision.deny(f"门户角色 {membership.role} 不能执行 {action}")
    return PortalDecision.allow()


__all__ = [
    "AGENT_CHAT",
    "PORTAL_ROLE_ACTIONS",
    "PROJECT_READ",
    "PortalDecision",
    "decide_portal",
]

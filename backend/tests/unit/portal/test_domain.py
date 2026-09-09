"""portal 权限矩阵与密码哈希的纯单测（无 IO）。"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.app.modules.portal.domain.models import ProjectMember
from backend.app.modules.portal.domain.permission import (
    AGENT_CHAT,
    PROJECT_READ,
    decide_portal,
)
from backend.app.shared.passwords import hash_password, verify_password

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _member(project_id: str = "pp_1", role: str = "member") -> ProjectMember:
    return ProjectMember(
        id="pm_1",
        project_id=project_id,
        portal_user_id="pu_1",
        role=role,  # type: ignore[arg-type]
        created_at=NOW,
    )


def test_member_can_read_and_chat() -> None:
    assert decide_portal(_member(), PROJECT_READ, "pp_1").allowed
    assert decide_portal(_member(), AGENT_CHAT, "pp_1").allowed


def test_owner_has_same_actions_today() -> None:
    """owner 与 member 当前动作集相同——差别留在矩阵里，等第一个 owner-only 动作出现。"""
    assert decide_portal(_member(role="owner"), AGENT_CHAT, "pp_1").allowed


def test_non_member_is_denied() -> None:
    decision = decide_portal(None, PROJECT_READ, "pp_1")
    assert not decision.allowed


def test_membership_of_another_project_is_denied() -> None:
    """拿着 A 项目的成员身份访问 B 项目必须被拒。"""
    decision = decide_portal(_member(project_id="pp_1"), PROJECT_READ, "pp_2")
    assert not decision.allowed


def test_unknown_action_is_denied() -> None:
    assert not decide_portal(_member(role="owner"), "project:delete", "pp_1").allowed


def test_password_roundtrip() -> None:
    stored = hash_password("portal-pass-123")
    assert stored != "portal-pass-123"
    assert verify_password(stored, "portal-pass-123")
    assert not verify_password(stored, "wrong")
    assert not verify_password(None, "portal-pass-123")

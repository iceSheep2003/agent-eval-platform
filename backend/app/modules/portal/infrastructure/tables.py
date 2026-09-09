"""portal 模块的 ORM 表。表名统一 `portal_` 前缀（表所有权约定）。

**不建到其他模块表的 FK**：`asset_id` / `workspace_id` 都是不透明引用。
跨模块 FK 会让迁移分支互相牵制（`test_migration_ownership` 只允许本模块前缀），
而且 portal 表的存在与否不应该影响 asset 的迁移。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....persistence.base import Base, TimestampMixin


class PortalUserRow(Base, TimestampMixin):
    __tablename__ = "portal_user"
    __table_args__ = (UniqueConstraint("username", name="uq_portal_username"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    #: argon2id；明文不落库
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    #: 连续登录失败次数；成功登录后清零。
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 锁定截止时间；到期后自动可再试（不清零计数，下次失败继续累加）。
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PortalSessionRow(Base, TimestampMixin):
    __tablename__ = "portal_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portal_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: sha256；明文只在 Set-Cookie 里出现一次
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortalProjectRow(Base, TimestampMixin):
    __tablename__ = "portal_project"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_portal_project_slug"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class ProjectMemberRow(Base, TimestampMixin):
    __tablename__ = "portal_member"
    __table_args__ = (
        UniqueConstraint("project_id", "portal_user_id", name="uq_portal_member"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    portal_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: owner | member
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")


class ProjectAgentRow(Base, TimestampMixin):
    __tablename__ = "portal_project_agent"
    __table_args__ = (
        UniqueConstraint("project_id", "asset_id", name="uq_portal_project_asset"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PortalAgentChannelRow(Base, TimestampMixin):
    __tablename__ = "portal_agent_channel"
    __table_args__ = (
        UniqueConstraint("project_agent_id", "channel", name="uq_portal_agent_channel"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 指向 asset_credential 的 `evl_` 凭证；只存引用，不存密钥
    deployment_credential_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

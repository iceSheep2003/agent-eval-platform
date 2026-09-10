"""identity 模块的 ORM 表。

表名统一 `identity_` 前缀——这是「表所有权」约定的物理体现：
其他模块的仓储不得 JOIN 这些表，只能通过 Port 读。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....persistence.base import Base, TimestampMixin


class UserRow(Base, TimestampMixin):
    __tablename__ = "identity_user"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class OrganizationRow(Base, TimestampMixin):
    __tablename__ = "identity_organization"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class OrganizationMembershipRow(Base, TimestampMixin):
    __tablename__ = "identity_organization_membership"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_membership"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_organization.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_user.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    organization: Mapped["OrganizationRow"] = relationship()
    user: Mapped["UserRow"] = relationship()


class InvitationRow(Base, TimestampMixin):
    __tablename__ = "identity_invitation"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_invitation_email"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_organization.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    invited_by: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["OrganizationRow"] = relationship()


class WorkspaceRow(Base, TimestampMixin):
    __tablename__ = "identity_workspace"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: 项目必须属于一个组织
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_organization.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    organization: Mapped["OrganizationRow"] = relationship()


class TenantRow(Base, TimestampMixin):
    __tablename__ = "identity_tenant"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_key", name="uq_tenant_external_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_workspace.id"), nullable=False, index=True
    )
    external_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    workspace: Mapped["WorkspaceRow"] = relationship()


class MembershipRow(Base, TimestampMixin):
    __tablename__ = "identity_membership"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_membership"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_workspace.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_user.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    #: "all" 或 ["tn_xxx", ...]
    tenant_scope: Mapped[Any] = mapped_column(JSON, nullable=False, default="all")

    # 声明关系不是为了导航，而是让 SQLAlchemy 知道 flush 的依赖顺序——
    # 否则同一事务里先插 membership 再插 workspace 会撞外键。
    workspace: Mapped["WorkspaceRow"] = relationship()
    user: Mapped["UserRow"] = relationship()


class SessionRow(Base, TimestampMixin):
    __tablename__ = "identity_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_user.id"), nullable=False, index=True
    )
    #: 只存 sha256，明文只在 Set-Cookie 时出现一次
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    auth_method: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["UserRow"] = relationship()

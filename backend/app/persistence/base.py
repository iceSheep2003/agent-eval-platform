"""ORM 基类与通用列。

**表所有权**：每张表属于一个模块，命名前缀即模块名（`identity_*`、`asset_*`、`run_*`…）。
其他模块只能通过 Port 读，禁止跨模块 JOIN。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """所有 ORM 表的基类。迁移脚本通过 `Base.metadata` 生成。"""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class WorkspaceScopedMixin:
    """工作区隔离的第一道防线：所有业务表都带 workspace_id 并建索引。

    仓储基类据此强制注入过滤，应用层守卫再做二次校验。
    """

    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

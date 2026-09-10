"""memory 模块的 ORM 表。表名统一 `memory_` 前缀（表所有权约定）。

**分区是这张表的核心**：`(agent_version_id, tenant_id, thread_id, scope)` 决定
一条记忆属于谁。少了任何一维都会串——版本之间、租户之间、会话之间。
"""

from __future__ import annotations

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....persistence.base import Base, TimestampMixin


class MemoryEntryRow(Base, TimestampMixin):
    """一条记忆。轮次与事实共用一张表，靠 `kind` 区分。

    `thread_id` 与 `tenant_id` 都允许为空——`thread_id` 为空表示「该版本该租户
    下的唯一短期记忆」，`tenant_id` 为空表示工作区级共享。
    """

    __tablename__ = "memory_entry"
    __table_args__ = (
        UniqueConstraint(
            "agent_version_id",
            "tenant_id",
            "thread_id",
            "scope",
            "kind",
            "seq",
            name="uq_memory_entry",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: 空 = 工作区级
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: 空 = 该版本该租户的唯一短期记忆
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    #: turn | fact
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: kind=turn 时单调递增，保证顺序；kind=fact 时用于稳定排序。
    seq: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content: Mapped[str] = mapped_column(String(8192), nullable=False, default="")
    #: kind=fact 时的键；turn 为空。
    fact_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    #: 检索用的分词结果（中文按字切，见 domain/recall.py）。
    terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

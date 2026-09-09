"""dataset 模块的 ORM 表。表名统一 `dataset_` 前缀。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....persistence.base import Base, TimestampMixin


class DatasetRow(Base, TimestampMixin):
    __tablename__ = "dataset_dataset"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_dataset_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    task_shape: Mapped[str] = mapped_column(String(24), nullable=False)
    #: 允许在哪些生命周期阶段被引用；策略绑定时会校验
    stages: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="qa/v1")
    source: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class DatasetVersionRow(Base, TimestampMixin):
    __tablename__ = "dataset_version"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_label", name="uq_dataset_version_label"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_dataset.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset: Mapped["DatasetRow"] = relationship()


class DatasetItemRow(Base, TimestampMixin):
    __tablename__ = "dataset_item"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "content_digest", name="uq_item_digest"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_version.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 保真原始样本
    raw: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    #: 公开部分，唯一允许进 Agent 输入
    task: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    #: 私有部分，只给评估器
    private: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    validation: Mapped[str] = mapped_column(String(16), nullable=False, default="valid")
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    version: Mapped["DatasetVersionRow"] = relationship()


class ImportSessionRow(Base, TimestampMixin):
    __tablename__ = "dataset_import_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("dataset_dataset.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issues: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    dataset: Mapped["DatasetRow"] = relationship()

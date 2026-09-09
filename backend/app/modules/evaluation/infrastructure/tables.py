"""evaluation 模块的 ORM 表。表名统一 `evaluation_` 前缀。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....persistence.base import Base, TimestampMixin


class CapabilityRow(Base, TimestampMixin):
    __tablename__ = "evaluation_capability"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_capability_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DimensionRow(Base, TimestampMixin):
    __tablename__ = "evaluation_dimension"
    __table_args__ = (
        UniqueConstraint("capability_id", "name", name="uq_dimension_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_capability.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    #: 权重与门槛都是 0–1 的比率（口径统一，展示层负责乘 100）
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    evaluator_names: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    #: 当前观测值，由评测结果回填；没有结果时为 NULL
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    capability: Mapped["CapabilityRow"] = relationship()


class TemplateRow(Base, TimestampMixin):
    __tablename__ = "evaluation_template"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_template_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluators: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    dimension_ids: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    gates: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)


class BindingRow(Base, TimestampMixin):
    __tablename__ = "evaluation_binding"
    __table_args__ = (
        UniqueConstraint("template_id", "asset_id", name="uq_binding"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_template.id"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    template: Mapped["TemplateRow"] = relationship()

"""observability 模块的 ORM 表。表名统一 `obs_` 前缀。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....persistence.base import Base, TimestampMixin


class TraceRow(Base, TimestampMixin):
    __tablename__ = "obs_trace"
    __table_args__ = (
        # SDK 幂等：同一 Agent 下同一个 external_trace_id 只落一行
        UniqueConstraint("asset_id", "external_trace_id", name="uq_trace_external"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_version_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trial_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    span_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested_via: Mapped[str] = mapped_column(String(16), nullable=False, default="sdk")
    #: 父调用的 trace id。编排产生的调用树靠它连通——整棵子树的总成本、
    #: 总成功率都从这一列聚合出来。
    parent_invocation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    #: 这条 Trace 的补充事实（如用了哪把密钥的**指纹**、记忆片的分区）。
    #: 存指纹不存值——「用的哪一把」可追溯，「钥匙是什么」不外扩。
    metadata_json: Mapped[Any] = mapped_column("metadata", JSON, nullable=False, default=dict)


class SpanRow(Base, TimestampMixin):
    __tablename__ = "obs_span"
    __table_args__ = (
        UniqueConstraint("trace_id", "external_span_id", name="uq_span_external"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: SDK 侧 span_id，用于还原父子关系
    external_span_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("obs_trace.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    attributes: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    #: 归因：这个 Span 属于哪个能力资产版本（N3）。归不上就是 NULL，不猜。
    resource_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource_attribution: Mapped[str | None] = mapped_column(String(16), nullable=True)

    trace: Mapped["TraceRow"] = relationship()

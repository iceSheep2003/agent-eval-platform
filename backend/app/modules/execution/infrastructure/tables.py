"""execution 模块的 ORM 表。表名统一 `run_` 前缀。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....persistence.base import Base, TimestampMixin


class RunRow(Base, TimestampMixin):
    __tablename__ = "run_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 冻结的策略快照；策略后续改动不影响历史 Run
    template_snapshot: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    tenant_scope: Mapped[Any] = mapped_column(JSON, nullable=False, default="all")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="provisioning")
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_budget_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    total_trials: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrialRow(Base, TimestampMixin):
    __tablename__ = "run_trial"
    __table_args__ = (
        # 同一 Run 下同一采样点同一次尝试只落一行——重试产生新 attempt_no
        UniqueConstraint("run_id", "sample_id", "attempt_no", name="uq_trial_attempt"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("run_run.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 执行侧：pending / running / succeeded / failed / timed_out / cancelled
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    #: 质量侧：pass / fail / skip / error；与执行状态正交
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["RunRow"] = relationship()


class ScoreRow(Base, TimestampMixin):
    __tablename__ = "run_score"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trial_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("run_trial.id"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)


class RunResultRow(Base, TimestampMixin):
    """Run 终态固化结果。一行一个 Run，写入后不再更新。"""

    __tablename__ = "run_result"

    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("run_run.id"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

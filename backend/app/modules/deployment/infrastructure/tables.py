"""deployment 模块的 ORM 表。表名统一 `deployment_` 前缀。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....persistence.base import Base, TimestampMixin


class InstanceRow(Base, TimestampMixin):
    """一个 (资产, 通道) 上的运行实例。同一通道至多一个。"""

    __tablename__ = "deployment_instance"
    __table_args__ = (
        UniqueConstraint("asset_id", "channel", name="uq_instance_channel"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: 实例跑的是哪个版本——启动时从通道指针解析并**冻结**在实例上
    asset_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="stopped", index=True)
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    #: 执行面句柄。重建 RuntimeHandle 只需它 + endpoint + asset_version_id
    handle_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 连续探活失败次数。成功一次即清零。
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_health_error: Mapped[str | None] = mapped_column(Text, nullable=True)

"""delivery 模块的 ORM 表。表名统一 `delivery_` 前缀。

三张表都是**不可变审计行**：晋级、回退、影子配置的每一次变更都留痕。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....persistence.base import Base, TimestampMixin


class PromotionRow(Base, TimestampMixin):
    __tablename__ = "delivery_promotion"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    to_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 门禁依据：哪次 Run 的判定放行了这次晋级
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_rules: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)


class RollbackRow(Base, TimestampMixin):
    __tablename__ = "delivery_rollback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    from_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)


class ShadowRouteRow(Base, TimestampMixin):
    __tablename__ = "delivery_shadow_route"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: 只存 ID，**不建外键**——跨模块引用对方的表违反 R3，且会让按模块过滤的
    #: autogenerate 解析不到目标表。存在性由 asset 的 Port 保证。
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    #: 固定为 copy_in_only：只把流量复制进影子，候选输出永不返回给真实用户
    direction: Mapped[str] = mapped_column(String(24), nullable=False, default="copy_in_only")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LifecyclePolicyRow(Base, TimestampMixin):
    """工作区级的治理策略覆盖。没有行 = 用平台默认策略。"""

    __tablename__ = "delivery_lifecycle_policy"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)

"""improvement 模块的表。前缀 `improvement_`。

提案是**只追加的证据链**：状态可以推进（draft → submitted → approved → applied），
但已经写下的证据与理由不改。批注（review_note）是追加的，不是覆盖的。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....persistence.base import Base, TimestampMixin


class ProposalRow(Base, TimestampMixin):
    __tablename__ = "improvement_proposal"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: revise | fork | promote
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: draft | submitted | approved | rejected | applied
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    target_asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposed_spec: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    #: 证据列表。**必须有**——没有证据的提案无法判断该不该批。
    evidence: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applied_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

"""improvement 的 HTTP DTO。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceDTO(BaseModel):
    kind: Literal["failed_trace", "metric_regression", "manual"]
    ref: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=512)
    metrics: dict[str, Any] = Field(default_factory=dict)


class SubmitProposalRequest(BaseModel):
    kind: Literal["revise", "fork", "promote"]
    target_asset_id: str = Field(min_length=1, max_length=64)
    #: `revise` / `fork` 必填；`promote` 不改内容，留空。
    proposed_spec: dict[str, Any] = Field(default_factory=dict)
    base_version_id: str | None = None
    #: **必须有**——没有证据的提案不予受理。
    evidence: list[EvidenceDTO] = Field(min_length=1)
    rationale: str = Field(default="", max_length=2048)


class ReviewProposalRequest(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=2048)


class ForkAssetRequest(BaseModel):
    source_asset_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)

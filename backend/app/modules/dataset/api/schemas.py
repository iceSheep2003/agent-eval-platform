"""dataset 的 HTTP DTO。

`kind` 是给旧前端（`EvalDataset.kind`）的兼容别名，等于 `origin`；
四维度模型以 `origin` / `purpose` / `task_shape` / `stages` 为准。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ....contracts.common import (
    DatasetOrigin,
    DatasetPurpose,
    EvaluationStage,
    TaskProtocol,
    TaskShape,
)


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    origin: DatasetOrigin = DatasetOrigin.MANUAL
    purpose: DatasetPurpose = DatasetPurpose.CAPABILITY
    task_shape: TaskShape = TaskShape.SINGLE_TURN
    stages: list[EvaluationStage] | None = None
    protocol: TaskProtocol = TaskProtocol.QA
    source: dict[str, Any] | None = None


class ReviewItemRequest(BaseModel):
    validation: Literal["valid", "needs_review", "invalid"]


class DatasetDTO(BaseModel):
    id: str
    name: str
    description: str
    owner: str
    kind: str  # = origin，兼容旧前端
    origin: str
    purpose: str
    task_shape: str
    stages: list[str]
    protocol: str
    source: dict[str, Any] | None = None
    version: str | None = None
    item_count: int = 0
    status: str = "draft"


class DatasetVersionDTO(BaseModel):
    id: str
    version: str
    lifecycle: str
    item_count: int
    content_digest: str
    is_current: bool = False
    created_at: datetime
    finalized_at: datetime | None = None


class ImportSessionDTO(BaseModel):
    id: str
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    duplicate_rows: int
    invalid_rows: int
    issues: list[dict[str, Any]] = []
    version_id: str | None = None
    created_at: datetime


class DatasetItemDTO(BaseModel):
    id: str
    index: int
    validation: str
    tenant_id: str | None = None
    task: dict[str, Any]
    private: dict[str, Any] | None = None
    raw: dict[str, Any]

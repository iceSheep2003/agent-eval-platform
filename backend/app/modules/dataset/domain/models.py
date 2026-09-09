"""数据集领域实体。

三段式样本（docs/backend-dataset.md §5）：
`raw` 保真原始样本、`task` 唯一允许进 Agent 的部分、`private` 只给评估器。

**P0 不实现回流**（§6/§7）：表里暂不带 lineage / review 的挖掘字段，
等实现时用本模块自己的迁移补。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

from ....contracts.common import (
    DatasetOrigin,
    DatasetPurpose,
    EvaluationStage,
    Id,
    ItemValidation,
    JsonValue,
    TaskProtocol,
    TaskShape,
)
from ....shared.canonical_json import digest as _digest

VersionLifecycle = Literal["draft", "finalized", "archived"]
ImportStatus = Literal["pending", "validated", "applied", "failed"]


@dataclass(frozen=True, slots=True)
class DatasetSource:
    """来源与适配信息。benchmark 数据集必须能回答「原始是哪一版、用哪个适配器」。"""

    benchmark_id: str | None = None
    benchmark_version: str | None = None
    adapter: str | None = None
    adapter_version: str | None = None
    split: str | None = None
    upstream_uri: str | None = None
    license: str | None = None

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "split": self.split,
            "upstream_uri": self.upstream_uri,
            "license": self.license,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "DatasetSource | None":
        if not raw:
            return None
        return cls(
            benchmark_id=raw.get("benchmark_id"),
            benchmark_version=raw.get("benchmark_version"),
            adapter=raw.get("adapter"),
            adapter_version=raw.get("adapter_version"),
            split=raw.get("split"),
            upstream_uri=raw.get("upstream_uri"),
            license=raw.get("license"),
        )


@dataclass(frozen=True, slots=True)
class TaskLimits:
    max_steps: int | None = None
    timeout_seconds: float | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str = ""
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """**唯一允许进入 Agent 输入的部分。**"""

    instruction: str
    protocol: TaskProtocol = TaskProtocol.QA
    context: Mapping[str, JsonValue] = field(default_factory=dict)
    tools: tuple[ToolSpec, ...] = ()
    limits: TaskLimits | None = None

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "instruction": self.instruction,
            "protocol": self.protocol.value,
            "context": dict(self.context),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                }
                for tool in self.tools
            ],
            "limits": (
                {
                    "max_steps": self.limits.max_steps,
                    "timeout_seconds": self.limits.timeout_seconds,
                    "max_cost_usd": self.limits.max_cost_usd,
                }
                if self.limits
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PrivateTaskContext:
    """**永不进入 Agent 输入。** M3 要用契约测试断言这一点。"""

    expected_output: JsonValue | None = None
    expected_actions: tuple[Mapping[str, JsonValue], ...] = ()
    hidden_state: Mapping[str, JsonValue] = field(default_factory=dict)
    verifier: str | None = None

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "expected_output": self.expected_output,
            "expected_actions": [dict(item) for item in self.expected_actions],
            "hidden_state": dict(self.hidden_state),
            "verifier": self.verifier,
        }


@dataclass(frozen=True, slots=True)
class Dataset:
    id: Id
    workspace_id: Id
    name: str
    description: str
    owner_id: Id
    origin: DatasetOrigin
    purpose: DatasetPurpose
    task_shape: TaskShape
    stages: tuple[EvaluationStage, ...]
    protocol: TaskProtocol
    source: DatasetSource | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    id: Id
    dataset_id: Id
    workspace_id: Id
    version_label: str
    lifecycle: VersionLifecycle
    item_count: int
    #: 内容摘要——同样的样本集得到同样的摘要，便于判断「这一版到底改了什么」
    content_digest: str
    created_by: Id
    created_at: datetime
    finalized_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DatasetItem:
    id: Id
    dataset_version_id: Id
    workspace_id: Id
    tenant_id: Id | None
    index: int
    raw: Mapping[str, Any]
    task: TaskSpec
    private: PrivateTaskContext | None
    validation: ItemValidation
    content_digest: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ImportIssue:
    row: int
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ImportSession:
    id: Id
    dataset_id: Id
    workspace_id: Id
    filename: str
    status: ImportStatus
    total_rows: int
    valid_rows: int
    duplicate_rows: int
    invalid_rows: int
    issues: tuple[ImportIssue, ...]
    created_by: Id
    created_at: datetime
    applied_version_id: Id | None = None


def item_digest(task: TaskSpec, private: PrivateTaskContext | None) -> str:
    """样本内容摘要：只算 task + private，不算 raw（raw 允许带无关元数据）。"""
    return _digest({"task": task.as_dict(), "private": private.as_dict() if private else None})


def row_digest(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_digest(dict(row)).encode("utf-8")).hexdigest()[:32]

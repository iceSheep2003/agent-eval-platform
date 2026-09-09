"""Stable data-only interop types for a future Benchmark Harness.

The SDK deliberately does not start browsers, containers, terminals, or remote
Benchmark environments. These types let an eventual Harness and an Agent share
the same public task/observation/action vocabulary without importing a
Benchmark implementation into the Agent package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

from .models import TraceEvent, utc_now


ActionKind = Literal["tool_call", "message", "file_operation", "submit", "finish", "abort"]


@dataclass(frozen=True)
class PublicTaskSpec:
    task_id: str
    benchmark_id: str
    benchmark_version: str
    adapter_version: str
    instruction: str
    goal: str | None = None
    visible_context: Mapping[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[Mapping[str, Any], ...] = ()
    limits: Mapping[str, Any] = field(default_factory=dict)
    policy: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "adapter_version": self.adapter_version,
            "instruction": self.instruction,
            "goal": self.goal,
            "visible_context": dict(self.visible_context),
            "allowed_actions": [dict(item) for item in self.allowed_actions],
            "limits": dict(self.limits),
            "policy": dict(self.policy),
        }


@dataclass(frozen=True)
class PrivateTaskContext:
    """Verifier-side context; never included in ``PublicTaskSpec.to_dict``."""

    hidden_ground_truth: Mapping[str, Any] = field(default_factory=dict)
    private_credentials: Mapping[str, Any] = field(default_factory=dict)
    verifier_config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    observation_id: str
    session_id: str
    type: str
    source: str
    content: Any | None = None
    artifact_ref: str | None = None
    is_error: bool = False
    timestamp: datetime = field(default_factory=utc_now)
    visibility: Literal["public", "internal"] = "public"
    reply_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "session_id": self.session_id,
            "type": self.type,
            "source": self.source,
            "content": self.content,
            "artifact_ref": self.artifact_ref,
            "is_error": self.is_error,
            "timestamp": self.timestamp.isoformat(),
            "visibility": self.visibility,
            "reply_to": self.reply_to,
        }


@dataclass(frozen=True)
class Action:
    id: str
    kind: ActionKind
    name: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.kind in {"tool_call", "file_operation"} and not self.name:
            raise ValueError(f"{self.kind} requires name")
        if self.kind in {"finish", "abort"} and self.name is not None:
            raise ValueError(f"{self.kind} cannot have name")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "arguments": dict(self.arguments),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class AgentContext:
    task: PublicTaskSpec
    observations: tuple[Observation, ...] = ()
    session_id: str | None = None


@dataclass(frozen=True)
class TrialResult:
    source_score: Mapping[str, Any] | None = None
    platform_scores: tuple[Mapping[str, Any], ...] = ()
    artifacts: tuple[Mapping[str, Any], ...] = ()
    events: tuple[TraceEvent, ...] = ()


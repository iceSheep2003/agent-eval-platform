"""领域事件。

跨模块副作用一律走事件 + Outbox：生产者不知道谁在消费，消费者各自订阅。
P0 用进程内分发即可，但**接口按跨进程设计**（带 event_id / occurred_at / sequence），
将来换消息队列不改业务代码。

payload 约定：**只放 ID 和判定结论，不放实体全量**。消费者需要细节时回查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

from .common import ActorKind, Id, JsonValue


@dataclass(frozen=True, slots=True)
class ActorRef:
    """事件发起者。自动提案的 actor.kind 是 agent/monitor，权限被硬性收窄。"""

    kind: ActorKind
    id: str
    display_name: str | None = None

    @classmethod
    def user(cls, user_id: Id, display_name: str | None = None) -> "ActorRef":
        return cls(ActorKind.USER, user_id, display_name)

    @classmethod
    def system(cls, name: str = "system") -> "ActorRef":
        return cls(ActorKind.SYSTEM, name)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: Id
    event_type: str
    event_version: int
    workspace_id: Id
    aggregate_type: str
    aggregate_id: Id
    sequence: int
    occurred_at: datetime
    actor: ActorRef
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    tenant_id: Id | None = None


class EventType:
    """事件类型目录。新增只能追加；消费者必须忽略未知类型而不是报错。"""

    # ---- identity ----
    MEMBER_ROLE_CHANGED = "identity.member.role_changed"
    MEMBER_REMOVED = "identity.member.removed"
    TENANT_SYNCED = "identity.tenant.synced"
    TENANT_PURGED = "identity.tenant.purged"
    SESSION_REVOKED = "identity.session.revoked"

    # ---- asset ----
    ASSET_CREATED = "asset.created"
    VERSION_CREATED = "asset.version.created"
    CHANNEL_BOUND = "asset.channel.bound"
    CREDENTIAL_CREATED = "asset.credential.created"
    CREDENTIAL_REVOKED = "asset.credential.revoked"

    # ---- dataset ----
    DATASET_VERSION_FINALIZED = "dataset.version.finalized"
    DATASET_IMPORT_FAILED = "dataset.import.failed"

    # ---- evaluation ----
    TEMPLATE_CREATED = "evaluation.template.created"
    TEMPLATE_UPDATED = "evaluation.template.updated"
    TEMPLATE_DISABLED = "evaluation.template.disabled"

    # ---- execution ----
    RUN_CREATED = "execution.run.created"
    RUN_STARTED = "execution.run.started"
    RUN_PAUSED = "execution.run.paused"
    RUN_RESUMED = "execution.run.resumed"
    RUN_CANCELLED = "execution.run.cancelled"
    RUN_COMPLETED = "execution.run.completed"
    RUN_FAILED = "execution.run.failed"
    TRIAL_STARTED = "execution.trial.started"
    TRIAL_EXECUTION_FAILED = "execution.trial.execution_failed"
    TRIAL_SCORED = "execution.trial.scored"

    # ---- observability ----
    TRACE_INGESTED = "observability.trace.ingested"
    SCORE_EMITTED = "observability.score.emitted"
    METRICS_THRESHOLD_BREACHED = "observability.metrics.threshold_breached"

    # ---- improvement ----
    PROPOSAL_CREATED = "improvement.proposal.created"
    PROPOSAL_REVIEWED = "improvement.proposal.reviewed"
    REGRESSION_SAMPLE_CREATED = "improvement.regression_sample.created"

    # ---- delivery ----
    PROMOTION_REQUESTED = "delivery.promotion.requested"
    PROMOTION_BLOCKED = "delivery.promotion.blocked"
    PROMOTION_APPROVED = "delivery.promotion.approved"
    VERSION_ROLLED_BACK = "delivery.version.rolled_back"

    @classmethod
    def all(cls) -> frozenset[str]:
        return frozenset(
            value for name, value in vars(cls).items() if name.isupper() and isinstance(value, str)
        )


@runtime_checkable
class EventBusPort(Protocol):
    """由基础设施实现（P0 进程内，P1 起可换消息队列）。"""

    async def publish(self, event: DomainEvent) -> None: ...


@runtime_checkable
class EventOutboxPort(Protocol):
    """与业务写入同事务落库，由 Worker 投递。避免「库写成功但事件丢失」。"""

    def append(self, event: DomainEvent) -> None: ...


def build_event(
    *,
    event_type: str,
    workspace_id: Id,
    aggregate_type: str,
    aggregate_id: Id,
    sequence: int,
    occurred_at: datetime,
    actor: ActorRef,
    event_id: Id,
    payload: Mapping[str, Any] | None = None,
    tenant_id: Id | None = None,
    event_version: int = 1,
) -> DomainEvent:
    """统一构造入口，保证所有事件字段齐全。"""
    return DomainEvent(
        event_id=event_id,
        event_type=event_type,
        event_version=event_version,
        workspace_id=workspace_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        sequence=sequence,
        occurred_at=occurred_at,
        actor=actor,
        payload=dict(payload or {}),
        tenant_id=tenant_id,
    )

"""事务性 Outbox：命令队列与事件派发。

**为什么不是直接上 MQ**：核心写路径「业务落库 + 入队」必须原子。外部 MQ 无法加入
数据库事务，先上它会立刻出现「消息发了但事务回滚」或「事务提交了但消息没发」。
所以 DB Outbox 是唯一真相与去重源；外部 MQ（如果将来需要）只是派发优化。

详见 docs/backend-runtime.md §5。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping, Sequence

from sqlalchemy import JSON, DateTime, Integer, String, Text, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..shared.clock import Clock, SystemClock
from .base import Base, TimestampMixin, utcnow
from .database import Database


class CommandStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DONE = "done"
    DEAD = "dead"  # 超过最大重试次数，或没有处理器——需人工介入，不自动丢弃


@dataclass(frozen=True, slots=True)
class Command:
    """一条待执行的命令。handler 必须按 `idempotency_key` 幂等。"""

    id: str
    workspace_id: str
    command_type: str
    aggregate_type: str
    aggregate_id: str
    idempotency_key: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    attempt_no: int = 0
    #: 最早可见时间。留空则用入队时刻——调用方应传自己的 Clock 值，避免与队列时钟不同源。
    not_before: datetime | None = None


@dataclass(frozen=True, slots=True)
class QueueConfig:
    lease_seconds: int = 60
    max_attempts: int = 5
    backoff_base_seconds: float = 2.0
    backoff_cap_seconds: int = 300

    def next_visible_at(self, now: datetime, attempts: int) -> datetime:
        delay = min(self.backoff_base_seconds * (2 ** max(attempts - 1, 0)), self.backoff_cap_seconds)
        return now + timedelta(seconds=delay)


class CommandOutboxRow(Base, TimestampMixin):
    __tablename__ = "platform_command_outbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CommandStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_before: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class EventOutboxRow(Base, TimestampMixin):
    __tablename__ = "platform_event_outbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


def _to_command(row: CommandOutboxRow) -> Command:
    return Command(
        id=row.id,
        workspace_id=row.workspace_id,
        command_type=row.command_type,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        idempotency_key=row.idempotency_key,
        payload=dict(row.payload or {}),
        attempt_no=row.attempts,
    )


class CommandQueue:
    """DB 支撑的命令队列。SQLite 与 PostgreSQL 共用同一段逻辑，只有子查询差一行。"""

    def __init__(
        self,
        database: Database,
        clock: Clock | None = None,
        config: QueueConfig | None = None,
    ) -> None:
        self._db = database
        self._clock = clock or SystemClock()
        self._config = config or QueueConfig()

    @property
    def config(self) -> QueueConfig:
        return self._config

    async def claim(self, worker_id: str, batch: int = 1) -> Sequence[Command]:
        """原子领取。多 worker 并发时不会拿到同一条命令。"""
        now = self._clock.now()
        lease_until = now + timedelta(seconds=self._config.lease_seconds)
        async with self._db.session() as session:
            subquery = (
                select(CommandOutboxRow.id)
                .where(
                    CommandOutboxRow.status == CommandStatus.PENDING,
                    CommandOutboxRow.not_before <= now,
                )
                .order_by(CommandOutboxRow.created_at)
                .limit(batch)
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                subquery = subquery.with_for_update(skip_locked=True)

            stmt = (
                update(CommandOutboxRow)
                .where(CommandOutboxRow.id.in_(subquery))
                .values(
                    status=CommandStatus.CLAIMED,
                    claimed_by=worker_id,
                    claimed_at=now,
                    lease_expires_at=lease_until,
                    attempts=CommandOutboxRow.attempts + 1,
                    updated_at=now,
                )
                .returning(CommandOutboxRow)
            )
            rows = (await session.execute(stmt)).scalars().all()
            await session.commit()
        return [_to_command(row) for row in rows]

    async def complete(self, command_id: str) -> None:
        now = self._clock.now()
        async with self._db.session() as session:
            await session.execute(
                update(CommandOutboxRow)
                .where(CommandOutboxRow.id == command_id)
                .values(
                    status=CommandStatus.DONE,
                    claimed_by=None,
                    lease_expires_at=None,
                    last_error=None,
                    updated_at=now,
                )
            )
            await session.commit()

    async def fail(self, command_id: str, error: str) -> CommandStatus:
        """失败后按退避重新可见；超过上限进死信，不自动丢弃。"""
        now = self._clock.now()
        async with self._db.session() as session:
            row = await session.get(CommandOutboxRow, command_id)
            if row is None:
                return CommandStatus.DEAD
            if row.attempts >= self._config.max_attempts:
                row.status = CommandStatus.DEAD
                status = CommandStatus.DEAD
            else:
                row.status = CommandStatus.PENDING
                row.not_before = self._config.next_visible_at(now, row.attempts)
                status = CommandStatus.PENDING
            row.last_error = error[:2000]
            row.claimed_by = None
            row.lease_expires_at = None
            row.updated_at = now
            await session.commit()
        return status

    async def dead_letter(self, command_id: str, error: str) -> None:
        """直接进死信：重试也不会有结果的情况（例如没有注册处理器）。"""
        now = self._clock.now()
        async with self._db.session() as session:
            await session.execute(
                update(CommandOutboxRow)
                .where(CommandOutboxRow.id == command_id)
                .values(
                    status=CommandStatus.DEAD,
                    claimed_by=None,
                    lease_expires_at=None,
                    last_error=error[:2000],
                    updated_at=now,
                )
            )
            await session.commit()

    async def release_expired_leases(self) -> int:
        """worker 崩溃后回收：租约过期且仍处 claimed 的命令回到 pending。"""
        now = self._clock.now()
        async with self._db.session() as session:
            result = await session.execute(
                update(CommandOutboxRow)
                .where(
                    CommandOutboxRow.status == CommandStatus.CLAIMED,
                    CommandOutboxRow.lease_expires_at.is_not(None),
                    CommandOutboxRow.lease_expires_at < now,
                )
                .values(
                    status=CommandStatus.PENDING,
                    claimed_by=None,
                    lease_expires_at=None,
                    not_before=now,
                    updated_at=now,
                )
            )
            await session.commit()
        return int(result.rowcount or 0)

    async def renew(self, command_id: str, worker_id: str) -> bool:
        """长任务续期；续期失败说明命令已被回收，handler 应尽快停止。"""
        now = self._clock.now()
        async with self._db.session() as session:
            result = await session.execute(
                update(CommandOutboxRow)
                .where(
                    CommandOutboxRow.id == command_id,
                    CommandOutboxRow.claimed_by == worker_id,
                    CommandOutboxRow.status == CommandStatus.CLAIMED,
                )
                .values(
                    lease_expires_at=now + timedelta(seconds=self._config.lease_seconds),
                    updated_at=now,
                )
            )
            await session.commit()
        return bool(result.rowcount)

    async def depth(self) -> Mapping[str, int]:
        """队列深度，用于 k8s HPA / KEDA 扩容与告警。"""
        from sqlalchemy import func

        async with self._db.session() as session:
            stmt = select(CommandOutboxRow.status, func.count()).group_by(CommandOutboxRow.status)
            rows = (await session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}


def append_event(
    session: AsyncSession,
    *,
    event_id: str,
    workspace_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    sequence: int,
    occurred_at: datetime,
    actor_kind: str,
    actor_id: str,
    payload: Mapping[str, Any],
    tenant_id: str | None = None,
    event_version: int = 1,
) -> None:
    """在同一事务里追加事件。调用方负责 commit。"""
    session.add(
        EventOutboxRow(
            id=event_id,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            event_type=event_type,
            event_version=event_version,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            sequence=sequence,
            payload=dict(payload),
            actor_kind=actor_kind,
            actor_id=actor_id,
            occurred_at=occurred_at,
        )
    )


def enqueue_command(session: AsyncSession, command: Command, *, not_before: datetime | None = None) -> None:
    """在同一事务里入队命令。调用方负责 commit。"""
    session.add(
        CommandOutboxRow(
            id=command.id,
            workspace_id=command.workspace_id,
            command_type=command.command_type,
            aggregate_type=command.aggregate_type,
            aggregate_id=command.aggregate_id,
            idempotency_key=command.idempotency_key,
            payload=dict(command.payload),
            status=CommandStatus.PENDING,
            attempts=command.attempt_no,
            not_before=not_before or command.not_before or utcnow(),
        )
    )

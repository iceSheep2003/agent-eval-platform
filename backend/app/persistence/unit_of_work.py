"""事务边界。

一个用例 = 一个 `UnitOfWork`。业务写入、命令入队、事件追加**在同一事务内**完成——
这是「库写成功但任务/事件丢失」这类不一致的根治办法。
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from ..contracts.events import DomainEvent
from .database import Database
from .outbox import Command, append_event, enqueue_command


class UnitOfWork:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork 尚未进入上下文")
        return self._session

    def append(self, event: DomainEvent) -> None:
        """追加领域事件到 Outbox（同事务）。"""
        append_event(
            self.session,
            event_id=event.event_id,
            workspace_id=event.workspace_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            actor_kind=event.actor.kind.value,
            actor_id=event.actor.id,
            payload=event.payload,
            tenant_id=event.tenant_id,
            event_version=event.event_version,
        )

    def enqueue(self, command: Command) -> None:
        """入队命令（同事务）。handler 必须按 `idempotency_key` 幂等。"""
        enqueue_command(self.session, command)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()

    async def __aenter__(self) -> Self:
        self._session = self._database.sessionmaker()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None

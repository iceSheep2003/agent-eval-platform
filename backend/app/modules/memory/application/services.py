"""memory 用例：实现 `contracts.memory.MemoryPort`。

Agent 通过 `memory` 形参拿到的就是这个服务。它**不暴露 workspace_id**——
Agent 只知道自己那片记忆，拿不到别人的分区键，也就无法越界。
"""

from __future__ import annotations

from typing import Sequence

from ....contracts.common import Id
from ....contracts.memory import (
    MemoryFact,
    MemoryKey,
    MemoryPort,
    MemorySessionPort,
    MemoryTurn,
)
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.recall import score, tokenize
from ..infrastructure.repositories import MemoryRepository
from ..infrastructure.tables import MemoryEntryRow

#: 保留上限：单分区的轮次超过这个数就丢最旧的。防无界增长。
MAX_TURNS_PER_SCOPE = 500


class MemoryService(MemoryPort):
    def __init__(self, database: Database, clock: Clock, *, workspace_id: Id) -> None:
        self._db = database
        self._clock = clock
        self._workspace_id = workspace_id

    async def remember_turns(
        self, target: MemoryKey, turns: Sequence[MemoryTurn]
    ) -> None:
        if not turns:
            return
        async with UnitOfWork(self._db) as uow:
            repo = MemoryRepository(uow.session)
            seq = await repo.next_seq(target)
            rows = [
                MemoryEntryRow(
                    id=new_id("memory"),
                    workspace_id=self._workspace_id,
                    agent_version_id=target.agent_version_id,
                    tenant_id=target.tenant_id,
                    thread_id=target.thread_id,
                    scope=target.scope,
                    kind="turn",
                    seq=seq + index,
                    role=turn.role,
                    content=turn.content,
                    fact_key=None,
                    terms=sorted(tokenize(turn.content)),
                )
                for index, turn in enumerate(turns)
            ]
            await repo.append_entries(rows)
            await uow.commit()

    async def recent_turns(
        self, target: MemoryKey, limit: int = 8
    ) -> Sequence[MemoryTurn]:
        async with UnitOfWork(self._db) as uow:
            return list(await MemoryRepository(uow.session).recent_turns(target, limit))

    async def remember_fact(self, target: MemoryKey, key: str, value: str) -> None:
        async with UnitOfWork(self._db) as uow:
            repo = MemoryRepository(uow.session)
            seq = await repo.next_seq(target)
            await repo.upsert_fact(
                target, key, value, sorted(tokenize(f"{key} {value}")), seq
            )
            await uow.commit()

    async def recall_facts(
        self, target: MemoryKey, query: str, top_k: int = 5
    ) -> Sequence[MemoryFact]:
        wanted = tokenize(query)
        if not wanted:
            return []
        async with UnitOfWork(self._db) as uow:
            entries = await MemoryRepository(uow.session).all_facts(target)
        scored = [
            (score(wanted, terms), fact)
            for fact, terms in entries
        ]
        hits = [item for item in scored if item[0] > 0]
        hits.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in hits[:top_k]]

    def for_key(self, key: MemoryKey) -> MemorySessionPort:
        """出一个**绑好分区**的收窄句柄，交给 Agent 用。"""
        return MemorySession(self, key)

    async def forget(self, target: MemoryKey) -> int:
        async with UnitOfWork(self._db) as uow:
            removed = await MemoryRepository(uow.session).delete_scope(target)
            await uow.commit()
        return removed




class MemorySession(MemorySessionPort):
    """注入给 Agent 的句柄：分区键已绑好，接口只覆盖「自己那一小片」。

    这是 `MemoryPort` 的**收窄视图**，不是另一套实现——所以不存在两边行为不一致
    的问题，Agent 也拿不到别人的分区。
    """

    def __init__(self, port: MemoryPort, key: MemoryKey) -> None:
        self._port = port
        self._key = key

    async def recent(self, limit: int = 8) -> Sequence[MemoryTurn]:
        return await self._port.recent_turns(self._key, limit)

    async def remember(self, role: str, content: str) -> None:
        await self._port.remember_turns(self._key, [MemoryTurn(role=role, content=content)])

    async def save_fact(self, key: str, value: str) -> None:
        await self._port.remember_fact(self._key, key, value)

    async def recall(self, query: str, top_k: int = 5) -> Sequence[MemoryFact]:
        return await self._port.recall_facts(self._key, query, top_k)


__all__ = ["MAX_TURNS_PER_SCOPE", "MemoryService", "MemorySession"]

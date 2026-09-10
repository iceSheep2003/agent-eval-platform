"""memory 仓储：按作用域分区读写。

**每个查询都必须带全 `(agent_version_id, tenant_id, thread_id, scope)`**——
少带一维就是把别人的记忆读出来了。所以这里的私有方法是 `_scope_filter`，
而不是让调用方自己拼 where。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.memory import MemoryFact, MemoryKey, MemoryTurn
from ....shared.clock import ensure_aware
from .tables import MemoryEntryRow


def _scope_filter(key: MemoryKey):
    return (
        MemoryEntryRow.agent_version_id == key.agent_version_id,
        MemoryEntryRow.tenant_id.is_(key.tenant_id)
        if key.tenant_id is None
        else MemoryEntryRow.tenant_id == key.tenant_id,
        MemoryEntryRow.thread_id.is_(key.thread_id)
        if key.thread_id is None
        else MemoryEntryRow.thread_id == key.thread_id,
        MemoryEntryRow.scope == key.scope,
    )


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_seq(self, key: MemoryKey) -> int:
        stmt = select(func.max(MemoryEntryRow.seq)).where(*_scope_filter(key))
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(current or 0) + 1

    async def append_entries(self, rows: Sequence[MemoryEntryRow]) -> None:
        for row in rows:
            self._session.add(row)

    async def recent_turns(self, key: MemoryKey, limit: int) -> Sequence[MemoryTurn]:
        stmt = (
            select(MemoryEntryRow)
            .where(*_scope_filter(key), MemoryEntryRow.kind == "turn")
            .order_by(MemoryEntryRow.seq.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [MemoryTurn(role=row.role or "user", content=row.content) for row in reversed(rows)]

    async def all_facts(self, key: MemoryKey) -> Sequence[tuple[MemoryFact, list[str]]]:
        """返回 `(事实, 词项)`——打分要用词项，一起取出来避免再查一次。"""
        stmt = select(MemoryEntryRow).where(
            *_scope_filter(key), MemoryEntryRow.kind == "fact"
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            (MemoryFact(key=row.fact_key or "", value=row.content), list(row.terms or []))
            for row in rows
        ]

    async def upsert_fact(self, key: MemoryKey, fact_key: str, value: str, terms: list[str], seq: int) -> None:
        stmt = select(MemoryEntryRow).where(
            *_scope_filter(key),
            MemoryEntryRow.kind == "fact",
            MemoryEntryRow.fact_key == fact_key,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            self._session.add(
                MemoryEntryRow(
                    id=f"mem_{key.agent_version_id}_{seq}",
                    workspace_id="",
                    agent_version_id=key.agent_version_id,
                    tenant_id=key.tenant_id,
                    thread_id=key.thread_id,
                    scope=key.scope,
                    kind="fact",
                    seq=seq,
                    role=None,
                    content=value,
                    fact_key=fact_key,
                    terms=terms,
                )
            )
            return
        row.content = value
        row.terms = terms

    async def delete_scope(self, key: MemoryKey) -> int:
        result = await self._session.execute(
            delete(MemoryEntryRow).where(*_scope_filter(key))
        )
        return int(result.rowcount or 0)

    async def count(self, key: MemoryKey) -> int:
        stmt = select(func.count()).select_from(MemoryEntryRow).where(*_scope_filter(key))
        return int((await self._session.execute(stmt)).scalar_one())

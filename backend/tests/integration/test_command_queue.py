"""命令队列的投递语义。

这些不变量是 Worker 能安全重试的前提：租约、退避、死信、幂等键。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.persistence import (
    Command,
    CommandQueue,
    CommandStatus,
    Database,
    QueueConfig,
    UnitOfWork,
    create_engine,
)
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def _database(tmp_path) -> Database:
    settings = Settings(
        env="development",
        data_dir=tmp_path,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'queue.db'}",
        master_key="test",
    )
    return Database(create_engine(settings))


def _command(key: str, clock: FixedClock, **overrides) -> Command:
    defaults = dict(
        id=f"cmd_{key}",
        workspace_id="ws_1",
        command_type="run.prepare",
        aggregate_type="run",
        aggregate_id="run_1",
        idempotency_key=key,
        payload={"run_id": "run_1"},
        not_before=clock.now(),
    )
    defaults.update(overrides)
    return Command(**defaults)


async def _scenario(tmp_path) -> None:
    database = _database(tmp_path)
    await database.create_all()
    clock = FixedClock()
    queue = CommandQueue(database, clock, QueueConfig(lease_seconds=60, max_attempts=3))
    try:
        # 入队必须与业务写入同事务
        async with UnitOfWork(database) as uow:
            uow.enqueue(_command("a", clock))
            uow.enqueue(_command("b", clock))
            await uow.commit()

        assert await queue.depth() == {"pending": 2}

        # 领取：一次拿一条，状态变 claimed
        claimed = await queue.claim("worker-1", batch=1)
        assert len(claimed) == 1
        assert claimed[0].idempotency_key == "a"
        assert claimed[0].attempt_no == 1
        assert await queue.depth() == {"claimed": 1, "pending": 1}

        # 另一个 worker 不会拿到同一条
        other = await queue.claim("worker-2", batch=10)
        assert [c.idempotency_key for c in other] == ["b"]

        # 完成
        await queue.complete(claimed[0].id)
        assert (await queue.depth())["done"] == 1

        # 失败 → 退避后重新可见
        await queue.fail(other[0].id, "boom")
        depth = await queue.depth()
        assert depth["pending"] == 1 and depth.get("claimed") is None
        assert await queue.claim("worker-1", batch=5) == []  # not_before 未到

        clock.advance(seconds=10)
        retried = await queue.claim("worker-1", batch=5)
        assert len(retried) == 1 and retried[0].attempt_no == 2

        # 超过最大重试 → 死信，不静默丢弃
        await queue.fail(retried[0].id, "again")
        clock.advance(seconds=60)
        last = await queue.claim("worker-1", batch=5)
        assert last and last[0].attempt_no == 3
        status = await queue.fail(last[0].id, "third")
        assert status is CommandStatus.DEAD
        assert (await queue.depth())["dead"] == 1

        # 租约过期可被回收
        async with UnitOfWork(database) as uow:
            uow.enqueue(_command("c", clock))
            await uow.commit()
        leased = await queue.claim("worker-3", batch=1)
        assert leased
        clock.advance(seconds=61)
        assert await queue.release_expired_leases() == 1
        reclaimed = await queue.claim("worker-4", batch=1)
        assert reclaimed and reclaimed[0].id == leased[0].id

        # 续期失败说明已被回收，handler 应停止
        assert await queue.renew(reclaimed[0].id, "worker-3") is False
        assert await queue.renew(reclaimed[0].id, "worker-4") is True
    finally:
        await database.dispose()


def test_command_queue_semantics(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))


async def _idempotency_scenario(tmp_path) -> None:
    database = _database(tmp_path)
    await database.create_all()
    clock = FixedClock()
    try:
        async with UnitOfWork(database) as uow:
            uow.enqueue(_command("dup", clock))
            await uow.commit()
        with pytest.raises(Exception):
            async with UnitOfWork(database) as uow:
                uow.enqueue(_command("dup", clock))
                await uow.commit()
    finally:
        await database.dispose()


def test_duplicate_idempotency_key_is_rejected(tmp_path) -> None:
    """同一幂等键重复入队必须被数据库拦住，而不是产生两条命令。"""
    asyncio.run(_idempotency_scenario(tmp_path))

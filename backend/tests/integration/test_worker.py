"""Worker 消费命令：分发、成功完成、未知类型进死信、handler 抛错可重试。"""

from __future__ import annotations

import asyncio
from typing import Sequence

from backend.app.container import Container
from backend.app.persistence import Command, UnitOfWork
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock
from backend.runtime.worker import Worker


class RecordingHandler:
    command_type = "echo"

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def handle(self, command: Command, uow: UnitOfWork) -> None:
        self.seen.append(command.idempotency_key)


class FailingHandler:
    command_type = "boom"

    async def handle(self, command: Command, uow: UnitOfWork) -> None:
        raise RuntimeError("处理失败")


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}",
            master_key="test",
            command_max_attempts=2,
        ),
        clock=clock,
    )


def _command(key: str, clock: FixedClock, command_type: str = "echo") -> Command:
    return Command(
        id=f"cmd_{key}",
        workspace_id="ws_1",
        command_type=command_type,
        aggregate_type="run",
        aggregate_id="run_1",
        idempotency_key=key,
        not_before=clock.now(),
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        async with UnitOfWork(container.database) as uow:
            uow.enqueue(_command("ok-1", clock))
            uow.enqueue(_command("ok-2", clock))
            uow.enqueue(_command("unknown", clock, command_type="not.registered"))
            uow.enqueue(_command("boom", clock, command_type="boom"))
            await uow.commit()

        handler = RecordingHandler()
        worker = Worker(container, [handler, FailingHandler()], worker_id="test-worker")

        assert await worker.run_once() == 4
        assert sorted(handler.seen) == ["ok-1", "ok-2"]

        depth = await container.command_queue.depth()
        assert depth["done"] == 2
        # 未知类型与 handler 异常都不静默丢弃
        assert depth["pending"] == 1  # boom 第 1 次失败，退避后可重试
        assert depth["dead"] == 1  # 未知类型没有处理器，重试无意义 → 直接死信

        # 第二次重试后超过 max_attempts=2 → 死信
        clock.advance(seconds=10)
        await worker.run_once()
        assert (await container.command_queue.depth())["dead"] == 2

        # 优雅停机：不再领取
        worker.request_stop()
        async with UnitOfWork(container.database) as uow:
            uow.enqueue(_command("late", clock))
            await uow.commit()
        await worker.run_forever()
        assert (await container.command_queue.depth())["pending"] == 1
    finally:
        await container.shutdown()


def test_worker_dispatch_and_failure_handling(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

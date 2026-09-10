"""Worker 进程入口：消费命令队列。

    python -m backend.runtime.worker

k8s 里是一个**没有 Service 的 Deployment**，按队列深度扩容。
多个副本并发安全：`CommandQueue.claim` 用原子 UPDATE...RETURNING 领取，
不会有两个 worker 拿到同一条命令。

投递语义是 **at-least-once**——handler 必须按 `command.idempotency_key` 幂等，
这是重试与租约回收能安全工作的前提（见 docs/backend-runtime.md §5.4）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Protocol, Sequence

from backend.app.container import Container
from backend.app.persistence import Command, UnitOfWork

logger = logging.getLogger(__name__)

IDLE_SLEEP_SECONDS = 1.0
LEASE_REAP_INTERVAL_SECONDS = 30.0
#: 运行实例探活的扫描间隔。实际节奏由 `Settings.health_interval_seconds` 决定，
#: 这里只是「多久看一眼有没有到期的」。
PROBE_SCAN_INTERVAL_SECONDS = 10.0


class CommandHandler(Protocol):
    """命令处理器。实现方在 `modules/<name>/application/` 里。

    一个 handler 可以管多种命令（`command_types`），也可以只写单个 `command_type`。
    """

    command_types: tuple[str, ...]

    async def handle(self, command: Command, uow: UnitOfWork) -> None: ...


def _command_types_of(handler: object) -> tuple[str, ...]:
    multiple = getattr(handler, "command_types", None)
    if multiple:
        return tuple(multiple)
    single = getattr(handler, "command_type", None)
    if single:
        return (str(single),)
    raise TypeError(f"{type(handler).__name__} 既没有 command_types 也没有 command_type")


class UnknownCommandType(RuntimeError):
    pass


class Worker:
    def __init__(
        self,
        container: Container,
        handlers: Sequence[CommandHandler] = (),
        *,
        worker_id: str | None = None,
        batch: int = 4,
    ) -> None:
        self._container = container
        self._handlers = {
            command_type: handler
            for handler in handlers
            for command_type in _command_types_of(handler)
        }
        self._worker_id = worker_id or f"worker-{os.getpid()}"
        self._batch = batch
        self._stopping = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def register(self, handler: CommandHandler) -> None:
        for command_type in _command_types_of(handler):
            self._handlers[command_type] = handler

    def request_stop(self) -> None:
        """优雅停机：停止领取新命令，在途的跑完。"""
        self._stopping = True

    async def run_once(self) -> int:
        """领取并处理一批命令，返回处理条数。测试里可以直接调它。"""
        claimed = await self._container.command_queue.claim(self._worker_id, self._batch)
        if not claimed:
            return 0
        await asyncio.gather(*(self._dispatch(command) for command in claimed))
        return len(claimed)

    async def run_forever(self) -> None:
        last_reap = 0.0
        last_probe = 0.0
        while not self._stopping:
            loop = asyncio.get_running_loop()
            now = loop.time()

            if now - last_reap >= LEASE_REAP_INTERVAL_SECONDS:
                reclaimed = await self._container.command_queue.release_expired_leases()
                if reclaimed:
                    logger.warning("回收了 %d 条租约过期的命令", reclaimed)
                last_reap = now

            # 运行实例探活。**这里是调度点，不是逻辑实现**——探活本身在
            # DeploymentService.probe_due()。上 k8s 后把这一行换成 CronJob 即可，
            # 业务逻辑与状态机不动。
            if now - last_probe >= PROBE_SCAN_INTERVAL_SECONDS:
                probed = await self._container.deployments.probe_due()
                if probed:
                    logger.info("探活了 %d 个运行实例", probed)
                last_probe = now

            processed = await self.run_once()
            if processed == 0:
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
        logger.info("worker %s 已停止领取新命令", self._worker_id)

    async def _dispatch(self, command: Command) -> None:
        handler = self._handlers.get(command.command_type)
        if handler is None:
            # 没有处理器时重试也没意义，直接进死信等人工介入，不静默丢弃。
            await self._container.command_queue.dead_letter(
                command.id, f"{UnknownCommandType.__name__}: {command.command_type}"
            )
            logger.error("没有注册 %s 的处理器，命令 %s 已进死信", command.command_type, command.id)
            return

        try:
            async with UnitOfWork(self._container.database) as uow:
                await handler.handle(command, uow)
                await uow.commit()
        except Exception as exc:  # noqa: BLE001 - 队列层必须兜住所有异常
            logger.exception("命令 %s 执行失败", command.id)
            await self._container.command_queue.fail(command.id, repr(exc))
        else:
            await self._container.command_queue.complete(command.id)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    container = Container.build()
    await container.startup()

    worker = Worker(container, [container.execution_handlers])
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run_forever()
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

"""组合根。

**唯一知道具体实现的地方**：把 Port 绑到 Adapter、把配置注入服务。
模块之间不互相 new 对方的实现，全靠这里装配。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from .modules.asset.application.services import AssetService
from .modules.identity.application.services import IdentityService
from .modules.identity.domain.authorizer import Authorizer
from .modules.observability.application.services import TraceService
from .persistence import CommandQueue, Database, QueueConfig, create_engine
from .settings import Settings
from .shared.clock import Clock, SystemClock


@dataclass(slots=True)
class Container:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    database: Database
    authorizer: Authorizer
    identity: IdentityService
    assets: AssetService
    traces: TraceService
    command_queue: CommandQueue

    @classmethod
    def build(cls, settings: Settings | None = None, clock: Clock | None = None) -> "Container":
        resolved = settings or Settings.from_env()
        resolved_clock = clock or SystemClock()
        engine = create_engine(resolved)
        database = Database(engine)
        authorizer = Authorizer()
        identity = IdentityService(
            database,
            resolved_clock,
            authorizer,
            session_idle_hours=resolved.session_idle_hours,
            session_absolute_hours=resolved.session_absolute_hours,
        )
        assets = AssetService(database, resolved_clock, identity)
        traces = TraceService(database, resolved_clock, assets)
        command_queue = CommandQueue(
            database,
            resolved_clock,
            QueueConfig(
                lease_seconds=resolved.command_lease_seconds,
                max_attempts=resolved.command_max_attempts,
            ),
        )
        return cls(
            settings=resolved,
            clock=resolved_clock,
            engine=engine,
            database=database,
            authorizer=authorizer,
            identity=identity,
            assets=assets,
            traces=traces,
            command_queue=command_queue,
        )

    async def startup(self) -> None:
        """开发态自动建表；生产必须由 `runtime/migrate.py` 先跑完迁移。"""
        if self.settings.is_production:
            await self._assert_migrated()
        else:
            await self.database.create_all()

    async def _assert_migrated(self) -> None:
        """生产启动前确认迁移已应用——比「表不存在」的模糊报错早失败得多。"""
        from sqlalchemy import text

        try:
            async with self.database.session() as session:
                result = await session.execute(text("SELECT version_num FROM alembic_version"))
                applied = result.scalars().all()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "数据库尚未迁移。生产环境请先运行 "
                "`python -m backend.runtime.migrate`（k8s 中是 migrate Job / initContainer）。"
            ) from exc
        if not applied:
            raise RuntimeError("alembic_version 为空：迁移未应用或未完成。")

    async def shutdown(self) -> None:
        await self.database.dispose()

"""异步引擎与 SQLite 调优。

SQLite 默认没有 WAL、默认 `busy_timeout=0`——四个进程（console/ingest/worker/scheduler）
同时写时会立刻 `database is locked`。所以连接建立时必须打三个 PRAGMA。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..settings import Settings

logger = logging.getLogger(__name__)

#: 秒；写锁等待上限。超过才抛 database is locked。
BUSY_TIMEOUT_MS = 5000


def create_engine(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    engine = create_async_engine(
        settings.database_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
    )
    if engine.dialect.name == "sqlite":
        _install_sqlite_pragmas(engine)
    return engine


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    logger.debug("已为 SQLite 安装 WAL / busy_timeout / foreign_keys PRAGMA")

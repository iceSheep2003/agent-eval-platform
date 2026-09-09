"""Alembic 环境。

支持按模块过滤 metadata：设置 `ALEMBIC_MODULE=identity|asset|platform` 后，
autogenerate 只会看到该模块前缀的表——这就是「一个迁移文件只碰自己模块的表」的实现方式。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
for candidate in (str(REPO_ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from alembic import context  # noqa: E402
from sqlalchemy import MetaData, pool  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

# 导入所有定义表的模块，确保 Base.metadata 完整。
from backend.app.persistence.base import Base  # noqa: E402
import backend.app.persistence.outbox  # noqa: E402,F401
import backend.app.modules.identity.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.asset.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.dataset.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.evaluation.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.execution.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.observability.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.portal.infrastructure.tables  # noqa: E402,F401
from backend.app.settings import Settings  # noqa: E402

MODULE_PREFIXES = (
    "identity",
    "asset",
    "dataset",
    "evaluation",
    "run",
    "platform",
    "obs",
    "portal",
)


def _metadata_for(module: str | None) -> MetaData:
    if not module:
        return Base.metadata
    if module not in MODULE_PREFIXES:
        raise SystemExit(f"未知模块 {module!r}；应为 {MODULE_PREFIXES} 之一")
    filtered = MetaData()
    for table in Base.metadata.tables.values():
        if table.name.startswith(f"{module}_"):
            table.to_metadata(filtered)
    return filtered


target_metadata = _metadata_for(os.getenv("ALEMBIC_MODULE"))


def _url() -> str:
    return os.getenv("EVAL_LOOM_DATABASE_URL") or Settings.from_env().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite 不支持大部分 ALTER，用 batch 模式重建表
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""迁移进程入口：k8s Job / initContainer。

    python -m backend.runtime.migrate

**必须在 Deployment 滚动更新之前跑完**——否则新代码会撞上旧表结构。
生产环境的 `Container.startup()` 不会自动建表，表结构只由这里负责。

按模块升级单个分支：
    python -m backend.runtime.migrate identity@head
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from backend.app.settings import Settings

logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def _sync_url(async_url: str) -> str:
    """Alembic 的 current/head 比对用同步驱动即可。"""
    return async_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = argv if argv is not None else sys.argv[1:]
    target = args[0] if args else "heads"

    config = Config(str(ALEMBIC_INI))
    url = Settings.from_env().database_url
    config.set_main_option("sqlalchemy.url", url)

    logger.info("升级数据库到 %s", target)
    command.upgrade(config, target)

    engine = create_engine(_sync_url(url))
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
    engine.dispose()

    script = ScriptDirectory.from_config(config)
    logger.info("当前 revision: %s；脚本 head: %s", current, script.get_heads())
    return 0


if __name__ == "__main__":
    sys.exit(main())

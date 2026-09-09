"""迁移建出来的表，必须和 ORM 模型一致。

挡住一类「开发环境看不出来、生产必炸」的问题：模型加了列但忘了写迁移。
开发库靠 `create_all()` 建表，看起来一切正常；生产走 `alembic upgrade`，
少的列在**第一次写数据时**才暴露（`no such column: asset_credential.channel`）。

这条测试把两边都建出来逐列比对。
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from backend.app.persistence.base import Base
from backend.tests.architecture._helpers import BACKEND_ROOT

# 导入所有定义表的模块，确保 Base.metadata 完整（与 migrations/env.py 保持一致）
import backend.app.persistence.outbox  # noqa: E402,F401
import backend.app.modules.identity.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.asset.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.dataset.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.evaluation.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.execution.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.observability.infrastructure.tables  # noqa: E402,F401
import backend.app.modules.portal.infrastructure.tables  # noqa: E402,F401


def test_migrations_match_models(tmp_path, monkeypatch) -> None:
    database = tmp_path / "migrated.db"
    monkeypatch.setenv("EVAL_LOOM_DATABASE_URL", f"sqlite+aiosqlite:///{database}")

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "heads")

    engine = create_engine(f"sqlite:///{database}")
    try:
        inspector = inspect(engine)
        migrated = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
            if table != "alembic_version"
        }
    finally:
        engine.dispose()

    expected = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }

    assert set(migrated) == set(expected), (
        f"迁移与模型的表集合不一致：\n"
        f"  只在迁移里：{sorted(set(migrated) - set(expected))}\n"
        f"  只在模型里：{sorted(set(expected) - set(migrated))}"
    )

    missing = {
        table: sorted(columns - migrated[table])
        for table, columns in expected.items()
        if columns - migrated[table]
    }
    assert not missing, (
        "以下列只存在于模型、迁移里没有——生产升级会漏掉它们：\n"
        + "\n".join(f"  {table}: {cols}" for table, cols in missing.items())
    )

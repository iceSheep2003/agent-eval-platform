"""迁移文件只能操作自己模块前缀的表。

这是「并行开发不互相踩踏」在数据库层的实现：`identity_0007` 永远不会去改 `asset_*`，
所以两条 Track 可以各自生成、各自升级，不需要 `alembic merge`。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from backend.tests.architecture._helpers import BACKEND_ROOT

VERSIONS_DIR = BACKEND_ROOT / "migrations" / "versions"

#: 第一个参数是**表名**的操作
TABLE_FIRST_OPS = (
    "create_table",
    "drop_table",
    "add_column",
    "drop_column",
    "alter_column",
    "create_unique_constraint",
    "create_foreign_key",
    "create_check_constraint",
)

#: 第一个参数是**索引名**、第二个才是表名的操作
TABLE_SECOND_OPS = ("create_index", "drop_index")

#: `batch_op.add_column('x')` 的第一个参数是**列名**，不是表名——表名在 `batch_alter_table`
#: 上。所以用 `(?<!batch_)` 排除掉，表名改由 `_BATCH` 单独校验。
_CALL = re.compile(
    r"(?<!batch_)op\.(" + "|".join(TABLE_FIRST_OPS) + r")\(\s*[\"']([a-z_]+)[\"']"
)

#: create_index('ix_x', 'table_name', ...) —— 表名在第二位
_CALL_SECOND = re.compile(
    r"(?<!batch_)op\.(" + "|".join(TABLE_SECOND_OPS)
    + r")\(\s*[\"'][a-z_]+[\"']\s*,\s*[\"']([a-z_]+)[\"']"
)

#: batch_alter_table('table_name', ...) —— 批处理块的目标表。
_BATCH = re.compile(r"batch_alter_table\(\s*[\"']([a-z_]+)[\"']")


def _table_names(source: str) -> list[str]:
    return (
        [table for _, table in _CALL.findall(source)]
        + [table for _, table in _CALL_SECOND.findall(source)]
        + _BATCH.findall(source)
    )


def _migrations() -> list[Path]:
    return sorted(path for path in VERSIONS_DIR.glob("*.py") if path.name != "__init__.py")


def _branch_labels(path: Path) -> tuple[str, ...]:
    """读 `branch_labels`。后续迁移写 `branch_labels = None`（合法），返回空元组。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "branch_labels":
                    value = ast.literal_eval(node.value)
                    return tuple(value) if value else ()
    return ()


def _module_of(path: Path) -> str:
    """迁移属于哪个模块。

    分支**根**迁移用 `branch_labels` 声明（Alembic 要求一个分支名只能用一次），
    后续迁移 `branch_labels = None`，模块名从文件名前缀取——
    `test_migration_revisions_are_module_prefixed` 保证了两者一致。
    """
    labels = _branch_labels(path)
    assert len(labels) <= 1, f"{path.name} 只应属于一个模块，收到 {labels}"
    if labels:
        return labels[0]
    return path.name.split("_", 1)[0]


@pytest.mark.parametrize("path", _migrations(), ids=lambda path: path.name)
def test_migration_touches_only_own_module_tables(path: Path) -> None:
    module = _module_of(path)
    source = path.read_text(encoding="utf-8")
    offenders = [
        table for table in _table_names(source) if not table.startswith(f"{module}_")
    ]
    assert not offenders, (
        f"{path.name} 属于模块 {module}，却操作了其他模块的表：{offenders}。\n"
        f"跨模块表结构变更必须由该模块自己的迁移完成。"
    )


def test_every_module_has_a_baseline() -> None:
    """每个有表的模块都必须有基线迁移，否则生产建不出表。"""
    labels = {label for path in _migrations() for label in _branch_labels(path)}
    assert {"identity", "asset", "platform"} <= labels


def test_migration_revisions_are_module_prefixed() -> None:
    for path in _migrations():
        assert path.name.startswith(f"{_module_of(path)}_"), (
            f"{path.name} 的文件名应以模块名开头，便于按模块检索"
        )

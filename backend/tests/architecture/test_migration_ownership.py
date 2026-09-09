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

#: op.xxx(<table_name>, ...) —— 第一个参数是表名的操作
TABLE_OPS = (
    "create_table",
    "drop_table",
    "add_column",
    "drop_column",
    "alter_column",
    "create_index",
    "drop_index",
    "create_unique_constraint",
    "create_foreign_key",
    "create_check_constraint",
)

_CALL = re.compile(r"op\.(" + "|".join(TABLE_OPS) + r")\(\s*[\"']([a-z_]+)[\"']")


def _migrations() -> list[Path]:
    return sorted(path for path in VERSIONS_DIR.glob("*.py") if path.name != "__init__.py")


def _branch_labels(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "branch_labels":
                    return tuple(ast.literal_eval(node.value))
    return ()


@pytest.mark.parametrize("path", _migrations(), ids=lambda path: path.name)
def test_migration_touches_only_own_module_tables(path: Path) -> None:
    labels = _branch_labels(path)
    assert labels, f"{path.name} 必须声明 branch_labels（模块名）"
    assert len(labels) == 1, f"{path.name} 只应属于一个模块，收到 {labels}"

    module = labels[0]
    source = path.read_text(encoding="utf-8")
    offenders = [
        f"{op}({table!r})"
        for op, table in _CALL.findall(source)
        if not table.startswith(f"{module}_")
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
        labels = _branch_labels(path)
        if labels:
            assert path.name.startswith(f"{labels[0]}_"), (
                f"{path.name} 的文件名应以模块名开头，便于按模块检索"
            )

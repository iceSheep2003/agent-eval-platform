"""R2：模块之间只能通过 `contracts/` 通信。

违反这条 = 两个模块的实现耦合在一起，并行开发必然互相踩踏。
"""

from __future__ import annotations

import pytest

from backend.tests.architecture._helpers import APP_ROOT, modules_root, module_names, python_files

#: 模块可以依赖的共享层。
SHARED_PREFIXES = ("app.contracts", "app.shared", "app.persistence", "app.schemas")


@pytest.mark.parametrize("module", module_names())
def test_module_does_not_import_other_modules(module: str) -> None:
    root = modules_root() / module
    violations: list[str] = []
    for source in python_files(root):
        for imported in source.imports:
            if not imported.startswith("app.modules."):
                continue
            target = imported.split(".")[2]
            if target != module:
                violations.append(f"{source.rel} -> {imported}")
    assert not violations, (
        f"模块 {module} 直接 import 了其他模块的实现；"
        f"应改为依赖 contracts/<对方>：\n" + "\n".join(violations)
    )


def test_no_module_imports_deleted_legacy_layers() -> None:
    """旧的水平分层目录已删除，防止有人再往那里写。

    `app/api/` 例外：它现在是**跨模块共享**的 HTTP 设施（错误映射、前缀约定），
    不承载任何业务用例。
    """
    for legacy in ("application", "domain", "infrastructure", "core"):
        assert not (APP_ROOT / legacy).exists(), f"旧目录 app/{legacy}/ 不应存在"


def test_shared_prefixes_stay_dependency_free() -> None:
    """`shared/` 是技术内核，不得反向依赖业务模块。"""
    violations: list[str] = []
    for source in python_files(APP_ROOT / "shared"):
        for imported in source.imports:
            if imported.startswith(("app.modules", "app.contracts")):
                violations.append(f"{source.rel} -> {imported}")
    assert not violations, "shared/ 不得依赖 modules/ 或 contracts/：\n" + "\n".join(violations)

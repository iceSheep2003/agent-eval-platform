"""G2/G3：契约只在有真实消费方时才存在。

契约的成本不在写，而在「冻结之后改不动」。这条检查把「不要预先冻结」
从口头约定变成机械约束：`contracts/` 里导出的每个名字，
必须在 `modules/` 或 `runtime/` 里被真正引用。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.tests.architecture._helpers import APP_ROOT, BACKEND_ROOT, RUNTIME_ROOT, python_files

CONTRACTS_ROOT = APP_ROOT / "contracts"


def _exported_names(init_file: Path) -> list[str]:
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    return [item.value for item in getattr(node.value, "elts", [])]
    return []


def _contract_packages() -> list[Path]:
    return sorted(
        child
        for child in CONTRACTS_ROOT.iterdir()
        if child.is_dir() and (child / "__init__.py").exists()
    )


def _consumer_sources() -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for root in (APP_ROOT / "modules", RUNTIME_ROOT):
        for source in python_files(root):
            sources.append((source.rel, source.source))
    return sources


@pytest.mark.parametrize("package", _contract_packages(), ids=lambda path: path.name)
def test_every_exported_contract_item_has_a_consumer(package: Path) -> None:
    exported = _exported_names(package / "__init__.py")
    if not exported:
        return
    consumers = _consumer_sources()
    orphans = [
        name
        for name in exported
        if not any(name in text for _, text in consumers)
    ]
    assert not orphans, (
        f"contracts/{package.name} 中的 {orphans} 没有任何消费方。\n"
        f"按 G2/G3：等第一个真实调用出现时再加，不要预先冻结。"
    )


def test_contract_version_is_zero_before_first_external_consumer() -> None:
    """G7：出现外部消费者（前端接真数据 / 独立部署）之前不升 1.0.0。"""
    namespace: dict[str, object] = {}
    exec((CONTRACTS_ROOT / "__init__.py").read_text(encoding="utf-8"), namespace)
    version = str(namespace["CONTRACT_VERSION"])
    assert version.startswith("0."), f"契约版本 {version} 应在 0.x 阶段"


def test_backend_root_is_importable() -> None:
    assert (BACKEND_ROOT / "__init__.py").exists()

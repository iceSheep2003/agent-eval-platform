"""架构检查的公共工具：解析每个源文件真正 import 了哪些模块。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
RUNTIME_ROOT = BACKEND_ROOT / "runtime"


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: Path
    module: str  # 相对 backend/ 的模块名，如 app.modules.identity.domain.authorizer
    imports: frozenset[str]
    source: str

    @property
    def rel(self) -> str:
        return str(self.path.relative_to(BACKEND_ROOT))


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(BACKEND_ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve(module: str | None, level: int, package: str) -> str | None:
    if level == 0:
        return module
    base = package.split(".")
    drop = level - 1
    if drop > len(base):
        return module
    prefix = base[: len(base) - drop]
    if module:
        prefix = [*prefix, *module.split(".")]
    return ".".join(prefix)


def parse(path: Path) -> SourceFile:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    module = _module_name(path)
    package = module.rsplit(".", 1)[0] if "." in module else module
    # 对包内的 __init__.py，package 就是它自己
    if path.name == "__init__.py":
        package = module

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve(node.module, node.level, package)
            if resolved:
                found.add(resolved)
                for alias in node.names:
                    found.add(f"{resolved}.{alias.name}")
    return SourceFile(
        path=path, module=module, imports=frozenset(found), source=source
    )


def python_files(root: Path) -> list[SourceFile]:
    return [
        parse(path)
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def modules_root() -> Path:
    return APP_ROOT / "modules"


def module_names() -> list[str]:
    return sorted(
        child.name
        for child in modules_root().iterdir()
        if child.is_dir() and (child / "__init__.py").exists()
    )


def top_level(import_name: str) -> str:
    return import_name.split(".")[0]

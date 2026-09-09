"""R6：领域层不依赖任何框架。

领域逻辑一旦 import 了 SQLAlchemy 或 FastAPI，就再也无法被纯单测覆盖，
也无法在 Worker / CLI / SDK 侧复用。
"""

from __future__ import annotations

from backend.tests.architecture._helpers import modules_root, module_names, python_files

FORBIDDEN = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "httpx",
    "pydantic",
    "uvicorn",
)


def test_domain_has_no_framework_imports() -> None:
    violations: list[str] = []
    for module in module_names():
        domain_dir = modules_root() / module / "domain"
        if not domain_dir.exists():
            continue
        for source in python_files(domain_dir):
            for imported in source.imports:
                if imported.split(".")[0] in FORBIDDEN:
                    violations.append(f"{source.rel} -> {imported}")
    assert not violations, "domain/ 引入了框架依赖：\n" + "\n".join(violations)

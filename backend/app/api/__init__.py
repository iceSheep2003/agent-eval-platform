"""HTTP 层的共享设施：错误映射、依赖、路由前缀。

`/api/*` 是**兼容面**（前端 `frontend-pro` 与 `examples/.../register.py` 已在用），
`/v1/*` 是**机器面**（Agent Gateway 与 Trace Ingest）。两者不重叠，不要互相搬家。
"""

from __future__ import annotations

#: 控制台接口的两个挂载前缀，指向同一批 router。
CONSOLE_PREFIXES: tuple[str, ...] = ("/api", "/api/v1")

#: 机器面前缀，只挂一次。
MACHINE_PREFIX = "/v1"

__all__ = ["CONSOLE_PREFIXES", "MACHINE_PREFIX"]

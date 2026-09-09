"""跨模块契约层。

**只描述边界，不描述实现**：这里不出现 FastAPI、SQLAlchemy、HTTP 客户端。
模块之间只能 import 本包，禁止 import 其他模块的 domain / infrastructure。

契约的生长规则见 docs/backend-contracts.md §14 与实施计划 §二：
契约包只在「第一次出现真实跨模块调用」时创建，且只加被真正调用的那一个 Protocol。
`tests/architecture/test_no_unused_contracts.py` 会强制这一点。
"""

from __future__ import annotations

#: 契约版本。0.x 阶段允许破坏性变更；出现第一个外部消费者（前端接真数据 / 独立部署）后升 1.0.0。
CONTRACT_VERSION = "0.1.0"

__all__ = ["CONTRACT_VERSION"]

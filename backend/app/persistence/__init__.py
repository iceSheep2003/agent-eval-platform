"""持久化基线。

各模块的表定义放在自己的 `infrastructure/tables.py`，迁移放在 `migrations/<module>/`，
互不干扰——这是并行开发不撞 Alembic 版本号的关键。
平台级表（Outbox）以 `platform_` 前缀命名，不归属任何业务模块。
"""

from .base import Base, TimestampMixin, WorkspaceScopedMixin, utcnow
from .database import Database
from .engine import create_engine
from .outbox import (
    Command,
    CommandOutboxRow,
    CommandQueue,
    CommandStatus,
    EventOutboxRow,
    QueueConfig,
)
from .unit_of_work import UnitOfWork

__all__ = [
    "Base",
    "Command",
    "CommandOutboxRow",
    "CommandQueue",
    "CommandStatus",
    "Database",
    "EventOutboxRow",
    "QueueConfig",
    "TimestampMixin",
    "UnitOfWork",
    "WorkspaceScopedMixin",
    "create_engine",
    "utcnow",
]

"""时间抽象。

领域层不允许直接调用 `datetime.now()`——测试需要可注入的固定时间，
而门禁、会话过期、租约续期都依赖时间。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """返回带时区的当前时间（UTC）。"""
        ...


class SystemClock:
    """生产实现。"""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class FixedClock:
    """测试实现。时间只在显式调用 advance() 时前进。"""

    current: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float = 0, **kwargs: float) -> datetime:
        self.current = self.current + timedelta(seconds=seconds, **kwargs)
        return self.current


def ensure_aware(value: datetime) -> datetime:
    """把 naive datetime 视为 UTC；已是 aware 则原样返回。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

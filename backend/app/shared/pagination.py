"""游标分页。

Trace / Span 量级大，不用 offset（深分页会随页码线性变慢，且翻页时数据漂移）。
游标是不透明的 base64(JSON)，只由服务端生成，客户端不得解析或构造。
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class InvalidCursor(ValueError):
    """游标无法解析——调用方应返回 422 而不是静默从头开始。"""


def encode_cursor(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> dict[str, Any]:
    if not value:
        raise InvalidCursor("游标为空")
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        parsed = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCursor(f"游标无法解析: {value!r}") from exc
    if not isinstance(parsed, dict):
        raise InvalidCursor("游标结构非法")
    return parsed


def normalize_limit(limit: int | None) -> int:
    """把外部传入的 limit 收敛到 [1, MAX_LIMIT]。"""
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        raise InvalidCursor("limit 必须大于 0")
    return min(limit, MAX_LIMIT)


@dataclass(frozen=True, slots=True)
class CursorPage:
    """仓储返回的分页结果。`next_cursor` 为 None 表示已到末尾。"""

    items: tuple[Any, ...]
    next_cursor: str | None
    total: int | None = None

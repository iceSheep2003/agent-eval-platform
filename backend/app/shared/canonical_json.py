"""规范化 JSON 与摘要。

`spec_digest`、`template_snapshot` 的比对都依赖「同样的内容得到同样的字符串」，
所以必须固定键序、分隔符和浮点表示，不能依赖 dict 的插入顺序。
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Mapping

_SENTINEL = object()


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        # 统一成字符串，避免 float 精度导致同一笔金额算出不同摘要
        return format(value.normalize(), "f")
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"无法规范化的类型: {type(value).__name__}")


def canonical_dumps(value: Any) -> str:
    """稳定序列化：键排序、无多余空白、UTF-8 原文。"""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    """sha256 十六进制摘要，用作 spec_digest / artifact 校验值。"""
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def same_content(left: Any, right: Any) -> bool:
    """内容等价判断，忽略键序与 Decimal/float 的表示差异。"""
    return digest(left) == digest(right)


def pick(mapping: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    """按给定键取出子集，缺键则填 _SENTINEL（供变更检测使用）。"""
    return {key: mapping.get(key, _SENTINEL) for key in keys}

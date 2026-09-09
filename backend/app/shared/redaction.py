"""字段级脱敏。

Trace 的输入输出里混着 Authorization 头、Cookie、API Key、租户凭证。
这些内容一旦落库或发给 Sink 就是泄露，所以脱敏必须发生在**写入之前**，
而不是查询时——查询时脱敏意味着库里已经存了明文。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

MASK = "[REDACTED]"

#: 命中即整体替换。全部小写比较，`authorization` / `Authorization` 一视同仁。
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "apikey",
        "api-key",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "password",
        "passwd",
        "secret",
        "private_key",
        "session_token",
        "x-csrf-token",
    }
)

#: 值本身像密钥时，即使键名正常也替换（例如 {"note": "Bearer sk-xxx"}）。
_VALUE_PREFIXES: tuple[str, ...] = ("bearer ", "basic ", "evl_", "evk_", "evs_", "sk-")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return lowered in SENSITIVE_KEYS or lowered.endswith("_secret") or lowered.endswith("_token")


def _looks_like_secret(value: str) -> bool:
    lowered = value.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _VALUE_PREFIXES)


def redact(value: Any, *, extra_keys: Iterable[str] = ()) -> Any:
    """递归脱敏，返回新对象，不修改入参。"""
    extra = {k.strip().lower() for k in extra_keys}
    return _redact(value, extra)


def _redact(value: Any, extra: set[str]) -> Any:
    if isinstance(value, Mapping):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and (_is_sensitive_key(key) or key.strip().lower() in extra):
                result[key] = MASK
            else:
                result[key] = _redact(item, extra)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item, extra) for item in value]
    if isinstance(value, str) and _looks_like_secret(value):
        return MASK
    return value


def truncate(value: str, limit: int) -> str:
    """超长内容截断并标记，避免单字段撑爆日志。"""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}…[truncated {len(value) - limit} chars]"

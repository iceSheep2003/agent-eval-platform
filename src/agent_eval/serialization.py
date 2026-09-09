"""Safe JSON conversion, redaction, and bounded value references."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping


DEFAULT_REDACT_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
}


def _redact_key(key: str, redact_keys: set[str]) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in redact_keys or any(part in lowered for part in ("api_key", "token", "password", "secret"))


def safe_json(value: Any, *, redact_keys: set[str] | None = None, _depth: int = 0) -> Any:
    """Return a JSON-compatible value without allowing logging to raise."""

    keys = redact_keys or DEFAULT_REDACT_KEYS
    if _depth > 12:
        return {"_type": type(value).__name__, "_truncated": "max_depth"}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"_type": "bytes", "size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _redact_key(str(key), keys) else safe_json(item, redact_keys=keys, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [safe_json(item, redact_keys=keys, _depth=_depth + 1) for item in value]
    if is_dataclass(value):
        return safe_json(asdict(value), redact_keys=keys, _depth=_depth + 1)
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError, OverflowError):
        return {"_type": type(value).__name__, "repr": repr(value)[:500]}


def json_dumps(value: Any) -> str:
    return json.dumps(safe_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bounded_ref(
    value: Any,
    *,
    max_chars: int,
    capture: bool = True,
    redact_keys: set[str] | None = None,
) -> Any | None:
    if not capture:
        return None
    converted = safe_json(value, redact_keys=redact_keys)
    try:
        encoded = json.dumps(converted, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, OverflowError):
        converted = {"_type": type(value).__name__, "repr": repr(value)[:500]}
        encoded = json.dumps(converted, ensure_ascii=False)
    if len(encoded) <= max_chars:
        return {"inline": converted, "size": len(encoded)}
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "inline": {"_truncated": True, "preview": encoded[: max(0, max_chars // 2)]},
        "size": len(encoded),
        "sha256": digest,
        "artifact_required": True,
    }


def unwrap_ref(ref: Any) -> Any:
    if isinstance(ref, Mapping) and "inline" in ref:
        return ref["inline"]
    return ref


"""密钥与令牌的生成、哈希与比较。

**库里永远不存明文**：会话 token、`evk_`/`evl_`/`evs_` 凭证都只存 sha256，
明文只在创建响应里出现一次。
"""

from __future__ import annotations

import hashlib
import secrets

DEFAULT_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 24


def new_secret(bytes_: int = DEFAULT_TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(bytes_)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)


def last_four(value: str) -> str:
    """展示用的末四位，用于让用户辨认是哪把钥匙。"""
    return value[-4:]

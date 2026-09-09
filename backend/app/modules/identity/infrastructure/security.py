"""会话令牌。

密码哈希已经上移到 `shared.passwords`——portal 也要用同一套 argon2id 参数。
本模块只保留「会话」这一层，并对外转出共享工具，避免会话与机器凭证各写一套。
"""

from __future__ import annotations

from ....shared.passwords import (  # noqa: F401  (对外转出，模块内直接复用)
    hash_password,
    needs_rehash,
    verify_password,
)
from ....shared.secrets import (  # noqa: F401  (对外转出，模块内直接复用)
    constant_time_equals,
    hash_secret as hash_token,
    new_csrf_token,
    new_secret,
)


def new_session_token() -> str:
    return new_secret()


__all__ = [
    "constant_time_equals",
    "hash_password",
    "hash_token",
    "needs_rehash",
    "new_csrf_token",
    "new_session_token",
    "verify_password",
]

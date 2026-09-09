"""密码哈希与会话令牌。

密码用 argon2id（内存硬 KDF）。令牌的生成/哈希/比较复用 `shared.secrets`，
避免会话与机器凭证各写一套。
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from ....shared.secrets import (  # noqa: F401  (对外转出，模块内直接复用)
    constant_time_equals,
    hash_secret as hash_token,
    new_csrf_token,
    new_secret,
)

_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(stored_hash: str | None, raw: str) -> bool:
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


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

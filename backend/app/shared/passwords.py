"""密码哈希。

argon2id（内存硬 KDF）。平台账号（identity）与展示平台账号（portal）是两套账号，
但**哈希方式必须一致**——放这里，避免两边各写一份而慢慢跑偏。
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

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


__all__ = ["hash_password", "needs_rehash", "verify_password"]

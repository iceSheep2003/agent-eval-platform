"""对称加密：资源密钥的**可解密**存储。

这里和 `shared/secrets.py` 是两件不同的事：

- `secrets.hash_secret` —— 平台凭证（`evk_` / `evl_`）。**只验不改**，所以只存
  哈希，泄露数据库也拿不到可用凭证；
- 本模块 —— 资源密钥（LLM API Key、MCP Token）。运行时必须**还原成明文**注入
  给 Agent，所以必须可逆，只能用加密。

密钥来自 `Settings.master_key`（开发态落本地文件、生产态强制外部注入，
**不进数据库**）。派生用 HKDF-SHA256，每个用途一个独立子密钥——
这样将来加「加密别的字段」不会复用到同一个密钥流。
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: HKDF 的信息串。换用途就换它，不要复用同一把子密钥。
_PURPOSE = b"eval-loom:resource-secret:v1"

_SALT = b"eval-loom:static-salt"  # 主密钥已是高熵随机值，固定 salt 足够


class SecretDecryptionError(RuntimeError):
    """密文解不开——主密钥换了，或者数据被篡改（Fernet 带认证）。"""


def _fernet(master_key: str) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=_PURPOSE,
    ).derive(master_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def seal(master_key: str, plaintext: str) -> str:
    """加密。返回可直接入库的字符串（Fernet token，urlsafe base64）。"""
    if not master_key:
        raise ValueError("主密钥为空——无法加密资源密钥")
    return _fernet(master_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def open_sealed(master_key: str, ciphertext: str) -> str:
    """解密。**解不开就抛**，绝不返回空串——静默降级会让 Agent 拿不到密钥却继续跑。"""
    if not master_key:
        raise SecretDecryptionError("主密钥为空——无法解密资源密钥")
    try:
        return _fernet(master_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptionError(
            "密文无法解密：主密钥已更换，或数据被篡改"
        ) from exc


def fingerprint(plaintext: str) -> str:
    """短指纹，用于日志与展示（「用的是哪一把」），**不可反推明文**。"""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:12]


def new_master_key() -> str:
    """生成一把新的主密钥（运维轮换时用）。"""
    return base64.urlsafe_b64encode(os.urandom(48)).decode("ascii")


__all__ = [
    "SecretDecryptionError",
    "fingerprint",
    "new_master_key",
    "open_sealed",
    "seal",
]

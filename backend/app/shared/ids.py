"""带前缀的有序 ID。

无第三方依赖：48-bit 毫秒时间戳 + 80-bit 随机数的 Crockford Base32 编码（ULID 形状）。
同一毫秒内自增随机部分，保证单调；ID 可直接按字符串排序等于按时间排序。

    >>> new_id("run")
    'run_01J8Z9K3M4N5P6Q7R8S9T0V1W2'
"""

from __future__ import annotations

import os
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIME_CHARS = 10
_RANDOM_CHARS = 16
_MAX_TIME = (1 << 48) - 1
_MAX_RANDOM = (1 << 80) - 1

#: 实体类型 → ID 前缀。新增实体时必须在此登记，避免前缀散落在业务代码里。
PREFIXES: dict[str, str] = {
    # identity
    "organization": "org",
    "workspace": "ws",
    "user": "usr",
    "session": "ses",
    "membership": "mem",
    "tenant": "tn",
    "invitation": "inv",
    "identity_provider": "idp",
    "federated_identity": "fed",
    # asset
    "asset": "ast",
    "version": "ver",
    "channel_binding": "cb",
    "binding": "bnd",
    "credential": "cred",
    "artifact": "art",
    "secret": "sec",
    "secret_binding": "sb",
    # dataset
    "dataset": "ds",
    "dataset_version": "dsv",
    "sample": "smp",
    "import_session": "imp",
    # evaluation
    "capability": "cap",
    "dimension": "dim",
    "evaluator": "ev",
    "template": "tpl",
    "gate_rule": "gr",
    # execution
    "run": "run",
    "trial": "trl",
    "command": "cmd",
    #: 网关/展示平台发起的一次调用（与 Run 无关，仅用于关联 Trace）
    "invocation": "inv",
    # observability
    "trace": "trc",
    "span": "spn",
    "event": "evt",
    "score": "scr",
    # portal（展示平台，独立账号体系）
    "portal_user": "pu",
    "portal_session": "ps",
    "portal_hub": "ph",
    "portal_hub_member": "pm",
    "portal_agent": "pa",
    "portal_channel": "pc",
    # improvement
    "proposal": "prp",
    "regression_sample": "rsm",
    # delivery
    "promotion": "prm",
    "rollback": "rbk",
    "shadow_route": "shr",
    # 横切
    "audit": "aud",
}

_PREFIX_TO_KIND = {v: k for k, v in PREFIXES.items()}

_lock = threading.Lock()
_last_time = 0
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid() -> str:
    """返回 26 字符的 ULID 字符串（不含前缀）。"""
    global _last_time, _last_random
    with _lock:
        now = int(time.time() * 1000) & _MAX_TIME
        if now == _last_time:
            _last_random = (_last_random + 1) & _MAX_RANDOM
        else:
            _last_time = now
            _last_random = int.from_bytes(os.urandom(10), "big")
        return _encode(now, _TIME_CHARS) + _encode(_last_random, _RANDOM_CHARS)


def new_id(kind: str) -> str:
    """按实体类型生成带前缀的 ID。未知类型直接报错，防止拼写错误静默产生新前缀。"""
    try:
        prefix = PREFIXES[kind]
    except KeyError:
        raise KeyError(
            f"未登记的 ID 类型 {kind!r}；请先在 shared.ids.PREFIXES 中登记前缀"
        ) from None
    return f"{prefix}_{new_ulid()}"


def split_id(value: str) -> tuple[str, str]:
    """拆出 (kind, ulid)。前缀未登记时抛出 ValueError。"""
    prefix, _, ulid = value.partition("_")
    kind = _PREFIX_TO_KIND.get(prefix)
    if kind is None or len(ulid) != _TIME_CHARS + _RANDOM_CHARS:
        raise ValueError(f"非法 ID: {value!r}")
    return kind, ulid


def is_valid_id(value: str, kind: str | None = None) -> bool:
    try:
        actual_kind, _ = split_id(value)
    except ValueError:
        return False
    return kind is None or actual_kind == kind

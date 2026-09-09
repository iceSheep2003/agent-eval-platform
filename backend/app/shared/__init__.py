"""技术内核：无业务含义的共享工具。

只放「任何模块都可能用、且不表达业务规则」的东西。一旦某个工具开始表达业务
（比如"什么算通过门禁"），它就该搬到对应模块的 domain 里。
"""

from .canonical_json import canonical_dumps, digest, same_content
from .clock import Clock, FixedClock, SystemClock, ensure_aware
from .ids import PREFIXES, is_valid_id, new_id, new_ulid, split_id
from .pagination import CursorPage, InvalidCursor, decode_cursor, encode_cursor, normalize_limit
from .redaction import MASK, redact, truncate

__all__ = [
    "Clock",
    "CursorPage",
    "FixedClock",
    "InvalidCursor",
    "MASK",
    "PREFIXES",
    "SystemClock",
    "canonical_dumps",
    "decode_cursor",
    "digest",
    "encode_cursor",
    "ensure_aware",
    "is_valid_id",
    "new_id",
    "new_ulid",
    "normalize_limit",
    "redact",
    "same_content",
    "split_id",
    "truncate",
]

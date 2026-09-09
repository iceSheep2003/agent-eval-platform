"""Agent 版本 spec 的校验与摘要。

spec 是「怎么把这个版本跑起来」的结构化配置。校验必须发生在**冻结版本之前**——
版本一旦落库就不可变，配置错误只能在下一个版本修。
"""

from __future__ import annotations

from typing import Any, Mapping

from .....contracts.common import AssetKind, ValidationIssue, ValidationResult
from .....shared.canonical_json import digest as _digest

CONNECT_TYPES = ("sdk", "github", "package")

#: 每种接入方式必须提供的字段。
_REQUIRED_BY_CONNECT: Mapping[str, tuple[str, ...]] = {
    "sdk": (),
    "github": ("repository", "ref", "entrypoint"),
    "package": ("artifact_id", "entrypoint"),
}


def validate(spec: Mapping[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []

    kind = spec.get("kind")
    if kind != AssetKind.AGENT.value:
        issues.append(ValidationIssue("kind", "invalid_kind", f"应为 agent，收到 {kind!r}"))

    connect_type = spec.get("connect_type")
    if connect_type not in CONNECT_TYPES:
        issues.append(
            ValidationIssue(
                "connect_type", "invalid_connect_type", f"应为 {CONNECT_TYPES} 之一"
            )
        )
        return ValidationResult.failure(*issues)

    for field in _REQUIRED_BY_CONNECT[connect_type]:
        if not spec.get(field):
            issues.append(ValidationIssue(field, "missing", f"{connect_type} 接入必须提供 {field}"))

    runtime = spec.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, Mapping):
            issues.append(ValidationIssue("runtime", "invalid", "应为对象"))
        else:
            port = runtime.get("port")
            if port is not None and not (1 <= int(port) <= 65535):
                issues.append(ValidationIssue("runtime.port", "range", "端口应在 1–65535"))

    return ValidationResult.success() if not issues else ValidationResult.failure(*issues)


def digest(spec: Mapping[str, Any]) -> str:
    """同一份配置必须得到同一个摘要，用于「内容相同的版本」去重。"""
    return _digest(dict(spec))

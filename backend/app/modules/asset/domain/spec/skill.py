"""Skill 版本 spec 的校验与摘要。

Skill 没有自己的 entrypoint——它只在宿主 Agent 的步骤里被调用。
因此 spec 描述的是**运行时契约**（指令、输入输出形状、可调用的工具、步数与超时），
而不是「怎么把它启动起来」。

校验必须发生在**冻结版本之前**：版本一旦落库就不可变，配置错误只能在下一个版本修。
"""

from __future__ import annotations

from typing import Any, Mapping

from .....contracts.common import AssetKind, ValidationIssue, ValidationResult
from .....shared.canonical_json import digest as _digest

MIN_STEPS = 1
MIN_TIMEOUT_MS = 100


def validate(spec: Mapping[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []

    kind = spec.get("kind")
    if kind != AssetKind.SKILL.value:
        issues.append(ValidationIssue("kind", "invalid_kind", f"应为 skill，收到 {kind!r}"))

    instructions = spec.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        issues.append(ValidationIssue("instructions", "missing", "Skill 必须有非空的核心指令"))

    max_steps = spec.get("max_steps")
    if not isinstance(max_steps, int) or isinstance(max_steps, bool):
        issues.append(ValidationIssue("max_steps", "invalid", "应为整数"))
    elif max_steps < MIN_STEPS:
        issues.append(ValidationIssue("max_steps", "range", f"至少 {MIN_STEPS} 步"))

    timeout_ms = spec.get("timeout_ms")
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        issues.append(ValidationIssue("timeout_ms", "invalid", "应为整数毫秒"))
    elif timeout_ms < MIN_TIMEOUT_MS:
        issues.append(ValidationIssue("timeout_ms", "range", f"至少 {MIN_TIMEOUT_MS}ms"))

    allowed_tools = spec.get("allowed_tools")
    if allowed_tools is not None:
        if not isinstance(allowed_tools, (list, tuple)):
            issues.append(ValidationIssue("allowed_tools", "invalid", "应为字符串数组"))
        else:
            names = [item for item in allowed_tools if isinstance(item, str) and item.strip()]
            if len(names) != len(allowed_tools):
                issues.append(
                    ValidationIssue("allowed_tools", "invalid", "每一项都必须是非空字符串")
                )
            elif len(set(names)) != len(names):
                issues.append(ValidationIssue("allowed_tools", "duplicate", "工具名不能重复"))

    for field in ("input_schema", "output_schema"):
        value = spec.get(field)
        if value is not None and not isinstance(value, Mapping):
            issues.append(ValidationIssue(field, "invalid", "应为 JSON Schema 对象"))

    return ValidationResult.success() if not issues else ValidationResult.failure(*issues)


def digest(spec: Mapping[str, Any]) -> str:
    """同一份配置必须得到同一个摘要，用于「内容相同的版本」去重。"""
    return _digest(dict(spec))

"""MCP 版本 spec 的校验与摘要。

`tools[].name` 是**归因的锚点**：生产 Trace 里的 tool span 靠它匹配回具体的 MCP 资产。
所以工具名必须稳定且唯一——改名等于换了一个工具，视为新版本而不是改名。
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .....contracts.common import AssetKind, ValidationIssue, ValidationResult
from .....shared.canonical_json import digest as _digest

TRANSPORTS = ("stdio", "sse", "streamable-http")

#: 工具名：小写字母开头，允许数字、下划线、点、连字符。
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_.-]*$")

#: 这些 key 一旦出现在 spec 里，说明有人把明文密钥写进了不可变版本——直接拒绝。
_PLAINTEXT_KEYS = ("password", "token", "api_key", "apikey", "secret")


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def validate(spec: Mapping[str, Any]) -> ValidationResult:
    issues: list[ValidationIssue] = []

    kind = spec.get("kind")
    if kind != AssetKind.MCP.value:
        issues.append(ValidationIssue("kind", "invalid_kind", f"应为 mcp，收到 {kind!r}"))

    endpoint = spec.get("endpoint")
    transport = spec.get("transport")
    if not isinstance(endpoint, str) or not endpoint.strip():
        issues.append(ValidationIssue("endpoint", "missing", "必须提供 endpoint"))
    elif transport in TRANSPORTS:
        if transport == "stdio" and _is_http_url(endpoint):
            issues.append(
                ValidationIssue("endpoint", "invalid", "stdio 传输的 endpoint 应是启动命令，不是 URL")
            )
        if transport != "stdio" and not _is_http_url(endpoint):
            issues.append(
                ValidationIssue("endpoint", "invalid", f"{transport} 传输的 endpoint 必须是 http(s) URL")
            )

    if transport not in TRANSPORTS:
        issues.append(
            ValidationIssue("transport", "invalid_transport", f"应为 {TRANSPORTS} 之一")
        )

    tools = spec.get("tools")
    if tools is not None and not isinstance(tools, (list, tuple)):
        issues.append(ValidationIssue("tools", "invalid", "应为工具数组"))
    elif isinstance(tools, (list, tuple)):
        seen: set[str] = set()
        for index, tool in enumerate(tools):
            field = f"tools[{index}]"
            if not isinstance(tool, Mapping):
                issues.append(ValidationIssue(field, "invalid", "应为对象"))
                continue
            name = tool.get("name")
            if not isinstance(name, str) or not _TOOL_NAME.match(name):
                issues.append(
                    ValidationIssue(f"{field}.name", "invalid_name", "需匹配 ^[a-z][a-z0-9_.-]*$")
                )
            elif name in seen:
                issues.append(ValidationIssue(f"{field}.name", "duplicate", f"工具名 {name} 重复"))
            else:
                seen.add(name)
            if "input_schema" in tool and not isinstance(tool.get("input_schema"), Mapping):
                issues.append(ValidationIssue(f"{field}.input_schema", "invalid", "应为对象"))

    auth = spec.get("authentication")
    if auth is not None:
        if not isinstance(auth, Mapping):
            issues.append(ValidationIssue("authentication", "invalid", "应为对象"))
        else:
            if not auth.get("type"):
                issues.append(ValidationIssue("authentication.type", "missing", "必须声明鉴权类型"))
            for key in auth:
                if key.lower() in _PLAINTEXT_KEYS:
                    issues.append(
                        ValidationIssue(
                            f"authentication.{key}",
                            "plaintext_secret",
                            "版本不可变，禁止把明文密钥写进 spec；只存 secret_ref",
                        )
                    )

    return ValidationResult.success() if not issues else ValidationResult.failure(*issues)


def digest(spec: Mapping[str, Any]) -> str:
    return _digest(dict(spec))

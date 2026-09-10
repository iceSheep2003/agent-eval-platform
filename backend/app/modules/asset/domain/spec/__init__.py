"""按资产类型分派的 spec 校验器。

四类资产共用「身份 + 不可变版本 + 通道指针」骨架，差异全部收敛到这里的校验器：
新增一类资产 = 新增一个文件 + 在 `_VALIDATORS` 里注册，不动骨架、不动表。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .....contracts.common import AssetKind, ValidationResult


@runtime_checkable
class SpecValidator(Protocol):
    def validate(self, spec: Mapping[str, Any]) -> ValidationResult: ...
    def digest(self, spec: Mapping[str, Any]) -> str: ...


#: 能力资产 = 会被 Agent 引用的三类资源。Agent 自己不是能力资产，它是消费方。
CAPABILITY_KINDS: tuple[AssetKind, ...] = (
    AssetKind.SKILL,
    AssetKind.MCP,
    AssetKind.KNOWLEDGE_BASE,
)


def validator_for(kind: AssetKind) -> SpecValidator:
    if kind is AssetKind.AGENT:
        from . import agent

        return agent
    if kind is AssetKind.SKILL:
        from . import skill

        return skill
    if kind is AssetKind.MCP:
        from . import mcp

        return mcp
    if kind is AssetKind.KNOWLEDGE_BASE:
        from . import knowledge_base

        return knowledge_base
    raise NotImplementedError(f"{kind} 的 spec 校验器尚未实现")


def is_capability(kind: AssetKind) -> bool:
    return kind in CAPABILITY_KINDS


def conformance_for(kind: AssetKind):
    """拿某类资产的**规范校验器**。目前只有 Agent 有——能力资产的规范各自定义。"""
    if kind is AssetKind.AGENT:
        from . import conformance

        return conformance
    return None


__all__ = [
    "CAPABILITY_KINDS",
    "SpecValidator",
    "conformance_for",
    "is_capability",
    "validator_for",
]

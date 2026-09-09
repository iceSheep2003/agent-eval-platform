"""按资产类型分派的 spec 校验器。

M1 只有 agent；P2 加 skill / mcp / knowledge_base 时只新增文件，不动骨架。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .....contracts.common import AssetKind, ValidationResult


@runtime_checkable
class SpecValidator(Protocol):
    def validate(self, spec: Mapping[str, Any]) -> ValidationResult: ...
    def digest(self, spec: Mapping[str, Any]) -> str: ...


def validator_for(kind: AssetKind) -> SpecValidator:
    if kind is AssetKind.AGENT:
        from . import agent

        return agent
    raise NotImplementedError(f"{kind} 的 spec 校验器尚未实现（P2 接入）")

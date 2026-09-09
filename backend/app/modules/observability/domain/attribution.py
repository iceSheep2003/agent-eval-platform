"""把 Span 归因到能力资产版本。

**纯函数、无 IO**：输入是 Span 的判别字段与候选清单，输出是归因结果或 None。
这样归因规则可以在单测里逐条验证，不依赖数据库。

三条纪律：

1. **不猜**。候选多于一个时返回 None，而不是挑一个「看起来像」的。
2. **不改 SDK 事件形状**。归因只用 Span 已有的 `kind` / `name` / `attributes`，
   SDK 不需要上报资源 ID。
3. **标注来源**。`declared` = 来自 Run 的冻结快照（评测 Trace，精确）；
   `resolved` = 按规则匹配出来（生产 Trace，近似）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from ....contracts.asset import CapabilityAttributionRef
from ....contracts.common import AssetKind, Id

#: Span 类型 → 能归因到哪类能力资产。
SPAN_KIND_TO_ASSET_KIND: Mapping[str, AssetKind] = {
    "tool": AssetKind.MCP,
    "retriever": AssetKind.KNOWLEDGE_BASE,
    "agent": AssetKind.SKILL,
}

#: 工具名可能出现在这几个 attributes key 上（不同 SDK / 框架命名不同）。
_TOOL_NAME_KEYS = ("tool_name", "mcp.tool.name", "gen_ai.tool.name")

#: 索引名可能出现的 key。
_INDEX_NAME_KEYS = ("index_name", "retrieval.index_name", "kb.index_name")

AttributionSource = Literal["declared", "resolved"]


@dataclass(frozen=True, slots=True)
class Attribution:
    asset_id: Id
    version_id: Id
    source: AttributionSource


def _candidates(targets: Sequence[CapabilityAttributionRef], kind: AssetKind) -> list[CapabilityAttributionRef]:
    return [item for item in targets if item.kind is kind]


def _first_attr(attributes: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _matches(
    target: CapabilityAttributionRef,
    span_kind: str,
    name: str,
    attributes: Mapping[str, Any],
) -> bool:
    if span_kind == "tool":
        tool_name = _first_attr(attributes, _TOOL_NAME_KEYS) or name
        return tool_name in target.names
    if span_kind == "retriever":
        index_name = _first_attr(attributes, _INDEX_NAME_KEYS) or name
        return index_name in target.names
    if span_kind == "agent":
        return name in target.names
    return False


def attribute_span(
    *,
    span_kind: str,
    name: str,
    attributes: Mapping[str, Any],
    targets: Sequence[CapabilityAttributionRef],
    source: AttributionSource,
) -> Attribution | None:
    """给一个 Span 找唯一的能力资产版本；找不到或多解返回 None。"""
    expected = SPAN_KIND_TO_ASSET_KIND.get(span_kind)
    if expected is None:
        return None
    hits = [
        target
        for target in _candidates(targets, expected)
        if _matches(target, span_kind, name, attributes)
    ]
    if len(hits) != 1:
        return None
    return Attribution(asset_id=hits[0].asset_id, version_id=hits[0].version_id, source=source)


__all__ = ["Attribution", "AttributionSource", "SPAN_KIND_TO_ASSET_KIND", "attribute_span"]

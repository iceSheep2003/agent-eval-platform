"""归因是纯函数，逐条规则单测——不依赖数据库。

最重要的一条：**多解不猜**。两个候选都匹配时返回 None，
宁可这条 Span 没有归因，也不要把它算到错的版本上。
"""

from __future__ import annotations

from backend.app.contracts.asset import CapabilityAttributionRef
from backend.app.contracts.common import AssetKind
from backend.app.modules.observability.domain.attribution import attribute_span

MCP = CapabilityAttributionRef(
    asset_id="ast_mcp", version_id="ver_mcp", kind=AssetKind.MCP, names=frozenset({"lookup_order"})
)
KB = CapabilityAttributionRef(
    asset_id="ast_kb",
    version_id="ver_kb",
    kind=AssetKind.KNOWLEDGE_BASE,
    names=frozenset({"policy-index"}),
)
SKILL = CapabilityAttributionRef(
    asset_id="ast_skill",
    version_id="ver_skill",
    kind=AssetKind.SKILL,
    names=frozenset({"refund-policy"}),
)


def _attribute(span_kind, name, attributes=None, targets=(MCP, KB, SKILL), source="resolved"):
    return attribute_span(
        span_kind=span_kind,
        name=name,
        attributes=attributes or {},
        targets=list(targets),
        source=source,  # type: ignore[arg-type]
    )


def test_tool_span_matches_mcp_by_name() -> None:
    hit = _attribute("tool", "lookup_order")
    assert hit is not None
    assert hit.asset_id == "ast_mcp" and hit.version_id == "ver_mcp"


def test_tool_span_matches_by_attribute_when_name_is_generic() -> None:
    hit = _attribute("tool", "call_tool", {"tool_name": "lookup_order"})
    assert hit is not None and hit.asset_id == "ast_mcp"


def test_retriever_span_matches_kb_by_index_name() -> None:
    hit = _attribute("retriever", "search", {"index_name": "policy-index"})
    assert hit is not None and hit.asset_id == "ast_kb"


def test_agent_span_matches_skill_by_name() -> None:
    hit = _attribute("agent", "refund-policy")
    assert hit is not None and hit.asset_id == "ast_skill"


def test_llm_span_is_never_attributed() -> None:
    """LLM 调用不属于任何能力资产——不要为了凑数据硬归因。"""
    assert _attribute("llm", "lookup_order") is None


def test_unknown_name_is_not_attributed() -> None:
    assert _attribute("tool", "delete_everything") is None


def test_ambiguous_match_returns_none() -> None:
    """两个 MCP 都声明了同名工具 → 归不了因，返回 None。"""
    twin = CapabilityAttributionRef(
        asset_id="ast_mcp2",
        version_id="ver_mcp2",
        kind=AssetKind.MCP,
        names=frozenset({"lookup_order"}),
    )
    assert _attribute("tool", "lookup_order", targets=(MCP, twin)) is None


def test_source_is_carried_through() -> None:
    hit = _attribute("tool", "lookup_order", source="declared")
    assert hit is not None and hit.source == "declared"

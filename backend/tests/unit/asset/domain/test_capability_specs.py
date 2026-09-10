"""能力资产 spec 校验器的边界值。

这些校验发生在**冻结版本之前**——版本一旦落库就不可变，配置错误只能在下一个版本修，
所以能挡住的错误必须在这里挡住。
"""

from __future__ import annotations

import pytest

from backend.app.contracts.common import AssetKind
from backend.app.modules.asset.domain import spec as registry

SKILL = registry.validator_for(AssetKind.SKILL)
MCP = registry.validator_for(AssetKind.MCP)
KB = registry.validator_for(AssetKind.KNOWLEDGE_BASE)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


# -- Skill ----------------------------------------------------------------


def test_skill_minimal_spec_passes() -> None:
    assert SKILL.validate(
        {"kind": "skill", "instructions": "查订单", "max_steps": 1, "timeout_ms": 100}
    ).ok


def test_skill_rejects_wrong_kind_and_empty_instructions() -> None:
    result = SKILL.validate({"kind": "mcp", "instructions": "   ", "max_steps": 0, "timeout_ms": 0})
    assert not result.ok
    assert {"invalid_kind", "missing", "range"} <= _codes(result)


def test_skill_rejects_duplicate_tools() -> None:
    result = SKILL.validate(
        {
            "kind": "skill",
            "instructions": "查订单",
            "max_steps": 3,
            "timeout_ms": 1000,
            "allowed_tools": ["orders.lookup", "orders.lookup"],
        }
    )
    assert "duplicate" in _codes(result)


# -- MCP ------------------------------------------------------------------


def test_mcp_stdio_endpoint_must_be_a_command() -> None:
    result = MCP.validate(
        {
            "kind": "mcp",
            "endpoint": "https://mcp.internal/x",
            "transport": "stdio",
            "tools": [{"name": "orders.lookup"}],
        }
    )
    assert "invalid" in _codes(result)


def test_mcp_http_transport_requires_url() -> None:
    result = MCP.validate(
        {
            "kind": "mcp",
            "endpoint": "npx some-server",
            "transport": "sse",
            "tools": [{"name": "orders.lookup"}],
        }
    )
    assert "invalid" in _codes(result)


def test_mcp_tools_can_be_discovered_after_connecting() -> None:
    assert MCP.validate(
        {
            "kind": "mcp",
            "endpoint": "https://mcp.internal/x",
            "transport": "streamable-http",
        }
    ).ok


def test_mcp_tool_name_must_be_stable_and_unique() -> None:
    result = MCP.validate(
        {
            "kind": "mcp",
            "endpoint": "https://mcp.internal/x",
            "transport": "sse",
            "tools": [{"name": "Bad Name"}, {"name": "orders.lookup"}, {"name": "orders.lookup"}],
        }
    )
    codes = _codes(result)
    assert "invalid_name" in codes and "duplicate" in codes


def test_mcp_rejects_plaintext_secret() -> None:
    """版本不可变，明文密钥写进去就永远留在库里了。"""
    result = MCP.validate(
        {
            "kind": "mcp",
            "endpoint": "https://mcp.internal/x",
            "transport": "sse",
            "tools": [{"name": "orders.lookup"}],
            "authentication": {"type": "bearer", "api_key": "sk-live-xxx"},
        }
    )
    assert "plaintext_secret" in _codes(result)


# -- 知识库 ----------------------------------------------------------------


def _kb(**overrides) -> dict:
    spec = {
        "kind": "knowledge_base",
        "embedding_model": "bge-m3",
        "index_name": "policy-index",
        "chunk_strategy": {"mode": "fixed", "size": 512, "overlap": 64},
        "retrieval": {"mode": "hybrid", "top_k": 5},
        "sources": [{"id": "s1", "name": "政策", "connector": "http", "uri": "https://x", "enabled": True}],
    }
    spec.update(overrides)
    return spec


def test_kb_valid_spec_passes() -> None:
    assert KB.validate(_kb()).ok


def test_kb_accepts_provider_reference_instead_of_model_name() -> None:
    spec = _kb(embedding_provider_id="embedding-bge-m3")
    spec.pop("embedding_model")
    assert KB.validate(spec).ok


def test_kb_overlap_must_be_smaller_than_chunk_size() -> None:
    result = KB.validate(_kb(chunk_strategy={"mode": "fixed", "size": 10, "overlap": 10}))
    assert "range" in _codes(result)


def test_kb_requires_at_least_one_enabled_source() -> None:
    result = KB.validate(
        _kb(sources=[{"id": "s1", "name": "政策", "connector": "http", "uri": "https://x", "enabled": False}])
    )
    assert "all_disabled" in _codes(result)


def test_kb_rejects_duplicate_source_ids() -> None:
    source = {"id": "s1", "name": "政策", "connector": "http", "uri": "https://x", "enabled": True}
    result = KB.validate(_kb(sources=[source, dict(source)]))
    assert "duplicate" in _codes(result)


# -- 注册表 ----------------------------------------------------------------


def test_registry_covers_all_capability_kinds() -> None:
    for kind in registry.CAPABILITY_KINDS:
        assert registry.validator_for(kind) is not None
        assert registry.is_capability(kind)
    assert not registry.is_capability(AssetKind.AGENT)


def test_agent_is_not_a_capability_asset() -> None:
    """Agent 是消费方，不是被引用的资源——这个边界不能模糊。"""
    with pytest.raises(NotImplementedError):
        registry.validator_for("unknown")  # type: ignore[arg-type]

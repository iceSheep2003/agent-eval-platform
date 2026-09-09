from __future__ import annotations

import asyncio
import json

import pytest

from agent_eval import JsonlSink, configure

from examples.customer_support_agent import (
    Memory,
    PlatformContext,
    configure_agent,
    fetch_platform_context,
    support_agent,
)
from examples.customer_support_agent.llm_client import ChatClient, llm_config_from_env
from examples.customer_support_agent.policy import policy_model

_LLM_ENV = (
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "DASHSCOPE_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
)


@pytest.fixture(autouse=True)
def _clear_llm_and_sinks(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    configure(sinks=[])
    configure_agent()
    yield
    configure(sinks=[])
    configure_agent()


def test_llm_config_is_absent_without_key():
    config = llm_config_from_env()
    assert config.api_key is None
    assert not ChatClient(config).available


def test_chat_returns_none_without_key():
    assert asyncio.run(ChatClient().chat([{"role": "user", "content": "hi"}])) is None


def test_policy_falls_back_to_deterministic():
    assert asyncio.run(policy_model("查询订单 A001", {"found": True, "refundable": True})) == "refund_allowed"
    assert asyncio.run(policy_model("查询订单 A002", {"found": True, "refundable": False})) == "refund_denied"
    assert asyncio.run(policy_model("查询订单 A999", {"found": False})) == "not_found"


def test_support_agent_deterministic_answers():
    assert "可以退款" in asyncio.run(support_agent("请判断订单 A001 是否可以退款"))
    assert "不可退款" in asyncio.run(support_agent("订单 A002 可以退款吗"))
    assert "没有找到订单 A999" in asyncio.run(support_agent("订单 A999 能退款吗"))
    assert "退款政策" in asyncio.run(support_agent("退款政策是什么？"))


def test_offline_run_writes_spans(tmp_path):
    out = tmp_path / "events.jsonl"
    configure(sinks=[JsonlSink(out)])
    asyncio.run(support_agent("请判断订单 A001 是否可以退款"))
    events = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    kinds = {event.get("payload", {}).get("kind") for event in events if event.get("event_type") == "span_started"}
    assert {"agent", "tool", "llm"} <= kinds


def test_memory_persists_turns_and_facts(tmp_path):
    path = tmp_path / "memory.json"
    memory = Memory(path)
    memory.add_turn("user", "查询订单 A001")
    memory.add_fact("order:A001", "delivered")
    memory.save()

    reloaded = Memory(path)
    assert reloaded.turns[-1]["content"] == "查询订单 A001"
    assert reloaded.facts["order:A001"] == "delivered"


def test_memory_recall_matches_facts():
    memory = Memory()
    memory.add_fact("order:A001", "delivered")
    memory.add_fact("order:A002", "refunded")
    assert "delivered" in memory.recall("A001 订单")


def test_agent_uses_platform_knowledge():
    context = PlatformContext(knowledge=[{"title": "退款政策", "content": "签收后 7 天内可申请退款。", "tags": ["退款"]}])
    configure_agent(context=context)
    answer = asyncio.run(support_agent("退款政策是什么？"))
    assert "签收后 7 天内可申请退款" in answer


def test_agent_records_memory_turns():
    memory = Memory()
    configure_agent(memory=memory)
    asyncio.run(support_agent("请判断订单 A001 是否可以退款"))
    assert memory.turns[0]["role"] == "user"
    assert memory.turns[-1]["role"] == "assistant"
    assert memory.facts["order:A001"] == "delivered"


def test_fetch_platform_context_success(monkeypatch):
    import httpx

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "knowledge": [{"title": "退款政策", "content": "7 天内", "tags": ["退款"]}],
                "skills": [{"name": "退款决策", "enabled": True}],
                "mcp_servers": [{"name": "crm", "enabled": True}],
            }

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse())
    context = fetch_platform_context("http://platform", "evk_test")
    assert len(context.knowledge) == 1
    assert context.skills[0]["name"] == "退款决策"
    assert context.mcp_servers[0]["name"] == "crm"


def test_fetch_platform_context_degrades_gracefully(monkeypatch):
    import httpx

    assert not fetch_platform_context("", "")
    assert not fetch_platform_context("http://platform", "")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "get", _boom)
    assert not fetch_platform_context("http://platform", "evk_test")


def test_llm_config_anthropic_backend(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy:8080")
    monkeypatch.setenv("ANTHROPIC_MODEL", "grok-4.5")
    config = llm_config_from_env()
    assert config.backend == "anthropic"
    assert config.model == "grok-4.5"
    assert config.api_key == "sk-test"
    assert config.base_url == "http://proxy:8080"


def test_chat_anthropic_uses_messages_api(monkeypatch):
    import httpx

    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy:8080")
    monkeypatch.setenv("ANTHROPIC_MODEL", "grok-4.5")

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "refund_allowed"}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: _Client())
    out = asyncio.run(ChatClient().chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]))
    assert out == "refund_allowed"
    assert captured["url"].endswith("/v1/messages")
    assert captured["json"]["system"] == "sys"
    assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
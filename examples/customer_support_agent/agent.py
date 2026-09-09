"""Top-level customer-support agent with memory, platform knowledge, skills and MCP.

The SDK-instrumented ``support_agent`` produces nested agent/llm/tool/retriever spans.
Beyond the core refund flow it now:

  * keeps built-in ``Memory`` (short-term turns + long-term facts) across invocations;
  * pulls a ``PlatformContext`` (knowledge base entries, public skills, MCP servers) from
    the control plane via the ``evk_`` SDK key, surfaced to the decision model;
  * uses knowledge-base entries for policy Q&A, falling back to local refund policy.
"""

from __future__ import annotations

from typing import Any

from ._obs import deepeval_observe, deepeval_update_trace, platform_observe
from .memory import Memory, _tokenize
from .platform import PlatformContext
from .policy import policy_model
from .tools import create_refund, lookup_order, refund_policy

_memory: Memory | None = None
_context: PlatformContext | None = None


def configure_agent(*, memory: Memory | None = None, context: PlatformContext | None = None) -> None:
    """Bind the memory and platform context the observed agent will use.

    Passing no arguments resets both to their defaults.
    """
    global _memory, _context
    _memory = memory
    _context = context


def _current_memory() -> Memory:
    return _memory if _memory is not None else Memory()


def _current_context() -> PlatformContext:
    return _context if _context is not None else PlatformContext()


def _extract_order_id(query: str) -> str:
    for token in query.replace("，", " ").replace("。", " ").replace("？", " ").replace("?", " ").split():
        if token.startswith("A") and token[1:].isdigit():
            return token
    return "UNKNOWN"


def _is_policy_question(query: str) -> bool:
    return any(word in query for word in ("政策", "退款规则", "几天", "规则"))


@deepeval_observe(type="retriever")
@platform_observe(kind="retriever", name="knowledge_lookup")
def retrieve_knowledge(query: str, context: PlatformContext) -> list[dict[str, Any]]:
    """Retrieve platform knowledge-base entries relevant to the query."""
    terms = _tokenize(query)
    hits: list[dict[str, Any]] = []
    for entry in context.knowledge:
        haystack = f"{entry.get('title', '')} {entry.get('content', '')} " + " ".join(entry.get("tags", []) or [])
        if any(term and term in haystack for term in terms):
            hits.append(entry)
    return hits


@deepeval_observe(type="agent")
@platform_observe(kind="agent", name="support_agent")
async def support_agent(query: str) -> str:
    memory = _current_memory()
    context = _current_context()
    memory.add_turn("user", query)
    answer = await _answer(query, memory, context)
    memory.add_turn("assistant", answer)
    deepeval_update_trace(
        name="support_agent",
        input=query,
        output=answer,
        metadata={
            "skills": [s["name"] for s in context.skills],
            "mcp_servers": [m["name"] for m in context.mcp_servers],
            "knowledge_hits": len(context.knowledge),
        },
    )
    return answer


async def _answer(query: str, memory: Memory, context: PlatformContext) -> str:
    if _is_policy_question(query):
        entries = retrieve_knowledge(query, context) if context.knowledge else []
        if entries:
            answer = "根据知识库：" + entries[0].get("content", "")
        else:
            answer = "退款政策：" + " ".join(refund_policy(query))
        memory.add_fact("last_policy_query", query)
    else:
        order_id = _extract_order_id(query)
        order = lookup_order(order_id)
        if not order.get("found"):
            answer = f"没有找到订单 {order_id}。"
        else:
            decision = await policy_model(query, order, context=context)
            if decision == "refund_allowed":
                refund = create_refund(order_id)
                answer = f"订单 {order_id} 可以退款，金额为 ¥{order['amount']:.2f}。"
                if refund.get("ok"):
                    answer += "已为您提交退款申请。"
            elif decision == "refund_denied":
                answer = f"订单 {order_id} 当前不可退款。"
            else:
                answer = f"没有找到订单 {order_id}。"
            memory.add_fact(f"order:{order_id}", order.get("status", "unknown"))
    return answer
"""The decision model: a real LLM with a deterministic fallback.

The function is intentionally shaped like an LLM call so it produces a stable
``llm`` span and can later be swapped for any provider client. When credentials are
present it asks an OpenAI-compatible endpoint for a structured decision word; any
missing key or call failure falls back to a rule-based policy.
"""

from __future__ import annotations

from typing import Any

from ._obs import deepeval_observe, platform_observe
from .llm_client import ChatClient
from .platform import PlatformContext

_SYSTEM_PROMPT = (
    "你是电商客服的退款决策引擎。根据用户问题和订单信息，输出一个决策词，"
    "只能是以下之一：refund_allowed、refund_denied、not_found。"
)


def _build_messages(question: str, order: dict[str, Any], context: PlatformContext | None) -> list[dict[str, str]]:
    user = f"用户问题：{question}\n订单信息：{order}"
    if context is not None:
        hints: list[str] = []
        if context.skills:
            hints.append("可用技能：" + "；".join(s["name"] for s in context.skills))
        if context.mcp_servers:
            hints.append("可用 MCP 工具：" + "；".join(m["name"] for m in context.mcp_servers))
        if context.knowledge:
            hints.append("参考知识：" + "；".join(k["title"] for k in context.knowledge))
        if hints:
            user += "\n" + "\n".join(hints)
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _normalize_decision(raw: str | None) -> str:
    if not raw:
        return ""
    lowered = raw.strip().lower()
    for token in ("refund_allowed", "refund_denied", "not_found"):
        if token in lowered:
            return token
    return ""


def _deterministic_policy(question: str, order: dict[str, Any]) -> str:
    del question
    if not order.get("found"):
        return "not_found"
    return "refund_allowed" if order.get("refundable") else "refund_denied"


@deepeval_observe(type="llm")
@platform_observe(kind="llm", name="policy_model")
async def policy_model(question: str, order: dict[str, Any], *, context: PlatformContext | None = None) -> str:
    client = ChatClient()
    if client.available:
        decision = _normalize_decision(await client.chat(_build_messages(question, order, context)))
        if decision:
            return decision
    return _deterministic_policy(question, order)
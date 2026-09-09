"""Customer-support order/refund agent (SDK-instrumented, real LLM + deterministic fallback).

Adds built-in memory, platform-served knowledge base, public skills, and MCP servers.
"""

from .agent import configure_agent, retrieve_knowledge, support_agent
from .memory import Memory
from .platform import PlatformContext, fetch_platform_context
from .policy import policy_model
from .tools import ORDERS, Order, create_refund, lookup_order, refund_policy

__all__ = [
    "Memory",
    "ORDERS",
    "Order",
    "PlatformContext",
    "configure_agent",
    "create_refund",
    "fetch_platform_context",
    "lookup_order",
    "policy_model",
    "refund_policy",
    "retrieve_knowledge",
    "support_agent",
]
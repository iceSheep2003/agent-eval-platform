"""A deterministic customer-support Agent instrumented with DeepEval tracing.

This module deliberately keeps the business logic independent from the platform
and from the evaluator.  The only DeepEval-specific code is the tracing surface:
the top-level Agent, the tools it calls, and the model-like policy step are all
observable spans.  Install the optional dependency before importing this module:

    python -m pip install -e '.[deepeval]'

The fake policy model makes the example runnable without an external LLM.  Replace
``policy_model`` with a real model call, or wrap a provider client with DeepEval's
provider integration, when connecting it to a real Agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from deepeval.tracing import observe, update_current_trace
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by import users
    raise RuntimeError(
        "DeepEval is optional. Install it with `python -m pip install -e '.[deepeval]'`."
    ) from exc


@dataclass(frozen=True)
class Order:
    order_id: str
    status: str
    amount: float
    refundable: bool


ORDERS: dict[str, Order] = {
    "A001": Order("A001", "delivered", 249.0, True),
    "A002": Order("A002", "refunded", 89.0, False),
}


@observe(type="tool")
def lookup_order(order_id: str) -> dict[str, Any]:
    """Return structured order data for the Agent to reason over."""

    order = ORDERS.get(order_id)
    if order is None:
        return {"order_id": order_id, "found": False}
    return {
        "order_id": order.order_id,
        "status": order.status,
        "amount": order.amount,
        "refundable": order.refundable,
        "found": True,
    }


@observe(type="tool")
def create_refund(order_id: str) -> dict[str, Any]:
    """A side-effecting tool kept behind an explicit policy decision."""

    order = ORDERS.get(order_id)
    if order is None or not order.refundable:
        return {"ok": False, "order_id": order_id, "reason": "order_not_refundable"}
    return {"ok": True, "order_id": order_id, "amount": order.amount}


@observe(type="llm")
def policy_model(question: str, order: dict[str, Any]) -> str:
    """Deterministic stand-in for an LLM policy decision.

    The function is intentionally shaped like an LLM call so the sample has a
    stable ``llm`` span in tests and can later be replaced by a provider call.
    """

    del question
    if not order.get("found"):
        return "not_found"
    return "refund_allowed" if order.get("refundable") else "refund_denied"


@observe(type="agent")
def customer_support_agent(query: str) -> str:
    """Answer a small refund-support task while producing a nested trace."""

    order_id = _extract_order_id(query)
    order = lookup_order(order_id)
    decision = policy_model(query, order)

    if decision == "refund_allowed":
        answer = f"订单 {order_id} 可以退款，金额为 ¥{order['amount']:.2f}。"
    elif decision == "refund_denied":
        answer = f"订单 {order_id} 当前不可退款。"
    else:
        answer = f"没有找到订单 {order_id}。"

    # DeepEval uses these trace-level fields to build the end-to-end test case.
    update_current_trace(input=query, output=answer)
    return answer


def _extract_order_id(query: str) -> str:
    for token in query.replace("，", " ").replace("。", " ").split():
        if token.startswith("A") and token[1:].isdigit():
            return token
    return "UNKNOWN"


__all__ = [
    "ORDERS",
    "Order",
    "create_refund",
    "customer_support_agent",
    "lookup_order",
    "policy_model",
]

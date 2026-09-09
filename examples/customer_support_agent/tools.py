"""Customer-support tools: order lookup, refund creation, and policy retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._obs import deepeval_observe, platform_observe


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

REFUND_POLICY: tuple[str, ...] = (
    "已发货且未退款订单可申请全额退款。",
    "已退款或已取消订单不可重复退款。",
    "退款申请需在签收后 7 天内提出。",
)


@deepeval_observe(type="tool")
@platform_observe(kind="tool", name="lookup_order")
def lookup_order(order_id: str) -> dict[str, Any]:
    """Return structured order data for the agent to reason over."""

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


@deepeval_observe(type="tool")
@platform_observe(kind="tool", name="create_refund")
def create_refund(order_id: str) -> dict[str, Any]:
    """A side-effecting tool kept behind an explicit policy decision."""

    order = ORDERS.get(order_id)
    if order is None or not order.refundable:
        return {"ok": False, "order_id": order_id, "reason": "order_not_refundable"}
    return {"ok": True, "order_id": order_id, "amount": order.amount}


@deepeval_observe(type="retriever")
@platform_observe(kind="retriever", name="refund_policy")
def refund_policy(query: str) -> list[str]:
    """Retrieve the refund policy terms most relevant to the query."""

    del query
    return list(REFUND_POLICY)
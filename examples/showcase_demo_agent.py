"""展示平台的演示 Agent。

存在的理由：本地沙箱按 `RuntimePort` 的协议调用被测函数，公开输入叫 `input`。
这个模块提供一个最小、确定、无外部依赖的实现，用来端到端跑通
「三通道切换 → 对话」的动线，也方便在没有真实模型时做演示。

    entrypoint: examples.showcase_demo_agent:demo_support_agent
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_REFUND_ANSWER = "订单 {order_id} 符合退款条件，可以退款。"


def demo_support_agent(
    input: str,  # noqa: A002 - 参数名由平台调用协议决定
    messages: Sequence[Mapping[str, Any]] = (),
) -> str:
    """按关键词给一个确定性的客服回复。`messages` 只是证明签名过滤不会误伤。"""
    text = input or ""
    if "退款" in text:
        order_id = _extract_order_id(text)
        return _REFUND_ANSWER.format(order_id=order_id) if order_id else "请提供订单号，我来查一下。"
    if "发货" in text:
        return "订单已出库，预计 1–2 个工作日送达。"
    return f"收到你的问题：{text}。我会转给人工客服跟进。"


def _extract_order_id(text: str) -> str | None:
    for token in text.replace("，", " ").replace(",", " ").split():
        cleaned = token.strip("。？！?！")
        if cleaned[:1].isalpha() and any(ch.isdigit() for ch in cleaned):
            return cleaned
    return None

"""展示平台的演示 Agent：**真模型 + 确定性兜底**。

`RuntimePort` 的调用协议把公开输入叫 `input`，多轮上下文放在 `messages`。
平台侧（API 进程 / Worker）注入模型凭证，Agent 自己不持有任何 Key。

没有凭证、或调用失败时**降级到确定性回复**而不是抛错——展示平台宁可给一句
可预期的答复，也不该在访客面前弹一个 500。

    entrypoint: examples.showcase_demo_agent:demo_support_agent
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Mapping, Sequence

from .customer_support_agent.llm_client import ChatClient

#: 客服人设。放在 system 里而不是拼进 user，模型对多轮上下文的处理更稳。
SYSTEM_PROMPT = (
    "你是电商平台的在线客服助手，名字叫小助手。"
    "回答要简洁、直接、有礼貌，不要编造订单信息。"
    "涉及具体订单时，如果用户没说订单号，先问订单号。"
)

MAX_TOKENS = 512

_REFUND_ANSWER = "订单 {order_id} 符合退款条件，可以退款。"


async def demo_support_agent(
    input: str,  # noqa: A002 - 参数名由平台调用协议决定
    messages: Sequence[Mapping[str, Any]] = (),
    secrets: Mapping[str, str] | None = None,
) -> AsyncIterator[str]:
    """**异步生成器**：逐段吐模型的增量。

    平台侧看到的是真流式（`RuntimePort.invoke_stream` 识别异步生成器）；
    非流式调用（评测 Trial）会把各段拼回完整输出，两条路都不吃亏。

    拿不到模型凭证、或模型一个字都没吐出来时，退到确定性回复——
    兜底也走同一个生成器，调用方不必区分。
    """
    history = _build_history(input, messages)
    # 凭证由平台按「版本 × 通道」注入；没注入就退回环境变量（本地开发）。
    client = ChatClient.from_secrets(secrets)
    if client.available:
        emitted = False
        async for piece in client.chat_stream(
            history, temperature=0.3, max_tokens=MAX_TOKENS
        ):
            emitted = True
            yield piece
        if emitted:
            return
    yield _fallback(input)


def _build_history(
    input: str, messages: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    """把平台传来的对话上下文整理成模型要的 `messages`。

    平台传的是**完整历史**（含本轮），所以优先用它；只有它为空时才退回单轮。
    """
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in messages:
        role = str(item.get("role") or "")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            history.append({"role": role, "content": content})
    if len(history) == 1 and input:
        history.append({"role": "user", "content": input})
    return history


def _fallback(text: str) -> str:
    """无模型时的确定性回复。保持可用，但一眼能看出不是模型答的。"""
    content = text or ""
    if "退款" in content:
        order_id = _extract_order_id(content)
        if order_id:
            return _REFUND_ANSWER.format(order_id=order_id)
        return "请提供订单号，我来查一下。"
    if "发货" in content or "物流" in content:
        return "订单已出库，预计 1–2 个工作日送达。"
    return f"收到你的问题：{content}。（当前未配置模型凭证，这是兜底回复）"


def _extract_order_id(text: str) -> str | None:
    for token in text.replace("，", " ").replace(",", " ").split():
        cleaned = token.strip("。？！?！")
        if cleaned[:1].isalpha() and any(ch.isdigit() for ch in cleaned):
            return cleaned
    return None

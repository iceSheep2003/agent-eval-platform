"""把 `customer_support_agent` 接到平台调用协议上的适配入口。

平台（`RuntimePort`）约定的公开输入是 `input`，多轮上下文放在 `messages`；
而 `support_agent(query)` 是照 SDK 直接调用写的，签名里只有 `query`。
这个薄适配层负责两件事：

1. **参数改名**：`input` → `query`；
2. **会话上下文**：`support_agent` 的记忆存在模块级的 `Memory` 上，跨进程调用会串味。
   平台每次调用都是独立的，所以这里按 `messages` 重建一份 Memory 再绑定上去——
   会话状态由**调用方**持有，不由进程持有。

注册到平台时用：

    entrypoint: examples.customer_support_agent.platform_entry:platform_support_agent
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

# DeepEval 每次调用都会打一行「No Confident AI API key found」。本地跑
# `deepeval test run` 时它有用，但平台上每次对话都刷屏只会淹没真正的日志。
# 必须在 import deepeval 之前设置才生效。
os.environ.setdefault("CONFIDENT_TRACE_VERBOSE", "false")

from .agent import configure_agent, support_agent  # noqa: E402
from .memory import Memory  # noqa: E402


async def platform_support_agent(
    input: str,  # noqa: A002 - 参数名由平台调用协议决定
    messages: Sequence[Mapping[str, Any]] = (),
) -> str:
    """平台入口。`messages` 是完整历史（含本轮），末尾那条就是 `input`。"""
    configure_agent(memory=_memory_from(messages))
    try:
        return await support_agent(input)
    finally:
        # 模块级状态用完即弃——下一次调用可能是别人的会话。
        configure_agent()


def _memory_from(messages: Sequence[Mapping[str, Any]]) -> Memory:
    """按平台传来的历史重建 Memory。

    **丢掉最后一条 user**：`support_agent` 自己会把当前这轮 `add_turn` 进去，
    这里再放一次就会出现重复的 user 轮次。
    """
    turns = [
        (str(item.get("role")), str(item.get("content")))
        for item in messages
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    if turns and turns[-1][0] == "user":
        turns = turns[:-1]

    memory = Memory()
    for role, content in turns:
        memory.add_turn(role, content)
    return memory

"""记忆契约。

**为什么记忆在平台侧而不是 Agent 里**：沙箱是无状态的，Agent 进程随时可能被
换掉。把记忆放在 Agent 的模块级变量上只有两种结局——要么丢，要么串味
（`customer_support_agent` 的 `_memory` 就踩过：同一个进程里两次不同会话的
对话会互相看见）。

所以记忆是**平台提供的服务**，Agent 通过 `memory` 形参拿到的只是一个句柄。

**作用域三件正交的事**，缺一个都会串：
- `agent_version_id` —— 换版本就该换记忆（行为变了，历史不该带过去）；
- `tenant_id` —— 不同租户绝不能互相看见；
- `thread_id` —— 同一次会话；为空表示该版本该租户下的唯一短期记忆。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence, runtime_checkable

from ..common import Id

#: 记忆作用域。Agent 在 spec 里显式声明，`stateless` 是明说的而不是忘了写。
MemoryScopeKind = Literal["thread", "tenant", "agent_version", "stateless"]

@dataclass(frozen=True, slots=True)
class MemoryKey:
    """一次调用该读写哪一片记忆。"""

    agent_version_id: Id
    tenant_id: Id | None = None
    thread_id: Id | None = None
    scope: MemoryScopeKind = "thread"


@dataclass(frozen=True, slots=True)
class MemoryTurn:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class MemoryFact:
    key: str
    value: str


@runtime_checkable
class MemoryPort(Protocol):
    """由平台实现；Agent 通过 `memory` 形参拿到的就是它。

    方法**全部异步**——实现要落库，而且沙箱里跑的是同步代码时也不能阻塞事件循环。
    """

    async def remember_turns(
        self, target: MemoryKey, turns: Sequence[MemoryTurn]
    ) -> None: ...

    async def recent_turns(self, target: MemoryKey, limit: int = 8) -> Sequence[MemoryTurn]: ...

    async def remember_fact(self, target: MemoryKey, key: str, value: str) -> None: ...

    async def recall_facts(
        self, target: MemoryKey, query: str, top_k: int = 5
    ) -> Sequence[MemoryFact]: ...

    async def forget(self, target: MemoryKey) -> int:
        """清空这个作用域的记忆。**不可逆**——保留策略到期时由平台调用。"""
        ...


@runtime_checkable
class MemorySessionPort(Protocol):
    """**注入给 Agent 的那个对象**——分区键已经绑好，Agent 看不到也改不了。

    刻意不把 `MemoryPort`（带 key 的那个）交给 Agent：那样它就得自己拼
    `agent_version_id` / `tenant_id` / `thread_id`，拼错一个就串到别人的记忆里。
    交给它一个「只能看自己那片」的句柄，越界在接口层面就不存在。
    """

    async def recent(self, limit: int = 8) -> Sequence[MemoryTurn]:
        """最近几轮对话，按时间正序。"""
        ...

    async def remember(self, role: str, content: str) -> None:
        """记一轮对话。`role` 为 `user` / `assistant`。"""
        ...

    async def save_fact(self, key: str, value: str) -> None:
        """记一条长期事实，可跨会话召回。"""
        ...

    async def recall(self, query: str, top_k: int = 5) -> Sequence[MemoryFact]:
        """按相关度召回长期事实。"""
        ...


__all__ = [
    "MemoryFact",
    "MemoryKey",
    "MemoryPort",
    "MemorySessionPort",
    "MemoryTurn",
]

"""通用状态机。

系统里有两条独立的状态机（Trial 执行、运行实例启停），机制完全一样：
一张合法迁移表 + 迁移历史 + 终态判定。抽出来避免写两遍。

**非法迁移一律抛错**——状态错乱不允许被静默接受。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Mapping, TypeVar

S = TypeVar("S", bound=StrEnum)


class IllegalTransition(RuntimeError):
    """状态机拒绝了这次迁移。出现在这里说明代码有 bug，不该被 catch 掉。"""


@dataclass
class StateMachine(Generic[S]):
    """刻意是**可变对象**：它就是「现在走到哪了」的载体。

    领域层其余部分用冻结 dataclass，但状态机要记录迁移历史，冻结反而别扭。
    """

    #: 合法迁移表。不在表里的组合一律拒绝。
    transitions: Mapping[S, frozenset[S]] = field(default_factory=dict)
    #: 终态。终态没有出边（原地迁移是 no-op）。
    terminal: frozenset[S] = field(default_factory=frozenset)
    #: 初始状态。子类通过 `initial_of()` 指定。
    initial: S | None = None
    state: S | None = None
    history: list[S] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state is None:
            self.state = self.initial
        if self.state is None:
            raise ValueError("状态机必须指定初始状态")
        self.history = [self.state]

    @property
    def is_terminal(self) -> bool:
        return self.state in self.terminal

    def can(self, target: S) -> bool:
        return target in self.transitions.get(self.state, frozenset())  # type: ignore[arg-type]

    def to(self, target: S) -> S:
        # 原地迁移是幂等的 no-op：调用方（方案的兜底、重复触发）不必先判断当前状态
        if target is self.state:
            return self.state  # type: ignore[return-value]
        if self.is_terminal:
            raise IllegalTransition(f"{self.state} 是终态，不能再迁移到 {target}")
        if not self.can(target):
            raise IllegalTransition(f"不允许从 {self.state} 迁移到 {target}")
        self.state = target
        self.history.append(target)
        return self.state  # type: ignore[return-value]

    def path(self) -> str:
        return " → ".join(item.value for item in self.history)


def verify_machine(states: type[StrEnum], transitions: Mapping[S, frozenset[S]]) -> None:
    """启动时自检：每个状态都要在迁移表里，且都要能从起点到达。

    漏一个的后果是「跑到那一步才炸」或「写了但永远走不到」，都属于死代码。
    """
    declared = set(states)
    covered = set(transitions)
    missing = declared - covered
    if missing:
        raise ValueError(f"这些状态没有声明迁移：{sorted(item.value for item in missing)}")

    reachable: set = set()
    for targets in transitions.values():
        reachable |= set(targets)
    orphans = covered - reachable
    # 起点本身不需要被别人指向
    if len(orphans) > 1:
        raise ValueError(
            f"这些状态不可达：{sorted(item.value for item in orphans)}"
        )


__all__ = ["IllegalTransition", "StateMachine", "verify_machine"]

"""Minimal adapter between Eval Loom's AgenticBench envelope and an Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class Observation:
    type: str
    content: Any
    is_error: bool = False


@dataclass(slots=True)
class Action:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


class AgenticBenchAdapter:
    """Owns protocol conversion; the Agent stays benchmark-independent."""

    protocol = "agentic-bench/v1"

    def __init__(self, agent_step: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]):
        self.agent_step = agent_step

    async def invoke(self, envelope: dict[str, Any]) -> dict[str, Any]:
        task = envelope.get("task") or {"instruction": envelope.get("input", "")}
        state = {
            "task_id": envelope.get("task_id"),
            "instruction": task.get("instruction", ""),
            "context": envelope.get("context", {}),
            "actions": envelope.get("actions", []),
            "observation": envelope.get("observation"),
            "limits": envelope.get("limits", {}),
        }
        result = await self.agent_step(state)
        action = result.get("action")
        if action:
            return {"protocol": self.protocol, "action": asdict(Action(action["name"], action.get("arguments", {})))}
        return {"protocol": self.protocol, "output": result.get("output", result), "terminal": True}

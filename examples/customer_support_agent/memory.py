"""Built-in short-term + long-term memory for the customer-support agent.

Memory is client-side and independent of the platform: a plain JSON file keeps past
turns and extracted facts so the agent can recall prior interactions across invocations.
The platform enriches *knowledge* (via ``PlatformContext``), not the agent's private memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _tokenize(text: str) -> set[str]:
    """CJK-friendly tokenizer: whole space-separated chunks plus individual CJK chars."""
    tokens: set[str] = set()
    for chunk in text.replace("，", " ").replace("。", " ").replace("？", " ").replace("?", " ").replace("：", " ").split():
        tokens.add(chunk)
        if any("一" <= c <= "鿿" for c in chunk):
            tokens.update(chunk)
    return tokens


class Memory:
    def __init__(self, path: str | Path | None = None, max_turns: int = 100) -> None:
        self.path = Path(path) if path else None
        self.max_turns = max_turns
        self.turns: list[dict[str, Any]] = []
        self.facts: dict[str, str] = {}
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.turns = (data.get("turns") or [])[-self.max_turns :]
            self.facts = data.get("facts") or {}
        except (OSError, ValueError):
            self.turns, self.facts = [], {}

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content})
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns :]

    def add_fact(self, key: str, value: str) -> None:
        self.facts[key] = value

    def recent(self, n: int = 8) -> list[dict[str, Any]]:
        return self.turns[-n:]

    def recall(self, query: str, top_k: int = 5) -> list[str]:
        terms = _tokenize(query)
        scored = [
            (sum(1 for term in terms if term in f"{key} {value}"), value)
            for key, value in self.facts.items()
        ]
        scored = [(score, value) for score, value in scored if score > 0]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [value for _, value in scored[:top_k]]

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"turns": self.turns, "facts": self.facts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
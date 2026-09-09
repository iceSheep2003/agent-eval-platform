"""Observability shims.

``agent_eval`` is a hard dependency — it is the platform's upload SDK and provides
``PlatformSink``, ``configure``, and ``observe``. DeepEval is optional and only adds
a second span layer for local ``deepeval test run`` / Confident AI. When DeepEval is
absent, the agent still uploads full agent/llm/tool/retriever events through
``PlatformSink``.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_eval import JsonlSink, PlatformSink, configure, observe as platform_observe

try:  # pragma: no cover - exercised by the DeepEval smoke test
    from deepeval.tracing import observe as deepeval_observe
    from deepeval.tracing import update_current_trace as deepeval_update_trace
except Exception:  # noqa: BLE001 - DeepEval is optional
    def deepeval_observe(func: Callable[..., Any] | None = None, **_: Any) -> Any:
        """No-op stand-in so call sites keep the same shape when DeepEval is missing."""

        def _deco(target: Callable[..., Any]) -> Callable[..., Any]:
            return target

        return _deco(func) if func is not None else _deco

    def deepeval_update_trace(**_: Any) -> None:  # type: ignore[misc]
        return None


__all__ = [
    "JsonlSink",
    "PlatformSink",
    "configure",
    "deepeval_observe",
    "deepeval_update_trace",
    "platform_observe",
]
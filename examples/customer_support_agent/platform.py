"""Pull the platform's context resources for an SDK-connected agent using its ``evk_`` key.

``GET /v1/agent-context`` returns the workspace-public plus agent-scoped knowledge-base
entries, skills, and MCP servers. Fetching is best-effort: without a base URL / SDK key,
or on any transport error, the agent continues with an empty context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class PlatformContext:
    knowledge: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.knowledge or self.skills or self.mcp_servers)


def fetch_platform_context(base_url: str, sdk_key: str, *, timeout: float = 10.0) -> PlatformContext:
    if not base_url or not sdk_key:
        return PlatformContext()
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/v1/agent-context",
            headers={"Authorization": f"Bearer {sdk_key}"},
            timeout=timeout,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return PlatformContext()
    return PlatformContext(
        knowledge=data.get("knowledge", []),
        skills=data.get("skills", []),
        mcp_servers=data.get("mcp_servers", []),
    )
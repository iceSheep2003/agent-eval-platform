"""可观测性契约。

定义方：消费方（execution 的 InvokeService 要记录一次按通道调用产生的 Trace）。
实现方：observability（`TraceService.record_invocation`）。

**只发布被跨模块消费的项**（G2/G3）。Score 是 Trial 的产物，归 execution，不在这里。

关于 Trace 与 Run 的关系：本端口只写**平台自己发起的一次调用**（`ingested_via="gateway"`），
SDK 上报仍走 `/v1/traces` 的 NDJSON 入口，两者在 `obs_trace` 里靠 `external_trace_id` 区分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from ..common import Channel, Id, TraceOrigin, Usage

TraceStatus = Literal["success", "error", "timeout", "cancelled"]


@dataclass(frozen=True, slots=True)
class InvocationTrace:
    """一次平台发起的调用事实。不含 Span——那是被测 Agent 自己上报的。"""

    workspace_id: Id
    asset_id: Id
    asset_version_id: Id
    channel: Channel | None
    origin: TraceOrigin
    external_trace_id: str
    name: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None = None
    tenant_id: Id | None = None
    input: Any | None = None
    output: Any | None = None
    error: str | None = None
    usage: Usage = field(default_factory=Usage)


@runtime_checkable
class TraceWriterPort(Protocol):
    """由 observability 实现；execution 在调用结束后写一条生产/影子/评测 Trace。"""

    async def record_invocation(self, trace: InvocationTrace) -> Id: ...


__all__ = ["InvocationTrace", "TraceWriterPort"]

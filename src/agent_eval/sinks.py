"""Event sinks. All built-in sinks are dependency-free."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from .models import TraceEvent
from .serialization import safe_json


class EventSink(Protocol):
    async def emit(self, event: TraceEvent) -> None: ...

    async def flush(self) -> None: ...

    async def close(self) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit_sync(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def emit(self, event: TraceEvent) -> None:
        self.emit_sync(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


class ConsoleSink:
    def __init__(self, *, stream: Any = None) -> None:
        import sys

        self.stream = stream or sys.stdout

    def emit_sync(self, event: TraceEvent) -> None:
        print(
            f"[{event.timestamp.isoformat()}] {event.event_type} "
            f"trace={event.trace_id} span={event.span_id or '-'}",
            file=self.stream,
        )

    async def emit(self, event: TraceEvent) -> None:
        self.emit_sync(event)

    async def flush(self) -> None:
        flush = getattr(self.stream, "flush", None)
        if flush:
            flush()

    async def close(self) -> None:
        return None


class JsonlSink:
    """Durable append-only JSONL sink for TraceEvent objects."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self.path.open("a", encoding="utf-8")

    def emit_sync(self, event: TraceEvent) -> None:
        line = json.dumps(safe_json(event.to_dict()), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    async def emit(self, event: TraceEvent) -> None:
        self.emit_sync(event)

    async def flush(self) -> None:
        with self._lock:
            self._file.flush()

    async def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()


class HttpSink:
    """Small optional platform sink using the standard library HTTP client."""

    def __init__(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0, retries: int = 2) -> None:
        self.url = url
        self.headers = {"Content-Type": "application/x-ndjson", **(headers or {})}
        self.timeout = timeout
        self.retries = max(0, retries)
        self._pending: list[TraceEvent] = []
        self._lock = asyncio.Lock()

    async def emit(self, event: TraceEvent) -> None:
        async with self._lock:
            self._pending.append(event)

    async def flush(self) -> None:
        async with self._lock:
            pending = list(self._pending)
            self._pending.clear()
        if not pending:
            return
        body = "".join(json.dumps(safe_json(item.to_dict()), ensure_ascii=False) + "\n" for item in pending).encode()
        headers = dict(self.headers)
        if pending:
            headers.setdefault("Idempotency-Key", f"{pending[0].trace_id}:{pending[0].sequence}:{pending[-1].sequence}")

        def send() -> None:
            request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
            last: Exception | None = None
            for attempt in range(self.retries + 1):
                try:
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        if response.status >= 300:
                            raise urllib.error.HTTPError(self.url, response.status, "ingest failed", response.headers, None)
                    return
                except Exception as exc:  # pragma: no cover - exercised with integration service
                    last = exc
                    if attempt < self.retries:
                        time.sleep(0.2 * (2**attempt))
            if last:
                raise last

        try:
            await asyncio.to_thread(send)
        except Exception:
            # Platform sinks are intentionally best-effort. The durable local sink remains authoritative.
            return

    async def close(self) -> None:
        await self.flush()


class PlatformSink(HttpSink):
    """Send SDK trace events to an Eval Loom control plane with an Agent SDK key."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0, retries: int = 2) -> None:
        if not api_key.startswith("evk_"):
            raise ValueError("Agent SDK key must start with evk_")
        super().__init__(
            f"{base_url.rstrip('/')}/v1/traces",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            retries=retries,
        )


class CompositeSink:
    def __init__(self, sinks: list[EventSink]) -> None:
        self.sinks = sinks
        self._pending_tasks: list[asyncio.Task[Any]] = []
        self._pending_sync: list[tuple[EventSink, TraceEvent]] = []
        self._sync_lock = threading.Lock()

    def emit_sync(self, event: TraceEvent) -> None:
        for sink in self.sinks:
            emit_sync = getattr(sink, "emit_sync", None)
            if emit_sync:
                try:
                    emit_sync(event)
                except Exception:
                    continue
            else:
                try:
                    loop = asyncio.get_running_loop()
                    self._pending_tasks.append(loop.create_task(sink.emit(event)))
                except RuntimeError:
                    # Sync Agents may run in a worker thread. Keep async-only
                    # sinks buffered until the evaluation loop calls flush().
                    with self._sync_lock:
                        self._pending_sync.append((sink, event))

    async def emit(self, event: TraceEvent) -> None:
        await asyncio.gather(*(sink.emit(event) for sink in self.sinks), return_exceptions=True)

    async def flush(self) -> None:
        with self._sync_lock:
            pending_sync = list(self._pending_sync)
            self._pending_sync.clear()
        if pending_sync:
            await asyncio.gather(*(sink.emit(event) for sink, event in pending_sync), return_exceptions=True)
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self._pending_tasks.clear()
        await asyncio.gather(*(sink.flush() for sink in self.sinks), return_exceptions=True)

    async def close(self) -> None:
        await asyncio.gather(*(sink.close() for sink in self.sinks), return_exceptions=True)

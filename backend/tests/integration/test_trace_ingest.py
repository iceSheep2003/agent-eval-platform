"""M1b 验收：SDK 事件 → Trace/Span。

夹具刻意**不含 `trace_started`**——SDK 对 `@observe` 的 Agent 就是不发这个事件。
适配器必须能兜底推导起始时间，否则会出现 ended_at < started_at（真实踩过的坑）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.app.container import Container
from backend.app.contracts.common import CredentialKind, SpanKind
from backend.app.contracts.errors import DomainError
from backend.app.modules.observability.application.services import TraceQuery
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

BASE = "2026-09-09T08:40:00"


def _event(sequence: int, event_type: str, span_id: str | None, payload: dict, offset: float,
           trace_id: str = "sdk-trace-1"):
    return {
        "event_id": f"evt{sequence}",
        "trace_id": trace_id,
        "span_id": span_id,
        "sequence": sequence,
        "event_type": event_type,
        "actor": "agent",
        "timestamp": f"{BASE}.{int(offset):06d}+00:00",
        "payload": payload,
        "visibility": "public",
    }


def _sdk_batch(trace_id: str = "sdk-trace-1") -> list[dict]:
    """形状取自 examples/customer_support_agent 的真实 events.jsonl。"""
    events = [
        _event(1, "span_started", "s1", {"kind": "agent", "name": "support_agent",
                                         "parent_span_id": None,
                                         "input_ref": {"inline": "订单 A001 能退款吗", "size": 15},
                                         "attributes": {}}, 583052),
        _event(2, "agent_started", "s1", {"name": "support_agent"}, 583075),
        _event(3, "span_started", "s2", {"kind": "tool", "name": "lookup_order",
                                         "parent_span_id": "s1",
                                         "input_ref": {"inline": {"order_id": "A001"}, "size": 18},
                                         "attributes": {}}, 583131),
        _event(4, "tool_called", "s2", {"name": "lookup_order"}, 583153),
        _event(5, "span_finished", "s2", {"kind": "tool", "name": "lookup_order",
                                          "status": "ok",
                                          "input_ref": {"inline": {"order_id": "A001"}, "size": 18},
                                          "output_ref": {"inline": {"status": "refundable"}, "size": 22},
                                          "attributes": {}, "usage": {"input_tokens": 0,
                                          "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
                                          "started_at": f"{BASE}.583131+00:00",
                                          "ended_at": f"{BASE}.583178+00:00",
                                          "error": None}, 583178),
        _event(6, "span_finished", "s1", {"kind": "agent", "name": "support_agent",
                                          "status": "ok",
                                          "input_ref": {"inline": "订单 A001 能退款吗", "size": 15},
                                          "output_ref": {"inline": "该订单可以退款。", "size": 27},
                                          "attributes": {},
                                          "usage": {"input_tokens": 12, "output_tokens": 5,
                                                    "total_tokens": 17, "cost_usd": 0.0003},
                                          "started_at": f"{BASE}.583052+00:00",
                                          "ended_at": f"{BASE}.583247+00:00",
                                          "error": None}, 583247),
        # 未知事件类型必须被忽略，而不是报错
        _event(7, "some_future_event_type", "s1", {"anything": 1}, 583260),
        _event(8, "trace_finished", None, {"status": "success",
                                           "output": {"inline": "该订单可以退款。", "size": 27}},
               583293),
    ]
    return [dict(event, trace_id=trace_id) for event in events]


def _ndjson(events: list[dict]) -> bytes:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events).encode("utf-8")


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'trace.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        agent = await container.assets.register_agent(
            workspace_id=seeded["workspace_id"],
            owner_id=seeded["admin"],
            name="customer-support-agent",
            connect_type="sdk",
        )
        issued = await container.assets.mint_credential(
            workspace_id=seeded["workspace_id"],
            kind=CredentialKind.TRACE,
            asset_id=agent.id,
        )
        credential = await container.traces.resolve_credential(issued.secret)
        service = container.traces

        result = await service.ingest_ndjson(_ndjson(_sdk_batch()), credential)
        assert result.accepted_count == 1
        assert result.dropped_events == 0
        trace_id = result.accepted_traces[0]

        trace = await service.get_trace(trace_id, seeded["workspace_id"])
        assert trace.name == "support_agent"  # 不是 uuid
        assert trace.status == "success"
        assert trace.span_count == 2
        assert trace.usage.total_tokens == 17
        # 起始时间必须来自事件，而不是平台接收时间
        assert trace.started_at.year == 2026 and trace.started_at.hour == 8
        assert trace.ended_at is not None and trace.ended_at >= trace.started_at

        nodes = await service.span_tree(trace_id)
        assert len(nodes) == 1 and nodes[0].depth == 0
        assert nodes[0].span.name == "support_agent"
        assert len(nodes[0].children) == 1
        child = nodes[0].children[0]
        assert child.depth == 1 and child.span.kind is SpanKind.TOOL
        assert child.span.output == {"status": "refundable"}

        # 幂等：同一批重复上报不产生第二行（重放走 updated 分支）
        again = await service.ingest_ndjson(_ndjson(_sdk_batch()), credential)
        assert again.accepted_count == 0
        assert len(again.updated_traces) == 1
        assert len((await service.list_traces(
            seeded["workspace_id"], TraceQuery(asset_id=agent.id), None
        ))[0]) == 1  # 仍然只有一条 trace

        # 同一 trace 分两批到达：第二批补齐 span，而不是整条被当重复丢弃
        split = _sdk_batch(trace_id="sdk-trace-split")
        first = [event for event in split if event["sequence"] <= 3]
        second = [event for event in split if event["sequence"] > 3]
        head = await service.ingest_ndjson(_ndjson(first), credential)
        assert head.accepted_count == 1
        partial = await service.get_trace(head.accepted_traces[0], seeded["workspace_id"])
        assert partial.span_count == 2  # 两个 span_started 已落库，但都还没结束

        tail = await service.ingest_ndjson(_ndjson(second), credential)
        assert tail.accepted_count == 0
        assert len(tail.updated_traces) == 1  # 只更新了已有 span，不算重复
        merged = await service.get_trace(head.accepted_traces[0], seeded["workspace_id"])
        assert merged.span_count == 2
        assert merged.status == "success"
        merged_nodes = await service.span_tree(merged.id)
        assert merged_nodes[0].span.status == "ok"

        # 坏行只回执不整批失败
        bad = await service.ingest_ndjson(b"not json\n{\"no_trace_id\":1}\n", credential)
        assert bad.accepted_count == 0 and bad.dropped_events == 2

        # 指标口径显式命名
        metrics = await service.agent_metrics(seeded["workspace_id"], agent.id)
        assert metrics.trace_count == 2  # sdk-trace-1 + 分两批到达的 sdk-trace-split
        assert metrics.invocation_success_rate == 1.0
        assert metrics.p95_latency_ms is not None and metrics.p95_latency_ms >= 0

        traces, total = await service.list_traces(
            seeded["workspace_id"], TraceQuery(asset_id=agent.id), None
        )
        assert total == 2 and len(traces) == 2

        # 密钥无效
        with pytest.raises(DomainError):
            await service.resolve_credential("evk_nope")
    finally:
        await container.shutdown()


def test_trace_ingest(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

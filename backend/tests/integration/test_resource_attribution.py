"""N3 验收：生产 Trace 的 tool span 归因到 MCP 版本 → 资源质量面板出数。

三条硬约束：
1. **不改 SDK 事件形状**——归因只用 Span 已有的 `kind` / `name` / `attributes`；
2. 生产 Trace 没有 `asset_version_id`，回退到该 Agent 的 LIVE 版本解析引用，
   结果标 `resolved`；归不上就保持 NULL；
3. 指标口径按 kind 命名（MCP 是 `tool_success_rate`），并且带归因覆盖率自检。
"""

from __future__ import annotations

import asyncio
import json

from backend.app.container import Container
from backend.app.contracts.common import AssetKind, Channel, CredentialKind
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

BASE = "2026-09-10T08:40:00"

MCP_SPEC = {
    "kind": "mcp",
    "endpoint": "https://mcp.internal/orders",
    "transport": "streamable-http",
    "tools": [{"name": "lookup_order", "description": "查订单"}],
}


def _event(sequence: int, event_type: str, span_id: str | None, payload: dict, offset: float):
    return {
        "event_id": f"evt{sequence}",
        "trace_id": "sdk-trace-attrib",
        "span_id": span_id,
        "sequence": sequence,
        "event_type": event_type,
        "actor": "agent",
        "timestamp": f"{BASE}.{int(offset):06d}+00:00",
        "payload": payload,
        "visibility": "public",
    }


def _batch() -> bytes:
    events = [
        _event(1, "span_started", "s1", {"kind": "agent", "name": "support_agent",
                                         "parent_span_id": None,
                                         "input_ref": {"inline": "订单 A001", "size": 9},
                                         "attributes": {}}, 583052),
        _event(2, "span_started", "s2", {"kind": "tool", "name": "lookup_order",
                                         "parent_span_id": "s1",
                                         "input_ref": {"inline": {"order_id": "A001"}, "size": 18},
                                         "attributes": {}}, 583131),
        _event(3, "span_finished", "s2", {"kind": "tool", "name": "lookup_order",
                                          "status": "ok",
                                          "input_ref": {"inline": {"order_id": "A001"}, "size": 18},
                                          "output_ref": {"inline": {"status": "refundable"}, "size": 22},
                                          "attributes": {}, "usage": {"input_tokens": 0,
                                          "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
                                          "started_at": f"{BASE}.583131+00:00",
                                          "ended_at": f"{BASE}.583178+00:00",
                                          "error": None}, 583178),
        _event(4, "span_finished", "s1", {"kind": "agent", "name": "support_agent",
                                          "status": "ok",
                                          "input_ref": {"inline": "订单 A001", "size": 9},
                                          "output_ref": {"inline": "可退款", "size": 9},
                                          "attributes": {},
                                          "usage": {"input_tokens": 10, "output_tokens": 4,
                                                    "total_tokens": 14, "cost_usd": 0.0002},
                                          "started_at": f"{BASE}.583052+00:00",
                                          "ended_at": f"{BASE}.583247+00:00",
                                          "error": None}, 583247),
        _event(5, "trace_finished", None, {"status": "success",
                                           "output": {"inline": "可退款", "size": 9}}, 583293),
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events).encode("utf-8")


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'attrib.db'}",
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
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        assets = container.assets

        agent = await assets.register_agent(
            workspace_id=workspace_id, owner_id=owner, name="support-agent"
        )
        agent_version = (await assets.list_versions(agent.id, workspace_id))[0]

        mcp = await assets.register_capability(
            workspace_id=workspace_id,
            owner_id=owner,
            kind=AssetKind.MCP,
            name="orders-mcp",
            spec=MCP_SPEC,
        )
        mcp_version = (await assets.list_versions(mcp.id, workspace_id))[0]

        # 引用关系就位：MCP 的 LIVE → v1；Agent 的 LIVE → 当前版本
        await assets.bind_channel(
            asset_id=mcp.id,
            channel=Channel.LIVE,
            version_id=mcp_version.id,
            workspace_id=workspace_id,
            actor_id=owner,
        )
        await assets.bind_capability(
            workspace_id=workspace_id,
            actor_id=owner,
            consumer_asset_id=agent.id,
            provider_asset_id=mcp.id,
            resolve_mode="channel",
        )
        await assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.LIVE,
            version_id=agent_version.id,
            workspace_id=workspace_id,
            actor_id=owner,
        )

        # 归因候选：生产 Trace 无版本号 → 回退到 Agent 的 LIVE 版本
        targets = await assets.attribution_targets(
            workspace_id=workspace_id, asset_id=agent.id, version_id=None
        )
        assert [item.asset_id for item in targets] == [mcp.id]
        assert targets[0].names == frozenset({"lookup_order"})

        issued = await assets.mint_credential(
            workspace_id=workspace_id, kind=CredentialKind.TRACE, asset_id=agent.id
        )
        credential = await container.traces.resolve_credential(issued.secret)
        result = await container.traces.ingest_ndjson(_batch(), credential)
        assert result.accepted_count == 1

        nodes = await container.traces.span_tree(result.accepted_traces[0])
        tool_span = nodes[0].children[0].span
        agent_span = nodes[0].span
        # tool span 归因到 MCP 版本；agent span 不归因（没有同名 Skill）
        assert tool_span.resource_asset_id == mcp.id
        assert tool_span.resource_version_id == mcp_version.id
        assert tool_span.resource_attribution == "resolved"
        assert agent_span.resource_asset_id is None

        # 质量读模型：口径按 kind 命名，不出现裸 success_rate
        metrics = await container.traces.resource_metrics(
            workspace_id=workspace_id,
            resource_asset_id=mcp.id,
            resource_version_id=mcp_version.id,
            kind=AssetKind.MCP.value,
            window_hours=24,
            consumer_asset_ids=(agent.id,),
        )
        assert metrics.invocations == 1
        assert metrics.success_metric == "tool_success_rate"
        assert metrics.success_rate == 1.0
        assert metrics.error_rate == 0.0
        assert metrics.attribution_coverage == 1.0  # 1 个 tool span，全部归因上了
    finally:
        await container.shutdown()


def test_resource_attribution(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

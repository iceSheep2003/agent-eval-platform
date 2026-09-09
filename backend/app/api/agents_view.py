"""Agent 控制台读模型（列表 + 详情）。

**组合层投影**：列表页要的一行数据横跨 asset（版本/通道/凭证）、execution（运行数）、
observability（成功率/延迟/成本）三个模块。放进任一模块都会让那个模块反向依赖其余两个，
所以放在组合层，只做「取数 + 拼装」，不含业务规则。

写路径（接入、建版本、签发凭证、晋级）仍在 `modules/asset` 与 `modules/delivery`。
"""

from __future__ import annotations

from typing import Annotated, Any, Sequence

from fastapi import APIRouter, Depends, Query

from ..container import Container
from ..contracts.common import Channel, RunStatus
from ..contracts.identity import Permission, ResourceRef
from ..schemas.response import list_response, ok
from .deps import Actor, assert_permission, get_container

router = APIRouter(tags=["asset"])

DEFAULT_WINDOW_HOURS = 24


def _source_ref(spec: dict[str, Any], name: str) -> str:
    """列表页「来源」列展示用：尽量给出真实出处，取不到再退化。"""
    for key in ("repository", "artifact_id", "source_ref"):
        value = spec.get(key)
        if value:
            ref = str(spec.get("ref") or "")
            return f"{value} · {ref}" if ref else str(value)
    return f"{name.lower().replace(' ', '-')}.zip"


async def _agent_row(container: Container, agent: Any, workspace_id: str, window_hours: int) -> dict:
    versions = await container.assets.list_versions(agent.id, workspace_id)
    channels = await container.assets.channel_states(agent.id, workspace_id)
    credentials = [
        item
        for item in await container.assets.list_credentials(workspace_id)
        if item.asset_id == agent.id
    ]
    active = [item for item in credentials if item.status != "revoked"]
    metrics = await container.traces.agent_metrics(
        workspace_id, agent.id, window_hours=window_hours
    )
    runs = [run for run in await container.runs.list_runs(workspace_id)
            if run.subject_asset_id == agent.id]
    completed = [run for run in runs if run.status is RunStatus.COMPLETED]
    quality: float | None = None
    if completed:
        result = await container.runs.get_result(completed[0].id, workspace_id)
        if result is not None:
            quality = round(result.avg_score * 100, 1)

    by_version = {version.id: version.version_label for version in versions}
    latest = versions[0] if versions else None
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "owner": agent.owner_id,
        "connect_type": agent.connect_type,
        "status": agent.lifecycle,
        "environment": agent.connect_type,
        "lifecycle": agent.lifecycle,
        "version": latest.version_label if latest else None,
        "test_version": by_version.get(channels[Channel.TEST].version_id or ""),
        "livesh_version": by_version.get(channels[Channel.LIVESH].version_id or ""),
        "live_version": by_version.get(channels[Channel.LIVE].version_id or ""),
        "credential_state": "ready" if active else "missing",
        "source_ref": _source_ref(dict(latest.spec) if latest else {}, agent.name),
        "run_count": len(runs),
        "success_rate": (
            round(metrics.invocation_success_rate * 100, 1)
            if metrics.invocation_success_rate is not None
            else None
        ),
        "latency_ms": metrics.p95_latency_ms,
        "average_cost": float(metrics.total_cost_usd) / metrics.trace_count
        if metrics.trace_count
        else None,
        "quality_score": quality,
        "instance_count": 0,
        "binding_count": 0,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.created_at.isoformat(),
    }


@router.get("/agents")
async def list_agents_view(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = DEFAULT_WINDOW_HOURS,
) -> dict:
    assert_permission(container, actor, Permission.ASSET_READ)
    agents = await container.assets.list_agents(actor.workspace_id)
    items = [
        await _agent_row(container, agent, actor.workspace_id, window_hours)
        for agent in agents
    ]
    return list_response(items)


@router.get("/agents/{agent_id}")
async def get_agent_detail(
    agent_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = DEFAULT_WINDOW_HOURS,
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.ASSET_READ,
        ResourceRef(kind="asset", id=agent_id, workspace_id=actor.workspace_id),
    )
    # 用领域对象（含 description / connect_type / created_at），不是投影
    agent = await container.assets.get_agent(agent_id, actor.workspace_id)
    workspace_id = actor.workspace_id
    base = await _agent_row(container, agent, workspace_id, window_hours)

    versions = await container.assets.list_versions(agent_id, workspace_id)
    credentials = [
        item
        for item in await container.assets.list_credentials(workspace_id)
        if item.asset_id == agent_id
    ]
    promotions = await container.delivery.list_promotions(agent_id, workspace_id)
    templates = await container.evaluations.list_templates_for_asset(agent_id, workspace_id)
    traces, trace_total = await container.traces.list_traces(
        workspace_id, _trace_query(agent_id), None
    )

    return ok(
        {
            **base,
            "versions": [
                {
                    "id": version.id,
                    "version": version.version_label,
                    "status": version.lifecycle.value,
                    "source_type": version.spec.get("connect_type"),
                    "source_uri": _source_ref(dict(version.spec), agent.name),
                    "created_at": version.created_at.isoformat(),
                }
                for version in versions
            ],
            "instances": [],  # 常驻实例由执行面管理，控制台暂不展示
            "bindings": [
                {
                    "id": template.id,
                    "policy_name": template.name,
                    "dataset_name": template.dataset_id or "",
                    "schedule": template.trigger_type,
                    "failure_threshold": 0,
                    "enabled": 1 if template.enabled else 0,
                }
                for template in templates
            ],
            "releases": [
                {
                    "id": item.id,
                    "version": item.version_id,
                    "from_version": item.from_channel.value,
                    "channel": item.to_channel.value,
                    "status": "completed" if item.gate_passed else "failed",
                    "created_at": item.created_at.isoformat(),
                }
                for item in promotions
            ],
            "health_checks": [],
            "credentials": [
                {
                    "id": item.id,
                    "name": item.name,
                    "kind": item.kind.value,
                    "last_four": item.last_four,
                    "updated_at": item.created_at.isoformat(),
                }
                for item in credentials
            ],
            "sdk_trace_count": trace_total,
            "invocations": [
                {
                    "id": trace.id,
                    "instance_id": trace.asset_version_id,
                    "caller_type": trace.ingested_via,
                    "input": _as_text(trace.input),
                    "output": _as_text(trace.output),
                    "status": trace.status,
                    "latency_ms": _duration_ms(trace),
                    "error": None,
                    "created_at": trace.started_at.isoformat(),
                }
                for trace in traces
            ],
        }
    )


def _trace_query(agent_id: str):
    from ..modules.observability.application.services import TraceQuery

    return TraceQuery(asset_id=agent_id, limit=50)


def _duration_ms(trace: Any) -> int:
    if trace.ended_at is None:
        return 0
    return int((trace.ended_at - trace.started_at).total_seconds() * 1000)


def _as_text(value: Any) -> str:
    import json

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


__all__: Sequence[str] = ["router"]

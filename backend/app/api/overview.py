"""工作区质量总览。

**组合层读模型**：跨模块聚合，只做计数与拼装，不含业务规则。
之所以放在这里而不是某个模块里：它天然需要读 4 个模块的数据，
放进任一模块都会让那个模块反向依赖其余三个。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..container import Container
from ..contracts.common import RunStatus
from ..contracts.identity import Permission
from ..schemas.response import ok
from .deps import Actor, assert_permission, get_container

router = APIRouter(tags=["overview"])


@router.get("/overview")
async def workspace_overview(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    assert_permission(container, actor, Permission.WORKSPACE_READ)
    workspace_id = actor.workspace_id

    agents = await container.assets.list_agents(workspace_id)
    runs = await container.runs.list_runs(workspace_id)
    datasets = await container.datasets.list_datasets(workspace_id)
    templates = await container.evaluations.list_templates(workspace_id)
    capabilities = await container.evaluations.list_capabilities(workspace_id)
    binding_counts = await container.evaluations.binding_counts(workspace_id)

    running = [item for item in runs if item.status is RunStatus.RUNNING]
    completed = [item for item in runs if item.status is RunStatus.COMPLETED]

    # 已完成运行的平均分：从各自固化的结果里取，而不是重新算
    scores: list[float] = []
    for run in completed[:20]:
        result = await container.runs.get_result(run.id, workspace_id)
        if result is not None:
            scores.append(result.avg_score)
    average_score = (sum(scores) / len(scores)) if scores else None

    return ok(
        {
            "running_runs": len(running),
            "agent_count": len(agents),
            "completed_runs": len(completed),
            "average_score": average_score,
            "dataset_count": len(datasets),
            "template_count": len(templates),
            "enabled_templates": sum(1 for item in templates if item.enabled),
            "bound_agents": sum(binding_counts.values()),
            # 关键能力维度的当前得分与阈值（维度没跑过就没有分数，不补 0）
            "dimensions": [
                {
                    "id": dimension.id,
                    "name": dimension.name,
                    "capability": view.capability.name,
                    "score": dimension.score,
                    "threshold": dimension.threshold,
                    "weight": dimension.weight,
                }
                for view in capabilities
                for dimension in view.dimensions
            ][:12],
            "recent_runs": [
                {
                    "id": item.id,
                    "name": item.name,
                    "status": item.status.value,
                    "phase": item.stage.value,
                    "total_trials": item.total_trials,
                    "created_at": item.created_at.isoformat(),
                }
                for item in runs[:5]
            ],
        }
    )

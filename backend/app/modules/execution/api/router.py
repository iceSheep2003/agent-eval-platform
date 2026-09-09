"""execution 的 HTTP 路由。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import RunStatus, Verdict
from ....contracts.errors import NotFound
from ....contracts.identity import Permission, ResourceRef
from ....schemas.response import list_response, ok
from ..application.services import RunService
from .schemas import (
    CreateRunRequest,
    RunDTO,
    TrialDTO,
    run_dto,
    score_dto,
    summary_dto,
    trial_dto,
)

router = APIRouter(tags=["execution"])


def get_run_service(container: Annotated[Container, Depends(get_container)]) -> RunService:
    return container.runs


async def _run_dto(service: RunService, run, workspace_id: str) -> RunDTO:
    """列表也要带上通过数与平均分——前端运行列表直接展示这两列。"""
    trials = await service.list_trials(run.id, workspace_id)
    scores = await service.list_scores(run.id, workspace_id)
    passed = sum(1 for item in trials if item.verdict is Verdict.PASS)
    numeric = [
        float(item.value)
        for item in scores
        if isinstance(item.value, (int, float)) and item.status in {"pass", "fail"}
    ]
    avg = sum(numeric) / len(numeric) if numeric else 0.0
    finished = sum(1 for item in trials if item.is_finished)
    progress = (finished / len(trials) * 100) if trials else 0.0
    cost = sum((item.cost_usd for item in trials), start=type(run.cost_budget_usd)("0"))
    return run_dto(
        run, passed=passed, score=avg, cost=float(cost), progress=round(progress, 1)
    )


@router.post("/runs")
async def create_run(
    payload: CreateRunRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
) -> dict:
    assert_permission(container, actor, Permission.RUN_CREATE)
    run = await service.create_run(
        workspace_id=actor.workspace_id,
        created_by=actor.user_id,
        name=payload.name,
        asset_version_id=payload.asset_version_id,
        dataset_version_id=payload.dataset_version_id,
        template_id=payload.template_id,
        concurrency=payload.concurrency,
        cost_budget_usd=payload.cost_budget_usd,
        tenant_scope=payload.tenant_scope,
    )
    return ok((await _run_dto(service, run, actor.workspace_id)).model_dump())


@router.get("/runs")
async def list_runs(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
    status: RunStatus | None = None,
) -> dict:
    assert_permission(container, actor, Permission.RUN_READ)
    runs = await service.list_runs(actor.workspace_id, status)
    return list_response(
        [(await _run_dto(service, run, actor.workspace_id)).model_dump() for run in runs]
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
) -> dict:
    assert_permission(container, actor, Permission.RUN_READ)
    run = await service.get_run(run_id, actor.workspace_id)
    base = await _run_dto(service, run, actor.workspace_id)
    trials = await service.list_trials(run_id, actor.workspace_id)
    scores = await service.list_scores(run_id, actor.workspace_id)
    by_trial: dict[str, list[float]] = {}
    for item in scores:
        if isinstance(item.value, (int, float)):
            by_trial.setdefault(item.trial_id, []).append(float(item.value))
    return ok(
        {
            **base.model_dump(),
            "trials": [
                trial_dto(
                    trial,
                    score=(
                        sum(by_trial[trial.id]) / len(by_trial[trial.id])
                        if by_trial.get(trial.id)
                        else None
                    ),
                ).model_dump()
                for trial in trials
            ],
            "scores": [score_dto(item).model_dump() for item in scores],
        }
    )


@router.get("/runs/{run_id}/summary")
async def run_summary(
    run_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
) -> dict:
    assert_permission(container, actor, Permission.RUN_READ)
    result = await service.get_result(run_id, actor.workspace_id)
    if result is None:
        raise NotFound("运行结果（尚未固化）", run_id)
    return ok(summary_dto(result).model_dump())


@router.get("/runs/{run_id}/trials")
async def list_trials(
    run_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
) -> dict:
    assert_permission(container, actor, Permission.RUN_READ)
    trials = await service.list_trials(run_id, actor.workspace_id)
    return list_response([trial_dto(item).model_dump() for item in trials])


@router.get("/trials/{trial_id}")
async def get_trial(
    trial_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
) -> dict:
    trial = await service.get_trial(trial_id, actor.workspace_id)
    assert_permission(
        container,
        actor,
        Permission.RUN_READ,
        ResourceRef(kind="trial", id=trial.id, workspace_id=trial.workspace_id),
    )
    scores = [item for item in await service.list_scores(trial.run_id, actor.workspace_id)
              if item.trial_id == trial.id]
    numeric = [float(item.value) for item in scores if isinstance(item.value, (int, float))]
    return ok(
        {
            **trial_dto(
                trial, score=(sum(numeric) / len(numeric)) if numeric else None
            ).model_dump(),
            "scores": [score_dto(item).model_dump() for item in scores],
        }
    )


@router.post("/runs/{run_id}/{action}")
async def control_run(
    run_id: str,
    action: Literal["pause", "resume", "cancel"],
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    service: Annotated[RunService, Depends(get_run_service)],
) -> dict:
    assert_permission(
        container,
        actor,
        Permission.RUN_CONTROL,
        ResourceRef(kind="run", id=run_id, workspace_id=actor.workspace_id),
    )
    run = await service.control(run_id, actor.workspace_id, action)
    return ok((await _run_dto(service, run, actor.workspace_id)).model_dump())

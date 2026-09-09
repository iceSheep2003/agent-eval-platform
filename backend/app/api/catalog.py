from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import BenchmarkAdapterCreate, EnabledBody, PolicyCreate

router = APIRouter(prefix="/api", tags=["evaluation catalog"])


@router.get("/capabilities")
def capabilities(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_capabilities(workspace)}


@router.get("/policies")
def policies(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_policies(workspace)}


@router.post("/policies", status_code=201)
def create_policy(body: PolicyCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_policy(workspace, user["id"], body.model_dump())


@router.patch("/policies/{policy_id}")
def set_policy_enabled(policy_id: str, body: EnabledBody, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).set_policy_enabled(workspace, user["id"], policy_id, body.enabled)


@router.get("/datasets/catalog")
def dataset_catalog(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_datasets(workspace)}


@router.post("/datasets/import", status_code=201)
async def import_dataset(
    request: Request,
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    version: Annotated[str, Form()] = "0.1.0",
    file: Annotated[UploadFile, File()] = ...,
    workspace=Depends(workspace_id),
    user=Depends(current_user),
):
    require_workspace(request, user, workspace)
    content = await file.read()
    return service(request).import_dataset(workspace, user["id"], name, kind, version, file.filename or "dataset.jsonl", content)


@router.get("/benchmark-adapters")
def benchmark_adapters(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).repo.all("SELECT * FROM benchmark_adapters WHERE workspace_id=? ORDER BY created_at DESC", (workspace,))}


@router.post("/benchmark-adapters", status_code=201)
def create_benchmark_adapter(body: BenchmarkAdapterCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_benchmark_adapter(workspace, user["id"], body.model_dump())

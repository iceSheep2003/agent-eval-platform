from fastapi import APIRouter, Depends, Request

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import RunCreate

router = APIRouter(prefix="/api", tags=["evaluations"])


@router.get("/dashboard")
def dashboard(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).dashboard(workspace)


@router.get("/datasets")
def datasets(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_datasets(workspace)}


@router.get("/evaluation-templates")
def templates(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).repo.all("SELECT * FROM evaluation_templates WHERE workspace_id=? ORDER BY created_at DESC", (workspace,))}


@router.get("/runs")
def list_runs(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_runs(workspace)}


@router.post("/runs", status_code=202)
def create_run(body: RunCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_run(workspace, user["id"], body.model_dump())


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).get_run(workspace, run_id)


@router.post("/runs/{run_id}/{action}", status_code=202)
def run_action(run_id: str, action: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    if action not in {"pause", "resume", "stop"}:
        from fastapi import HTTPException
        raise HTTPException(404, "Unknown action")
    return service(request).run_action(workspace, user["id"], run_id, action)

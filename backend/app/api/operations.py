from fastapi import APIRouter, Depends, Request

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import AgentConfigChange, BindingCreate, EnabledBody, ReleaseCreate, RollbackCreate, WorkspaceSettingsUpdate

router = APIRouter(prefix="/api", tags=["operations"])


@router.post("/agents/{agent_id}/health-check", status_code=202)
def health_check(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).request_health_check(workspace, user["id"], agent_id)


@router.post("/agents/{agent_id}/config-changes", status_code=201)
def config_change(agent_id: str, body: AgentConfigChange, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).update_agent_config(workspace, user["id"], agent_id, body.model_dump())


@router.get("/agents/{agent_id}/bindings")
def bindings(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_bindings(workspace, agent_id)}


@router.post("/agents/{agent_id}/bindings", status_code=201)
def create_binding(agent_id: str, body: BindingCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_binding(workspace, user["id"], agent_id, body.model_dump())


@router.patch("/agents/{agent_id}/continuous-evaluation", status_code=204)
def continuous(agent_id: str, body: EnabledBody, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).set_continuous_evaluation(workspace, user["id"], agent_id, body.enabled)


@router.post("/agents/{agent_id}/releases", status_code=202)
def release(agent_id: str, body: ReleaseCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_release(workspace, user["id"], agent_id, body.model_dump())


@router.post("/agents/{agent_id}/rollback", status_code=202)
def rollback(agent_id: str, body: RollbackCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).rollback(workspace, user["id"], agent_id, body.target_version_id)


@router.get("/workspace-settings")
def get_settings(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).workspace_settings(workspace)


@router.put("/workspace-settings")
def put_settings(body: WorkspaceSettingsUpdate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).update_workspace_settings(workspace, user["id"], body.model_dump())


@router.get("/audit-logs")
def audit_logs(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).repo.all("SELECT * FROM audit_logs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 200", (workspace,))}

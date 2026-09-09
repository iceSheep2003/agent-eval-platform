from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import DeploymentTokenCreate
from backend.app.application.services import NotFoundError

router = APIRouter(tags=["deployment-gateway"])


@router.get("/api/agents/{agent_id}/access-tokens")
def list_tokens(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).get_agent(workspace, agent_id)
    return {"items": service(request).list_access_tokens(workspace, agent_id)}


@router.post("/api/agents/{agent_id}/access-tokens", status_code=201)
def create_token(agent_id: str, body: DeploymentTokenCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    token = service(request).create_access_token(workspace, user["id"], agent_id, body.name)
    token["invoke_url"] = f"/v1/agents/{agent_id}/invoke"
    return token


@router.post("/api/agents/{agent_id}/deploy", status_code=202)
def deploy(agent_id: str, body: DeploymentTokenCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).deploy_agent(workspace, user["id"], agent_id, body.name)


@router.delete("/api/access-tokens/{token_id}", status_code=204)
def revoke_token(token_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).revoke_access_token(workspace, user["id"], token_id)
    return Response(status_code=204)


@router.get("/api/agents/{agent_id}/invocations")
def list_invocations(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).get_agent(workspace, agent_id)
    return {"items": service(request).list_invocations(workspace, agent_id)}


@router.post("/api/agents/{agent_id}/invoke")
def invoke_from_console(agent_id: str, body: dict[str, Any], request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).invoke_agent(workspace, agent_id, body, f"console:{user['id']}")


@router.post("/v1/agents/{agent_id}/invoke")
def invoke_public(agent_id: str, body: dict[str, Any], request: Request, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing deployment Bearer token")
    try:
        workspace = service(request).workspace_for_access_token(agent_id, authorization.removeprefix("Bearer ").strip())
    except NotFoundError as exc:
        raise HTTPException(401, str(exc)) from exc
    return service(request).invoke_agent(workspace, agent_id, body, "deployment-token")

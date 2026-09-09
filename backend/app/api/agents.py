from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import AgentCreate, AgentStatusBody, CredentialBindingBody, CredentialCreate, InstanceCreate

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents")
def list_agents(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_agents(workspace)}


@router.post("/agents", status_code=201)
def create_agent(body: AgentCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_agent(workspace, user["id"], body.model_dump(exclude_none=True))


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).get_agent(workspace, agent_id)


@router.patch("/agents/{agent_id}/status")
def set_agent_status(agent_id: str, body: AgentStatusBody, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).set_agent_status(workspace, user["id"], agent_id, body.status)


@router.delete("/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).delete_agent(workspace, user["id"], agent_id)
    return Response(status_code=204)


@router.post("/agents/{agent_id}/versions", status_code=201)
def create_version(
    agent_id: str,
    request: Request,
    version: Annotated[str, Form()],
    source_type: Annotated[str, Form()] = "package",
    source_uri: Annotated[str | None, Form()] = None,
    image_ref: Annotated[str | None, Form()] = None,
    runtime_manifest: Annotated[str, Form()] = "{}",
    package: Annotated[UploadFile | None, File()] = None,
    workspace=Depends(workspace_id),
    user=Depends(current_user),
):
    require_workspace(request, user, workspace)
    return service(request).create_version(workspace, user["id"], agent_id, version, source_type, source_uri, image_ref, json.loads(runtime_manifest), package.file if package else None, package.filename if package else None)


@router.post("/credentials", status_code=201)
def store_credential(body: CredentialCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    agent_ids = list(dict.fromkeys([*body.agent_ids, *([body.agent_id] if body.agent_id else [])]))
    return service(request).store_credential(workspace, user["id"], agent_ids, body.provider, body.name, body.value)


@router.get("/credentials")
def list_credentials(request: Request, agent_id: str | None = None, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_credentials(workspace, agent_id)}


@router.delete("/credentials/{credential_id}", status_code=204)
def delete_credential(credential_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).delete_credential(workspace, user["id"], credential_id)
    return Response(status_code=204)


@router.put("/credentials/{credential_id}/bindings")
def update_credential_bindings(credential_id: str, body: CredentialBindingBody, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).set_credential_bindings(workspace, user["id"], credential_id, body.agent_ids)


@router.post("/agents/{agent_id}/instances", status_code=202)
def create_instance(agent_id: str, body: InstanceCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_instance(workspace, user["id"], agent_id, body.agent_version_id)


@router.post("/instances/{instance_id}/{action}", status_code=202)
def instance_action(instance_id: str, action: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    if action not in {"start", "stop", "delete"}:
        return Response(status_code=404)
    require_workspace(request, user, workspace)
    return service(request).instance_action(workspace, user["id"], instance_id, action)


@router.delete("/instances/{instance_id}", status_code=202)
def delete_instance(instance_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).instance_action(workspace, user["id"], instance_id, "delete")

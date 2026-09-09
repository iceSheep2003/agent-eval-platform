from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import SdkKeyCreate
from backend.app.application.services import NotFoundError


router = APIRouter(tags=["agent-sdk"])


@router.get("/api/agents/{agent_id}/sdk-keys")
def list_sdk_keys(agent_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).get_agent(workspace, agent_id)
    return {"items": service(request).list_sdk_keys(workspace, agent_id)}


@router.post("/api/agents/{agent_id}/sdk-keys", status_code=201)
def create_sdk_key(agent_id: str, body: SdkKeyCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    result = service(request).create_sdk_key(workspace, user["id"], agent_id, body.name)
    result["ingest_url"] = "/v1/traces"
    return result


@router.delete("/api/sdk-keys/{key_id}", status_code=204)
def revoke_sdk_key(key_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).revoke_sdk_key(workspace, user["id"], key_id)
    return Response(status_code=204)


@router.post("/v1/traces", status_code=202)
async def ingest_traces(request: Request, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer evk_"):
        raise HTTPException(401, "Missing Agent SDK Bearer key")
    raw = await request.body()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Trace batch exceeds 5 MiB")
    try:
        events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Body must be UTF-8 NDJSON") from exc
    if not events or len(events) > 1000:
        raise HTTPException(400, "Trace batch must contain 1 to 1000 events")
    try:
        key = service(request).agent_for_sdk_key(authorization.removeprefix("Bearer ").strip())
    except NotFoundError as exc:
        raise HTTPException(401, str(exc)) from exc
    return service(request).ingest_sdk_trace_events(key, events)


@router.get("/v1/agent-context")
def agent_context(request: Request, authorization: str | None = Header(default=None)):
    """Bootstrap the SDK-connected agent: workspace-public + agent-scoped knowledge/skills/MCP.

    Uses the same ``evk_`` SDK key as trace ingest, but read-only and scoped to the owning agent.
    """
    if not authorization or not authorization.startswith("Bearer evk_"):
        raise HTTPException(401, "Missing Agent SDK Bearer key")
    try:
        key = service(request).agent_for_sdk_key(authorization.removeprefix("Bearer ").strip())
    except NotFoundError as exc:
        raise HTTPException(401, str(exc)) from exc
    return service(request).agent_context(key["workspace_id"], key["agent_id"])

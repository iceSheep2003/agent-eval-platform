"""Console management for agent context resources: knowledge base, skills, MCP servers.

These are the controls behind the "平台补充/拓展知识库、公共 skill 与 MCP" affordances. Each
resource is workspace-scoped; ``agent_id = null`` marks a workspace-public entry that every
SDK-connected agent in the workspace receives via ``GET /v1/agent-context``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from backend.app.api.dependencies import current_user, require_workspace, service, workspace_id
from backend.app.api.schemas import KnowledgeCreate, McpServerCreate, SkillCreate

router = APIRouter(prefix="/api", tags=["agent context"])


@router.get("/knowledge")
def list_knowledge(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_knowledge(workspace)}


@router.post("/knowledge", status_code=201)
def create_knowledge(body: KnowledgeCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_knowledge(workspace, user["id"], body.model_dump())


@router.delete("/knowledge/{knowledge_id}", status_code=204)
def delete_knowledge(knowledge_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).delete_knowledge(workspace, user["id"], knowledge_id)
    return Response(status_code=204)


@router.get("/skills")
def list_skills(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_skills(workspace)}


@router.post("/skills", status_code=201)
def create_skill(body: SkillCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_skill(workspace, user["id"], body.model_dump())


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).delete_skill(workspace, user["id"], skill_id)
    return Response(status_code=204)


@router.get("/mcp-servers")
def list_mcp_servers(request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return {"items": service(request).list_mcp_servers(workspace)}


@router.post("/mcp-servers", status_code=201)
def create_mcp_server(body: McpServerCreate, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    return service(request).create_mcp_server(workspace, user["id"], body.model_dump())


@router.delete("/mcp-servers/{mcp_id}", status_code=204)
def delete_mcp_server(mcp_id: str, request: Request, workspace=Depends(workspace_id), user=Depends(current_user)):
    require_workspace(request, user, workspace)
    service(request).delete_mcp_server(workspace, user["id"], mcp_id)
    return Response(status_code=204)
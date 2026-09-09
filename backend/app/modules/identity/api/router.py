"""identity 的 HTTP 路由。

挂载点由 `app/main.py` 决定：同一批 router 同时挂 `/api` 与 `/api/v1`
（前者是前端与 `register.py` 已在用的兼容面）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from ....api.deps import Actor, clear_session_cookie, get_container, set_session_cookie
from ....container import Container
from ....contracts.errors import NotFound
from ....schemas.response import list_response, ok
from ..application.services import IdentityService
from .schemas import LoginRequest, session_payload, workspace_list

auth_router = APIRouter(prefix="/auth", tags=["identity"])
workspace_router = APIRouter(tags=["identity"])


def get_identity(container: Annotated[Container, Depends(get_container)]) -> IdentityService:
    return container.identity


@auth_router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    user, token = await identity.login_local(
        payload.identifier,
        payload.password,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    set_session_cookie(
        response, container, token, container.settings.session_absolute_hours * 3600
    )
    workspaces = await identity.list_workspaces(user.id)
    roles = await identity.role_map(user.id)
    return ok(session_payload(user, workspaces, roles).model_dump())


@auth_router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    await identity.logout(request.cookies.get(container.settings.cookie_name, ""))
    clear_session_cookie(response, container)
    return ok({"ok": True})


@auth_router.get("/me")
async def me(
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    user = await identity.get_user(actor.user_id)
    if user is None:
        raise NotFound("用户", actor.user_id)
    workspaces = await identity.list_workspaces(user.id)
    roles = await identity.role_map(user.id)
    return ok(
        session_payload(
            user, workspaces, roles, current_workspace_id=actor.workspace_id
        ).model_dump()
    )


@workspace_router.get("/workspaces")
async def list_workspaces(
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    workspaces = await identity.list_workspaces(actor.user_id)
    return list_response(workspace_list(workspaces, await identity.role_map(actor.user_id)))


@workspace_router.get("/me/permissions")
async def my_permissions(
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    return list_response(sorted(p.value for p in identity.permissions_of(actor.subject)))

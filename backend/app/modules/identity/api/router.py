"""identity 的 HTTP 路由。

挂载点由 `app/main.py` 决定：同一批 router 同时挂 `/api` 与 `/api/v1`
（前者是前端与 `register.py` 已在用的兼容面）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from ....api.deps import (
    Actor,
    assert_permission,
    clear_session_cookie,
    get_container,
    set_session_cookie,
)
from ....container import Container
from ....contracts.common import OrgRole, WorkspaceRole
from ....contracts.errors import DomainError, Errors, NotFound, PermissionDenied
from ....contracts.identity import Permission
from ....schemas.response import list_response, ok
from ..application.services import IdentityService
from .schemas import (
    AddMemberRequest,
    CreateWorkspaceRequest,
    LoginRequest,
    UpdateMemberRoleRequest,
    member_dto,
    organization_dto,
    session_payload,
    workspace_list,
)

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
    organizations = await identity.list_organizations(user.id)
    org_roles = {
        org.id: (await identity.org_role_of(org.id, user.id)).value  # type: ignore[union-attr]
        for org in organizations
    }
    return ok(
        session_payload(
            user, workspaces, roles, organizations=organizations, org_roles=org_roles
        ).model_dump()
    )


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
    organizations = await identity.list_organizations(user.id)
    org_roles = {
        org.id: (await identity.org_role_of(org.id, user.id)).value  # type: ignore[union-attr]
        for org in organizations
    }
    return ok(
        session_payload(
            user,
            workspaces,
            roles,
            current_workspace_id=actor.workspace_id,
            organizations=organizations,
            org_roles=org_roles,
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


# --------------------------------------------------------------------------- #
# 组织与成员
# --------------------------------------------------------------------------- #

#: 组织级管理动作只允许 owner / admin
ORG_ADMIN_ROLES = {OrgRole.OWNER, OrgRole.ADMIN}


async def _require_org_admin(
    identity: IdentityService, actor, organization_id: str
) -> None:
    """组织成员管理不走工作区角色——它是**组织层**的事。"""
    role = await identity.org_role_of(organization_id, actor.user_id)
    if role is None:
        raise NotFound("组织", organization_id)
    if role not in ORG_ADMIN_ROLES:
        raise PermissionDenied("org:member:manage", f"组织角色 {role.value} 无权管理成员")


@workspace_router.get("/organizations")
async def list_organizations(
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    organizations = await identity.list_organizations(actor.user_id)
    items = []
    for organization in organizations:
        role = await identity.org_role_of(organization.id, actor.user_id)
        items.append(organization_dto(organization, role.value if role else None).model_dump())
    return list_response(items)


@workspace_router.get("/organizations/{organization_id}/members")
async def list_org_members(
    organization_id: str,
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    await _require_org_admin(identity, actor, organization_id)
    rows = await identity.list_org_members(organization_id)
    return list_response(
        [
            {
                "user_id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role": membership.role.value,
            }
            for membership, user in rows
        ]
    )


@workspace_router.post("/organizations/{organization_id}/members")
async def add_org_member(
    organization_id: str,
    payload: AddMemberRequest,
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    await _require_org_admin(identity, actor, organization_id)
    membership = await identity.add_org_member(
        organization_id, payload.identifier, OrgRole(payload.role)
    )
    return ok({"organization_id": organization_id, "user_id": membership.user_id,
               "role": membership.role.value})


@workspace_router.patch("/organizations/{organization_id}/members/{user_id}")
async def update_org_member(
    organization_id: str,
    user_id: str,
    payload: UpdateMemberRoleRequest,
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    await _require_org_admin(identity, actor, organization_id)
    await identity.set_org_member_role(organization_id, user_id, OrgRole(payload.role))
    return ok({"organization_id": organization_id, "user_id": user_id, "role": payload.role})


@workspace_router.delete("/organizations/{organization_id}/members/{user_id}")
async def remove_org_member(
    organization_id: str,
    user_id: str,
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    await _require_org_admin(identity, actor, organization_id)
    await identity.remove_org_member(organization_id, user_id)
    return ok({"organization_id": organization_id, "user_id": user_id})


@workspace_router.post("/workspaces")
async def create_workspace(
    payload: CreateWorkspaceRequest,
    actor: Actor,
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    if actor.organization_id is None:
        raise DomainError(Errors.VALIDATION_FAILED, "当前会话没有绑定组织")
    role = await identity.org_role_of(actor.organization_id, actor.user_id)
    if role not in ORG_ADMIN_ROLES:
        raise PermissionDenied("workspace:create", "只有组织 owner / admin 能新建项目")
    workspace = await identity.create_workspace(
        organization_id=actor.organization_id,
        owner_id=actor.user_id,
        slug=payload.slug,
        name=payload.name,
    )
    return ok(workspace_dto(workspace, WorkspaceRole.OWNER.value).model_dump())


@workspace_router.get("/workspaces/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    assert_permission(container, actor, Permission.WORKSPACE_READ)
    members = await identity.list_members(workspace_id)
    return list_response([member_dto(item).model_dump() for item in members])


@workspace_router.post("/workspaces/{workspace_id}/members")
async def add_workspace_member(
    workspace_id: str,
    payload: AddMemberRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    assert_permission(container, actor, Permission.MEMBER_INVITE)
    member = await identity.add_workspace_member(
        workspace_id, payload.identifier, WorkspaceRole(payload.role)
    )
    return ok(member_dto(member).model_dump())


@workspace_router.patch("/workspaces/{workspace_id}/members/{user_id}")
async def update_workspace_member(
    workspace_id: str,
    user_id: str,
    payload: UpdateMemberRoleRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    assert_permission(container, actor, Permission.MEMBER_ROLE_WRITE)
    await identity.set_workspace_member_role(
        workspace_id, user_id, WorkspaceRole(payload.role)
    )
    return ok({"workspace_id": workspace_id, "user_id": user_id, "role": payload.role})


@workspace_router.delete("/workspaces/{workspace_id}/members/{user_id}")
async def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> dict:
    assert_permission(container, actor, Permission.MEMBER_REMOVE)
    await identity.remove_workspace_member(workspace_id, user_id)
    return ok({"workspace_id": workspace_id, "user_id": user_id})

"""identity 的 HTTP DTO。

字段名对齐前端 `frontend-pro/src/services/eval/index.ts` 的 `EvalUser` / `Workspace`，
改这里等于改前端类型定义。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, Field

from ....contracts.identity import MemberRef
from ..domain.models import Invitation, Organization, User, Workspace


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class UserDTO(BaseModel):
    id: str
    username: str
    display_name: str
    email: str | None = None
    role: str | None = None


class WorkspaceDTO(BaseModel):
    id: str
    name: str
    description: str | None = None
    role: str | None = None
    member_count: int | None = None
    #: 项目所属组织（前端按组织分组展示）
    organization_id: str | None = None


class OrganizationDTO(BaseModel):
    id: str
    slug: str
    name: str
    role: str | None = None


class MemberDTO(BaseModel):
    """工作区成员。`owner_id` 这类字段必须从成员里选，不能收任意字符串。"""

    user_id: str
    username: str
    display_name: str
    email: str | None = None
    role: str


class AddMemberRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255, description="用户名或邮箱")
    role: str = Field(default="viewer")


class UpdateMemberRoleRequest(BaseModel):
    role: str


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(default="member")


class InvitationDTO(BaseModel):
    id: str
    organization_id: str
    email: str
    role: str
    status: str
    invited_by: str
    created_at: str
    expires_at: str
    accepted_at: str | None = None


class CreateWorkspaceRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=128)


class SessionPayload(BaseModel):
    """前端 `GET /api/auth/me` 与 `POST /api/auth/login` 的响应体。"""

    user: UserDTO
    workspaces: list[WorkspaceDTO]
    organizations: list[OrganizationDTO] = []


def workspace_dto(workspace: Workspace, role: str | None = None) -> WorkspaceDTO:
    return WorkspaceDTO(
        id=workspace.id,
        name=workspace.name,
        role=role,
        organization_id=workspace.organization_id,
    )


def organization_dto(
    organization: Organization, role: str | None = None
) -> OrganizationDTO:
    return OrganizationDTO(
        id=organization.id, slug=organization.slug, name=organization.name, role=role
    )


def invitation_dto(invitation: Invitation) -> InvitationDTO:
    return InvitationDTO(
        id=invitation.id,
        organization_id=invitation.organization_id,
        email=invitation.email,
        role=invitation.role.value,
        status=invitation.status,
        invited_by=invitation.invited_by,
        created_at=invitation.created_at.isoformat(),
        expires_at=invitation.expires_at.isoformat(),
        accepted_at=invitation.accepted_at.isoformat() if invitation.accepted_at else None,
    )


def member_dto(member: MemberRef) -> MemberDTO:
    return MemberDTO(
        user_id=member.user_id,
        username=member.username,
        display_name=member.display_name,
        email=member.email,
        role=member.role.value,
    )


def session_payload(
    user: User,
    workspaces: Sequence[Workspace],
    roles: Mapping[str, str],
    *,
    current_workspace_id: str | None = None,
    organizations: Sequence[Organization] = (),
    org_roles: Mapping[str, str] | None = None,
) -> SessionPayload:
    org_role_map = org_roles or {}
    return SessionPayload(
        user=UserDTO(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=roles.get(current_workspace_id or "", None),
        ),
        workspaces=[workspace_dto(ws, roles.get(ws.id)) for ws in workspaces],
        organizations=[
            organization_dto(org, org_role_map.get(org.id)) for org in organizations
        ],
    )


def workspace_list(
    workspaces: Sequence[Workspace], roles: Mapping[str, str]
) -> list[dict]:
    return [workspace_dto(ws, roles.get(ws.id)).model_dump() for ws in workspaces]

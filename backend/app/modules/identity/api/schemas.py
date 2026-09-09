"""identity 的 HTTP DTO。

字段名对齐前端 `frontend-pro/src/services/eval/index.ts` 的 `EvalUser` / `Workspace`，
改这里等于改前端类型定义。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, Field

from ..domain.models import User, Workspace


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


class SessionPayload(BaseModel):
    """前端 `GET /api/auth/me` 与 `POST /api/auth/login` 的响应体。"""

    user: UserDTO
    workspaces: list[WorkspaceDTO]


def session_payload(
    user: User,
    workspaces: Sequence[Workspace],
    roles: Mapping[str, str],
    *,
    current_workspace_id: str | None = None,
) -> SessionPayload:
    return SessionPayload(
        user=UserDTO(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=roles.get(current_workspace_id or "", None),
        ),
        workspaces=[
            WorkspaceDTO(id=ws.id, name=ws.name, role=roles.get(ws.id)) for ws in workspaces
        ],
    )


def workspace_list(
    workspaces: Sequence[Workspace], roles: Mapping[str, str]
) -> list[dict]:
    return [
        WorkspaceDTO(id=ws.id, name=ws.name, role=roles.get(ws.id)).model_dump()
        for ws in workspaces
    ]

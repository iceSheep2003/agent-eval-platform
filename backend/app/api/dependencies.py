from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, Request


def service(request: Request):
    return request.app.state.container.service


def current_user(request: Request, sid: str | None = Cookie(default=None)) -> dict:
    user = service(request).user_for_session(sid)
    if not user:
        raise HTTPException(401, "未登录")
    return user


def workspace_id(x_workspace_id: str = Header(default="eval-dev")) -> str:
    return x_workspace_id


def require_workspace(request: Request, user: dict, workspace: str) -> None:
    allowed = {item["id"] for item in service(request).workspaces_for_user(user["id"])}
    if workspace not in allowed:
        raise HTTPException(403, "无权访问该工作区")

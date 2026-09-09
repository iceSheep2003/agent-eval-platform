from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from backend.app.api.dependencies import current_user, service
from backend.app.api.schemas import LoginBody

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    result = service(request).authenticate(body.identifier.strip(), body.password)
    if not result:
        raise HTTPException(401, "账号或密码错误")
    user, workspaces, session_id = result
    response.set_cookie("sid", session_id, max_age=8 * 3600, httponly=True, samesite="lax")
    return {"user": user, "workspaces": workspaces}


@router.get("/me")
def me(request: Request, user=Depends(current_user)):
    return {"user": service(request).public_user(user), "workspaces": service(request).workspaces_for_user(user["id"])}


@router.post("/logout")
def logout(request: Request, response: Response, sid: str | None = Cookie(default=None)):
    service(request).logout(sid)
    response.delete_cookie("sid")
    return {"ok": True}

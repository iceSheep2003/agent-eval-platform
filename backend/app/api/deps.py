"""共享 HTTP 依赖：会话解析与权限守卫。

放在 `app/api/` 而不是 identity 模块里——**每个模块的路由都需要它**，
让它属于 identity 会迫使所有模块反向依赖 identity 的实现（架构检查会拦下）。
这里只依赖 `contracts/identity` 的类型，实现由 `container` 装配。
"""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, Header, Request, Response

from ..container import Container
from ..contracts.errors import Errors, PermissionDenied
from ..contracts.identity import ActorContext, Permission, ResourceRef

WORKSPACE_HEADER = "x-workspace-id"


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("应用未装配 Container")
    return container


async def get_actor(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    workspace_ref: Annotated[str | None, Header(alias=WORKSPACE_HEADER)] = None,
) -> ActorContext:
    raw = request.cookies.get(container.settings.cookie_name, "")
    actor = await container.identity.resolve(raw, workspace_ref)
    if actor is None:
        raise PermissionDenied("登录", str(Errors.UNAUTHENTICATED.message))
    return actor


Actor = Annotated[ActorContext, Depends(get_actor)]


def assert_permission(
    container: Container,
    actor: ActorContext,
    permission: Permission,
    resource: ResourceRef | None = None,
) -> None:
    """无资源的权限检查。资源级检查用各模块自己的 `require_on_*` 依赖。"""
    decision = container.authorizer.decide(actor.subject, permission, resource)
    if not decision.allowed:
        raise PermissionDenied(permission.value, decision.reason)


def require(permission: Permission) -> Callable[..., ActorContext]:
    """路由守卫：只需权限点、不需要资源的场景。"""

    async def dependency(
        container: Annotated[Container, Depends(get_container)],
        actor: Actor,
    ) -> ActorContext:
        assert_permission(container, actor, permission)
        return actor

    return dependency


def set_session_cookie(
    response: Response, container: Container, token: str, max_age_seconds: int
) -> None:
    response.set_cookie(
        key=container.settings.cookie_name,
        value=token,
        max_age=max_age_seconds,
        httponly=True,
        secure=container.settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, container: Container) -> None:
    response.delete_cookie(key=container.settings.cookie_name, path="/")

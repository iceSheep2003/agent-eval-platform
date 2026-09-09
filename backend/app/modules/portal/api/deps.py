"""portal 的请求依赖。

**与平台的 `app/api/deps.py` 是两条独立的鉴权链**：这里认 portal cookie，
那里认平台 cookie。两者的会话表、cookie 名、账号体系都不相交。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Response

from ....api.deps import get_container
from ....container import Container
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.common import Id
from ..application.services import PortalAuthService
from ..domain.models import PortalHub, PortalUser, HubRole
from ..domain.permission import PortalDecision, decide_portal

PORTAL_COOKIE_PATH = "/"


@dataclass(frozen=True, slots=True)
class PortalActor:
    """一次已认证的展示平台请求。`hub` 只在门户内路由上非空。"""

    user: PortalUser
    hub: PortalHub | None = None
    role: HubRole | None = None


def get_portal_auth(container: Annotated[Container, Depends(get_container)]) -> PortalAuthService:
    return container.portal_auth


def get_portal_service(container: Annotated[Container, Depends(get_container)]):
    return container.portal


def set_portal_cookie(response: Response, container: Container, token: str) -> None:
    response.set_cookie(
        key=container.settings.portal_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=container.settings.env == "production",
        path=PORTAL_COOKIE_PATH,
    )


def clear_portal_cookie(response: Response, container: Container) -> None:
    response.delete_cookie(container.settings.portal_cookie_name, path=PORTAL_COOKIE_PATH)


async def get_portal_actor(
    request: Request,
    auth: Annotated[PortalAuthService, Depends(get_portal_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> PortalActor:
    raw = request.cookies.get(container.settings.portal_cookie_name, "")
    user = await auth.resolve(raw)
    if user is None:
        raise DomainError(Errors.UNAUTHENTICATED, "未登录或会话已过期")
    return PortalActor(user=user)


async def _resolve_hub(
    hub_id: str,
    actor: PortalActor,
    auth: PortalAuthService,
    container: Container,
    action: str,
) -> PortalActor:
    """解析门户成员身份。**非成员一律 404**——不让外部用户枚举出门户是否存在。"""
    membership = await auth.membership(hub_id, actor.user.id)
    decision: PortalDecision = decide_portal(membership, action, hub_id)
    if not decision.allowed:
        raise NotFound("门户", hub_id)
    assert membership is not None  # decide_portal 已保证
    hub = await container.portal.get_hub_unscoped(hub_id)
    return PortalActor(user=actor.user, hub=hub, role=membership.role)


def require_hub(action: str):
    async def dependency(
        hub_id: str,
        actor: Annotated[PortalActor, Depends(get_portal_actor)],
        auth: Annotated[PortalAuthService, Depends(get_portal_auth)],
        container: Annotated[Container, Depends(get_container)],
    ) -> PortalActor:
        return await _resolve_hub(hub_id, actor, auth, container, action)

    return dependency


PortalActorDep = Annotated[PortalActor, Depends(get_portal_actor)]
HubActorDep = Annotated[PortalActor, Depends(require_hub("hub:read"))]


def hub_workspace_id(actor: PortalActor) -> Id:
    assert actor.hub is not None
    return actor.hub.workspace_id

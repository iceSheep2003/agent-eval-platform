"""portal 的 HTTP 路由。

两条面：
- `/portal/*`      —— 展示平台用户（portal cookie）。只读 + 对话。
- `/portal-admin/*` —— 平台运营者（平台 cookie + `PORTAL_PROVISION`）。供给账号/门户/成员/挂载。

对话的线格式是 **OpenAI 兼容分块**，这样前端可以直接用 `@ant-design/x-sdk` 的
`OpenAIChatProvider`，不必自己写 SSE 解析。
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.common import Channel
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.execution import ChannelInvocation
from ....contracts.identity import Permission
from ....schemas.response import list_response, ok
from ..application.services import (
    AgentView,
    CHAT_LIMIT_PER_MINUTE,
    PortalService,
    HubView,
)
from .deps import (
    PortalActor,
    PortalActorDep,
    HubActorDep,
    clear_portal_cookie,
    get_portal_auth,
    get_portal_service,
    require_hub,
    set_portal_cookie,
)
from .schemas import (
    AddHubMemberRequest,
    AttachHubAgentRequest,
    BindPortalChannelRequest,
    ChannelViewDTO,
    CreatePortalHubRequest,
    CreatePortalUserRequest,
    PortalAgentDTO,
    PortalChatRequest,
    PortalLoginRequest,
    PortalHubDTO,
    PortalSessionDTO,
    PortalUserDTO,
    SetPortalUserStatusRequest,
)

router = APIRouter(tags=["portal"])

#: 流式对话的心跳间隔。本地沙箱是「跑完才出结果」，心跳让中间代理不掐断连接。
KEEPALIVE_SECONDS = 15.0


def _hub_dto(view: HubView) -> PortalHubDTO:
    return PortalHubDTO(
        id=view.hub.id,
        slug=view.hub.slug,
        name=view.hub.name,
        description=view.hub.description,
        my_role=view.role,
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _agent_dto(view: AgentView) -> PortalAgentDTO:
    return PortalAgentDTO(
        id=view.id,
        asset_id=view.asset_id,
        name=view.name,
        display_name=view.display_name,
        description=view.description,
        lifecycle=view.lifecycle,
        channels=[
            ChannelViewDTO(
                channel=item.channel.value,
                label=item.label,
                bound=item.bound,
                version_id=item.version_id,
                version_label=item.version_label,
            )
            for item in view.channels
        ],
    )


# --------------------------------------------------------------------------- #
# 展示平台面（portal cookie）
# --------------------------------------------------------------------------- #


@router.post("/portal/auth/login")
async def portal_login(
    payload: PortalLoginRequest,
    request: Request,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    issued = await container.portal_auth.login(payload.identifier, payload.password)
    if issued is None:
        # 失败也要记：登录失败序列是账号被盗的信号
        await container.audit.record(
            action="portal.login",
            actor_kind="portal_user",
            actor_id=payload.identifier,
            detail={"ok": False},
            ip=_client_ip(request),
        )
        raise DomainError(Errors.UNAUTHENTICATED, "用户名或密码不正确")
    await container.audit.record(
        action="portal.login",
        actor_kind="portal_user",
        actor_id=issued.user.id,
        detail={"ok": True, "username": issued.user.username},
        ip=_client_ip(request),
    )
    set_portal_cookie(response, container, issued.token)
    hubs = await container.portal.list_hubs_for_user(issued.user.id)
    return ok(
        PortalSessionDTO(
            user=PortalUserDTO(
                id=issued.user.id,
                username=issued.user.username,
                display_name=issued.user.display_name,
                email=issued.user.email,
                status=issued.user.status,
            ),
            hubs=[_hub_dto(item) for item in hubs],
        ).model_dump()
    )


@router.post("/portal/auth/logout")
async def portal_logout(
    request: Request,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    raw = request.cookies.get(container.settings.portal_cookie_name, "")
    user = await container.portal_auth.resolve(raw)
    await container.portal_auth.logout(raw)
    if user is not None:
        await container.audit.record(
            action="portal.logout",
            actor_kind="portal_user",
            actor_id=user.id,
            ip=_client_ip(request),
        )
    clear_portal_cookie(response, container)
    return ok({"ok": True})


@router.get("/portal/me")
async def portal_me(
    actor: PortalActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    hubs = await portal.list_hubs_for_user(actor.user.id)
    return ok(
        PortalSessionDTO(
            user=PortalUserDTO(
                id=actor.user.id,
                username=actor.user.username,
                display_name=actor.user.display_name,
                email=actor.user.email,
                status=actor.user.status,
            ),
            hubs=[_hub_dto(item) for item in hubs],
        ).model_dump()
    )


@router.get("/portal/hubs/{hub_id}")
async def portal_hub(
    actor: HubActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    assert actor.hub is not None
    return ok(
        PortalHubDTO(
            id=actor.hub.id,
            slug=actor.hub.slug,
            name=actor.hub.name,
            description=actor.hub.description,
            my_role=actor.role,
        ).model_dump()
    )


@router.get("/portal/hubs/{hub_id}/agents")
async def portal_agents(
    actor: HubActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    assert actor.hub is not None
    views = await portal.list_hub_agents(actor.hub.id, actor.hub.workspace_id)
    return list_response([_agent_dto(view).model_dump() for view in views])


@router.get("/portal/hubs/{hub_id}/agents/{hub_agent_id}")
async def portal_agent(
    hub_agent_id: str,
    actor: HubActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    assert actor.hub is not None
    view = await portal.get_hub_agent(
        hub_agent_id, actor.hub.id, actor.hub.workspace_id
    )
    return ok(_agent_dto(view).model_dump())


# --------------------------------------------------------------------------- #
# 对话（portal cookie；线格式 OpenAI 兼容）
# --------------------------------------------------------------------------- #


def _chunk(
    *,
    chunk_id: str,
    model: str,
    created: int,
    delta: dict,
    finish_reason: str | None = None,
) -> str:
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _error_frame(code: str, message: str) -> str:
    body = json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False)
    return f"event: error\ndata: {body}\n\n"


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


@router.post("/portal/hubs/{hub_id}/agents/{hub_agent_id}/channels/{channel}/chat")
async def portal_chat(
    hub_agent_id: str,
    channel: Channel,
    payload: PortalChatRequest,
    request: Request,
    actor: Annotated[PortalActor, Depends(require_hub("agent:chat"))],
    portal: Annotated[PortalService, Depends(get_portal_service)],
    container: Annotated[Container, Depends(get_container)],
):
    assert actor.hub is not None
    hub = actor.hub
    model = f"{hub_agent_id}@{channel.value}"
    message = payload.resolved_message()
    if not message.strip():
        raise DomainError(Errors.VALIDATION_FAILED, "对话内容为空")

    # 限流放在开流之前：超限时还能返回正常的 429 JSON，而不是一条已经开始的 SSE。
    allowed = await container.portal_limiter.consume(
        scope="chat", subject_id=actor.user.id, limit=CHAT_LIMIT_PER_MINUTE
    )
    if not allowed:
        await container.audit.record(
            action="portal.chat",
            actor_kind="portal_user",
            actor_id=actor.user.id,
            workspace_id=hub.workspace_id,
            target_kind="portal_agent",
            target_id=hub_agent_id,
            detail={"channel": channel.value, "rejected": "rate_limited"},
            ip=_client_ip(request),
        )
        raise DomainError(
            Errors.RATE_LIMITED,
            f"对话太频繁，每分钟最多 {CHAT_LIMIT_PER_MINUTE} 次",
        )
    # 记「发起了调用」；调用结果由 Trace 记录，两者靠 request 时间对齐
    await container.audit.record(
        action="portal.chat",
        actor_kind="portal_user",
        actor_id=actor.user.id,
        workspace_id=hub.workspace_id,
        target_kind="portal_agent",
        target_id=hub_agent_id,
        detail={"channel": channel.value, "stream": payload.stream},
        ip=_client_ip(request),
    )

    if not payload.stream:
        result = await portal.chat(
            hub_agent_id=hub_agent_id,
            hub_id=hub.id,
            workspace_id=hub.workspace_id,
            channel=channel,
            message=message,
            messages=payload.messages,
            timeout_seconds=payload.timeout_seconds,
        )
        return ok(
            {
                "id": f"chatcmpl-{hub_agent_id}",
                "object": "chat.completion",
                "model": model,
                "channel": channel.value,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": result.error or _as_text(result.output),
                        },
                        "finish_reason": "error" if result.error else "stop",
                    }
                ],
                "version": result.version_label,
                "trace_id": result.trace_id,
            }
        )

    async def stream() -> AsyncIterator[str]:
        """**生成器必须自己兜住所有异常**——响应头一旦发出，
        `app/api/errors.py` 的全局 handler 就再也修不了这条流了。"""
        created = int(container.clock.now().timestamp())
        chunk_id = f"chatcmpl-{hub_agent_id}"
        # 先发角色帧，让前端的空气泡立刻出现，不必等被测 Agent 跑完。
        yield _chunk(
            chunk_id=chunk_id,
            model=model,
            created=created,
            delta={"role": "assistant", "content": ""},
        )

        task = asyncio.create_task(
            portal.chat(
                hub_agent_id=hub_agent_id,
                hub_id=hub.id,
                workspace_id=hub.workspace_id,
                channel=channel,
                message=message,
                messages=payload.messages,
                timeout_seconds=payload.timeout_seconds,
            )
        )
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=KEEPALIVE_SECONDS)
                if done:
                    break
                if await request.is_disconnected():
                    task.cancel()
                    return
                yield ": keep-alive\n\n"
            result = await task
        except DomainError as exc:
            yield _error_frame(exc.code, str(exc))
            yield "data: [DONE]\n\n"
            return
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - 流已开始，只能自己收尾
            yield _error_frame(Errors.NOT_FOUND.code, f"{type(exc).__name__}: {exc}")
            yield "data: [DONE]\n\n"
            return

        if result.error is not None:
            yield _error_frame("invoke_failed", result.error)
        else:
            yield _chunk(
                chunk_id=chunk_id,
                model=model,
                created=created,
                delta={"content": _as_text(result.output)},
            )
            yield _chunk(
                chunk_id=chunk_id,
                model=model,
                created=created,
                delta={},
                finish_reason="stop",
            )
        yield "data: [DONE]\n\n"

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "X-Eval-Loom-Channel": channel.value,
    }
    return StreamingResponse(
        stream(), media_type="text/event-stream; charset=utf-8", headers=headers
    )


# --------------------------------------------------------------------------- #
# 运营侧供给面（平台 cookie + PORTAL_PROVISION）
# --------------------------------------------------------------------------- #


def _assert_provision(container: Container, actor: Actor) -> None:
    assert_permission(container, actor, Permission.PORTAL_PROVISION)


@router.post("/portal-admin/users")
async def create_portal_user(
    payload: CreatePortalUserRequest,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    user = await container.portal_auth.create_user(
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        password=payload.password,
    )
    await container.audit.record(
        action="portal_admin.user.create",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_user",
        target_id=user.id,
        detail={"username": user.username},
        ip=_client_ip(request),
    )
    return ok(
        PortalUserDTO(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
        ).model_dump()
    )


@router.get("/portal-admin/audit")
async def list_audit_log(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """按工作区读审计流水。**只读**——审计记录不可改、不可删。"""
    _assert_provision(container, actor)
    entries = await container.audit.list_recent(
        workspace_id=actor.workspace_id, limit=min(limit, 500), offset=offset
    )
    return list_response(
        [
            {
                "id": item.id,
                "actor_kind": item.actor_kind,
                "actor_id": item.actor_id,
                "action": item.action,
                "target_kind": item.target_kind,
                "target_id": item.target_id,
                "detail": dict(item.detail),
                "ip": item.ip,
                "created_at": item.created_at.isoformat(),
            }
            for item in entries
        ]
    )


@router.post("/portal-admin/users/{portal_user_id}/status")
async def set_portal_user_status(
    portal_user_id: str,
    payload: SetPortalUserStatusRequest,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """启用/禁用 portal 账号。**禁用会吊销该用户的全部会话**，旧 cookie 立刻失效。"""
    _assert_provision(container, actor)
    user = await container.portal_auth.set_user_status(portal_user_id, payload.status)
    await container.audit.record(
        action="portal_admin.user.status",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_user",
        target_id=portal_user_id,
        detail={"status": payload.status},
        ip=_client_ip(request),
    )
    return ok(
        PortalUserDTO(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            status=user.status,
        ).model_dump()
    )


@router.get("/portal-admin/users")
async def list_portal_users(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    users = await container.portal_auth.list_users()
    return list_response(
        [
            PortalUserDTO(
                id=item.id,
                username=item.username,
                display_name=item.display_name,
                email=item.email,
            ).model_dump()
            for item in users
        ]
    )


@router.post("/portal-admin/hubs")
async def create_portal_hub(
    payload: CreatePortalHubRequest,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    hub = await container.portal.create_hub(
        workspace_id=actor.workspace_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        created_by=actor.user_id,
    )
    await container.audit.record(
        action="portal_admin.hub.create",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_hub",
        target_id=hub.id,
        detail={"slug": hub.slug},
        ip=_client_ip(request),
    )
    return ok(
        PortalHubDTO(
            id=hub.id,
            slug=hub.slug,
            name=hub.name,
            description=hub.description,
        ).model_dump()
    )


@router.get("/portal-admin/hubs/{hub_id}/members")
async def list_hub_members(
    hub_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_hub(hub_id, actor.workspace_id)
    members = await container.portal.list_members(hub_id)
    return list_response(
        [
            {"id": item.id, "portal_user_id": item.portal_user_id, "role": item.role}
            for item in members
        ]
    )


@router.post("/portal-admin/hubs/{hub_id}/members")
async def add_hub_member(
    hub_id: str,
    payload: AddHubMemberRequest,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_hub(hub_id, actor.workspace_id)
    member = await container.portal.add_member(
        hub_id=hub_id,
        portal_user_id=payload.portal_user_id,
        role=payload.role,
    )
    await container.audit.record(
        action="portal_admin.member.add",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_hub",
        target_id=hub_id,
        detail={"portal_user_id": payload.portal_user_id, "role": payload.role},
        ip=_client_ip(request),
    )
    return ok(
        {"id": member.id, "portal_user_id": member.portal_user_id, "role": member.role}
    )


@router.delete("/portal-admin/hubs/{hub_id}/members/{member_id}")
async def remove_hub_member(
    hub_id: str,
    member_id: str,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_hub(hub_id, actor.workspace_id)
    await container.portal.remove_member(member_id)
    await container.audit.record(
        action="portal_admin.member.remove",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_hub",
        target_id=hub_id,
        detail={"member_id": member_id},
        ip=_client_ip(request),
    )
    return ok({"ok": True})


@router.post("/portal-admin/hubs/{hub_id}/agents")
async def attach_hub_agent(
    hub_id: str,
    payload: AttachHubAgentRequest,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_hub(hub_id, actor.workspace_id)
    hub_agent = await container.portal.attach_agent(
        hub_id=hub_id,
        workspace_id=actor.workspace_id,
        asset_id=payload.asset_id,
        display_name=payload.display_name,
    )
    await container.audit.record(
        action="portal_admin.agent.attach",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_hub",
        target_id=hub_id,
        detail={"asset_id": payload.asset_id, "portal_agent_id": hub_agent.id},
        ip=_client_ip(request),
    )
    return ok(
        {
            "id": hub_agent.id,
            "asset_id": hub_agent.asset_id,
            "display_name": hub_agent.display_name,
        }
    )


@router.post("/portal-admin/agents/{hub_agent_id}/channels/{channel}/bind")
async def bind_portal_channel(
    hub_agent_id: str,
    channel: Channel,
    payload: BindPortalChannelRequest,
    request: Request,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """把一把 `evl_` 部署密钥挂到门户 Agent 的某个通道上。

    密钥本身由 `POST /api/agents/{id}/deployment-keys` 签发——portal 只存引用。
    """
    _assert_provision(container, actor)
    credentials = await container.assets.list_credentials(actor.workspace_id)
    target = next((item for item in credentials if item.id == payload.deployment_credential_id), None)
    if target is None:
        raise NotFound("凭证", payload.deployment_credential_id)
    if target.channel is not None and target.channel is not channel:
        raise DomainError(
            Errors.CREDENTIAL_SCOPE_VIOLATION,
            f"该密钥只允许用于 {target.channel.value} 通道",
        )
    binding = await container.portal.bind_channel(
        hub_agent_id=hub_agent_id,
        channel=channel,
        deployment_credential_id=payload.deployment_credential_id,
    )
    await container.audit.record(
        action="portal_admin.channel.bind",
        actor_kind="platform_user",
        actor_id=actor.user_id,
        workspace_id=actor.workspace_id,
        target_kind="portal_agent",
        target_id=hub_agent_id,
        detail={
            "channel": channel.value,
            "deployment_credential_id": payload.deployment_credential_id,
        },
        ip=_client_ip(request),
    )
    return ok(
        {
            "id": binding.id,
            "hub_agent_id": binding.hub_agent_id,
            "channel": binding.channel.value,
            "deployment_credential_id": binding.deployment_credential_id,
        }
    )

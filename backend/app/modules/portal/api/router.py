"""portal 的 HTTP 路由。

两条面：
- `/portal/*`      —— 展示平台用户（portal cookie）。只读 + 对话。
- `/portal-admin/*` —— 平台运营者（平台 cookie + `PORTAL_PROVISION`）。供给账号/项目/成员/挂载。

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
from ..application.services import AgentView, PortalService, ProjectView, SHADOW_NOTICE
from .deps import (
    PortalActor,
    PortalActorDep,
    ProjectActorDep,
    clear_portal_cookie,
    get_portal_auth,
    get_portal_service,
    require_project,
    set_portal_cookie,
)
from .schemas import (
    AddProjectMemberRequest,
    AttachProjectAgentRequest,
    BindPortalChannelRequest,
    ChannelViewDTO,
    CreatePortalProjectRequest,
    CreatePortalUserRequest,
    PortalAgentDTO,
    PortalChatRequest,
    PortalLoginRequest,
    PortalProjectDTO,
    PortalSessionDTO,
    PortalUserDTO,
    SetPortalUserStatusRequest,
)

router = APIRouter(tags=["portal"])

#: 流式对话的心跳间隔。本地沙箱是「跑完才出结果」，心跳让中间代理不掐断连接。
KEEPALIVE_SECONDS = 15.0


def _project_dto(view: ProjectView) -> PortalProjectDTO:
    return PortalProjectDTO(
        id=view.project.id,
        slug=view.project.slug,
        name=view.project.name,
        description=view.project.description,
        my_role=view.role,
    )


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
                notice=item.notice,
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
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    issued = await container.portal_auth.login(payload.identifier, payload.password)
    if issued is None:
        raise DomainError(Errors.UNAUTHENTICATED, "用户名或密码不正确")
    set_portal_cookie(response, container, issued.token)
    projects = await container.portal.list_projects_for_user(issued.user.id)
    return ok(
        PortalSessionDTO(
            user=PortalUserDTO(
                id=issued.user.id,
                username=issued.user.username,
                display_name=issued.user.display_name,
                email=issued.user.email,
                status=issued.user.status,
            ),
            projects=[_project_dto(item) for item in projects],
        ).model_dump()
    )


@router.post("/portal/auth/logout")
async def portal_logout(
    request: Request,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    raw = request.cookies.get(container.settings.portal_cookie_name, "")
    await container.portal_auth.logout(raw)
    clear_portal_cookie(response, container)
    return ok({"ok": True})


@router.get("/portal/me")
async def portal_me(
    actor: PortalActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    projects = await portal.list_projects_for_user(actor.user.id)
    return ok(
        PortalSessionDTO(
            user=PortalUserDTO(
                id=actor.user.id,
                username=actor.user.username,
                display_name=actor.user.display_name,
                email=actor.user.email,
                status=actor.user.status,
            ),
            projects=[_project_dto(item) for item in projects],
        ).model_dump()
    )


@router.get("/portal/projects/{project_id}")
async def portal_project(
    actor: ProjectActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    assert actor.project is not None
    return ok(
        PortalProjectDTO(
            id=actor.project.id,
            slug=actor.project.slug,
            name=actor.project.name,
            description=actor.project.description,
            my_role=actor.role,
        ).model_dump()
    )


@router.get("/portal/projects/{project_id}/agents")
async def portal_agents(
    actor: ProjectActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    assert actor.project is not None
    views = await portal.list_project_agents(actor.project.id, actor.project.workspace_id)
    return list_response([_agent_dto(view).model_dump() for view in views])


@router.get("/portal/projects/{project_id}/agents/{project_agent_id}")
async def portal_agent(
    project_agent_id: str,
    actor: ProjectActorDep,
    portal: Annotated[PortalService, Depends(get_portal_service)],
) -> dict:
    assert actor.project is not None
    view = await portal.get_project_agent(
        project_agent_id, actor.project.id, actor.project.workspace_id
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


@router.post("/portal/projects/{project_id}/agents/{project_agent_id}/channels/{channel}/chat")
async def portal_chat(
    project_agent_id: str,
    channel: Channel,
    payload: PortalChatRequest,
    request: Request,
    actor: Annotated[PortalActor, Depends(require_project("agent:chat"))],
    portal: Annotated[PortalService, Depends(get_portal_service)],
    container: Annotated[Container, Depends(get_container)],
):
    assert actor.project is not None
    project = actor.project
    model = f"{project_agent_id}@{channel.value}"
    message = payload.resolved_message()
    if not message.strip():
        raise DomainError(Errors.VALIDATION_FAILED, "对话内容为空")

    if not payload.stream:
        result = await portal.chat(
            project_agent_id=project_agent_id,
            project_id=project.id,
            workspace_id=project.workspace_id,
            channel=channel,
            message=message,
            messages=payload.messages,
            timeout_seconds=payload.timeout_seconds,
        )
        return ok(
            {
                "id": f"chatcmpl-{project_agent_id}",
                "object": "chat.completion",
                "model": model,
                "channel": channel.value,
                "notice": SHADOW_NOTICE if channel is Channel.LIVESH else None,
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
        chunk_id = f"chatcmpl-{project_agent_id}"
        # 先发角色帧，让前端的空气泡立刻出现，不必等被测 Agent 跑完。
        yield _chunk(
            chunk_id=chunk_id,
            model=model,
            created=created,
            delta={"role": "assistant", "content": ""},
        )

        task = asyncio.create_task(
            portal.chat(
                project_agent_id=project_agent_id,
                project_id=project.id,
                workspace_id=project.workspace_id,
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
    if channel is Channel.LIVESH:
        # HTTP 头只能是 ASCII，所以这里放**机器可读的标记**；
        # 人话提示在 `channels[].notice` 与响应体里（见 SHADOW_NOTICE）。
        headers["X-Eval-Loom-Notice"] = "shadow-preview"
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
    return ok(
        PortalUserDTO(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
        ).model_dump()
    )


@router.post("/portal-admin/users/{portal_user_id}/status")
async def set_portal_user_status(
    portal_user_id: str,
    payload: SetPortalUserStatusRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """启用/禁用 portal 账号。**禁用会吊销该用户的全部会话**，旧 cookie 立刻失效。"""
    _assert_provision(container, actor)
    user = await container.portal_auth.set_user_status(portal_user_id, payload.status)
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


@router.post("/portal-admin/projects")
async def create_portal_project(
    payload: CreatePortalProjectRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    project = await container.portal.create_project(
        workspace_id=actor.workspace_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        created_by=actor.user_id,
    )
    return ok(
        PortalProjectDTO(
            id=project.id,
            slug=project.slug,
            name=project.name,
            description=project.description,
        ).model_dump()
    )


@router.get("/portal-admin/projects/{project_id}/members")
async def list_project_members(
    project_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_project(project_id, actor.workspace_id)
    members = await container.portal.list_members(project_id)
    return list_response(
        [
            {"id": item.id, "portal_user_id": item.portal_user_id, "role": item.role}
            for item in members
        ]
    )


@router.post("/portal-admin/projects/{project_id}/members")
async def add_project_member(
    project_id: str,
    payload: AddProjectMemberRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_project(project_id, actor.workspace_id)
    member = await container.portal.add_member(
        project_id=project_id,
        portal_user_id=payload.portal_user_id,
        role=payload.role,
    )
    return ok(
        {"id": member.id, "portal_user_id": member.portal_user_id, "role": member.role}
    )


@router.delete("/portal-admin/projects/{project_id}/members/{member_id}")
async def remove_project_member(
    project_id: str,
    member_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_project(project_id, actor.workspace_id)
    await container.portal.remove_member(member_id)
    return ok({"ok": True})


@router.post("/portal-admin/projects/{project_id}/agents")
async def attach_project_agent(
    project_id: str,
    payload: AttachProjectAgentRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    _assert_provision(container, actor)
    await container.portal.get_project(project_id, actor.workspace_id)
    project_agent = await container.portal.attach_agent(
        project_id=project_id,
        workspace_id=actor.workspace_id,
        asset_id=payload.asset_id,
        display_name=payload.display_name,
    )
    return ok(
        {
            "id": project_agent.id,
            "asset_id": project_agent.asset_id,
            "display_name": project_agent.display_name,
        }
    )


@router.post("/portal-admin/agents/{project_agent_id}/channels/{channel}/bind")
async def bind_portal_channel(
    project_agent_id: str,
    channel: Channel,
    payload: BindPortalChannelRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """把一把 `evl_` 部署密钥挂到项目 Agent 的某个通道上。

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
        project_agent_id=project_agent_id,
        channel=channel,
        deployment_credential_id=payload.deployment_credential_id,
    )
    return ok(
        {
            "id": binding.id,
            "project_agent_id": binding.project_agent_id,
            "channel": binding.channel.value,
            "deployment_credential_id": binding.deployment_credential_id,
        }
    )

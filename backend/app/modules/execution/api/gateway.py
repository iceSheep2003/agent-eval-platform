"""机器面路由：按通道调用已发布 Agent。

鉴权走 `evl_` Bearer，**不复用会话 Cookie**（架构文档 §5.1 的四条鉴权链）。
与 SDK 上报（`evk_`）严格分开：`evk_` 只能写 Trace，`evl_` 只能调用 Agent。

调用方**不能指定版本**，只能指定通道——版本由 `asset_channel_binding` 解析，
否则展示平台的「三通道切换」就成了装饰。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header

from ....api.deps import get_container
from ....container import Container
from ....contracts.common import Channel, CredentialKind
from ....contracts.errors import DomainError, Errors
from ....contracts.execution import ChannelInvocation
from ....schemas.response import ok
from .schemas import InvokeRequest

router = APIRouter(tags=["gateway"])

DEPLOY_KEY_PREFIX = "evl_"

#: 影子通道的回复必须让调用方一眼看出「这不是给真实用户的结果」。
SHADOW_NOTICE = "影子预览 · 未返回真实用户"


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise DomainError(Errors.UNAUTHENTICATED, "缺少 Bearer 密钥")
    return authorization[7:].strip()


@router.post("/agents/{agent_id}/invoke")
async def invoke_agent(
    agent_id: str,
    payload: InvokeRequest,
    container: Annotated[Container, Depends(get_container)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    raw_key = _bearer(authorization)
    if not raw_key.startswith(DEPLOY_KEY_PREFIX):
        raise DomainError(Errors.CREDENTIAL_SCOPE_VIOLATION, "该接口只接受 evl_ 部署密钥")

    credential = await container.assets.resolve_credential(raw_key)
    if credential is None:
        raise DomainError(Errors.CREDENTIAL_EXPIRED, "密钥无效或已吊销")
    if credential.kind is not CredentialKind.DEPLOY:
        raise DomainError(Errors.CREDENTIAL_SCOPE_VIOLATION, "该密钥不是部署密钥")
    if credential.asset_id != agent_id:
        raise DomainError(Errors.CREDENTIAL_SCOPE_VIOLATION, "该密钥不属于这个 Agent")

    channel = Channel(payload.channel)
    # 密钥限定通道时必须一致：拿 LIVE 的密钥打 TEST 是越权。
    if credential.channel is not None and credential.channel is not channel:
        raise DomainError(
            Errors.CREDENTIAL_SCOPE_VIOLATION,
            f"该密钥只允许调用 {credential.channel.value} 通道",
        )

    result = await container.invoke.invoke_channel(
        ChannelInvocation(
            workspace_id=credential.workspace_id,
            asset_id=agent_id,
            channel=channel,
            input=payload.input,
            messages=tuple(payload.messages),
            tenant_id=credential.tenant_id,
            timeout_seconds=payload.timeout_seconds,
            credential_id=credential.credential_id,
        )
    )
    return ok(
        {
            "agent_id": agent_id,
            "channel": channel.value,
            "version": result.version_label,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "trace_id": result.trace_id,
            "notice": SHADOW_NOTICE if channel is Channel.LIVESH else None,
        }
    )

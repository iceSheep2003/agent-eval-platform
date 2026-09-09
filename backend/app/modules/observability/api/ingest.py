"""机器面路由：SDK 事件上报与 Agent 上下文。

鉴权走 `evk_` Bearer，**不复用会话 Cookie**——SDK 密钥只允许写 Trace，
不能调用 Agent，也不能读控制台数据（架构文档 §5.1 的四条鉴权链）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from ....api.deps import get_container
from ....container import Container
from ....contracts.errors import DomainError, Errors
from ....schemas.response import ok

router = APIRouter(tags=["ingest"])

TRACE_KEY_PREFIX = "evk_"


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise DomainError(Errors.UNAUTHENTICATED, "缺少 Bearer 密钥")
    return authorization[7:].strip()


@router.post("/traces")
async def ingest_traces(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """NDJSON 批量写入。宽松接受：坏行只回执不整批报错，避免 Trace 无声丢失。"""
    raw_key = _bearer(authorization)
    if not raw_key.startswith(TRACE_KEY_PREFIX):
        raise DomainError(Errors.CREDENTIAL_SCOPE_VIOLATION, "该接口只接受 evk_ 接入密钥")

    service = container.traces
    credential = await service.resolve_credential(raw_key)
    body = await request.body()
    result = await service.ingest_ndjson(body, credential)
    return ok(
        {
            "accepted_traces": list(result.accepted_traces),
            "updated_traces": list(result.updated_traces),
            "rejected": [{"trace_id": key, "reason": reason} for key, reason in result.rejected],
            "dropped_events": result.dropped_events,
            "accepted_count": result.accepted_count,
        }
    )


@router.get("/agent-context")
async def agent_context(
    container: Annotated[Container, Depends(get_container)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """SDK 侧拉取知识库 / Skill / MCP 配置。

    P0 返回空集合——示例 Agent 的 `fetch_platform_context()` 拿到空值会静默降级，
    所以这个接口先存在比先完善更重要。
    """
    raw_key = _bearer(authorization)
    if not raw_key.startswith(TRACE_KEY_PREFIX):
        raise DomainError(Errors.CREDENTIAL_SCOPE_VIOLATION, "该接口只接受 evk_ 接入密钥")
    credential = await container.traces.resolve_credential(raw_key)
    return ok(
        {
            "agent_id": credential.asset_id,
            "tenant_id": credential.tenant_id,
            "knowledge": [],
            "skills": [],
            "mcp_servers": [],
        }
    )

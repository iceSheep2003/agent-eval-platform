"""asset 的 HTTP DTO。字段名对齐前端 `EvalAgent` / `AgentCredential`。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RegisterAgentRequest(BaseModel):
    """`POST /api/agents`。`register.py` 用的就是这个形状。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    connect_type: Literal["sdk", "github", "package"] = "sdk"
    environment: str | None = None
    #: 接入方式特有字段：github 的 repository/ref、package 的 artifact_id/entrypoint
    source: dict[str, Any] | None = None


class CreateVersionRequest(BaseModel):
    spec: dict = Field(default_factory=dict)
    version_label: str | None = Field(default=None, max_length=32)


class SdkKeyRequest(BaseModel):
    name: str = Field(default="default", max_length=128)
    expires_at: datetime | None = None


class AgentDTO(BaseModel):
    id: str
    name: str
    description: str
    owner: str
    connect_type: str | None
    status: str
    environment: str | None = None
    lifecycle: str
    version: str | None = None
    test_version: str | None = None
    livesh_version: str | None = None
    live_version: str | None = None
    credential_state: Literal["ready", "missing", "expiring"] = "missing"
    instance_count: int = 0
    binding_count: int = 0
    success_rate: float | None = None
    latency_ms: float | None = None
    run_count: int = 0


class AgentVersionDTO(BaseModel):
    id: str
    version: str
    status: str
    source_type: str | None = None
    source_uri: str | None = None
    created_at: datetime


class ChannelDTO(BaseModel):
    channel: str
    version_id: str | None
    version: str | None
    bound_at: datetime | None
    bound_by: str | None


class IssuedCredentialDTO(BaseModel):
    """注意：`key` 只在本响应里出现一次，之后任何接口都不会再返回。"""

    id: str
    key: str
    ingest_url: str
    prefix: str
    last_four: str
    agent_id: str | None
    tenant_id: str | None
    name: str
    created_at: datetime


class CredentialDTO(BaseModel):
    id: str
    name: str
    prefix: str
    last_four: str
    kind: str
    agent_id: str | None
    tenant_id: str | None
    status: str
    environment: str | None = None
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime

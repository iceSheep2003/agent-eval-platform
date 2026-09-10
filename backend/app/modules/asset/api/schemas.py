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
    #: 负责人：必须是本工作区成员。留空则默认当前登录用户。
    owner_id: str | None = None
    #: 接入方式特有字段：github 的 repository/ref、package 的 artifact_id/entrypoint
    source: dict[str, Any] | None = None


class CreateCredentialRequest(BaseModel):
    """`POST /api/agent-credentials`。`kind` 决定前缀：evk_ / evl_ / evs_。"""

    name: str = Field(default="default", max_length=128)
    kind: Literal["evk", "evl", "evs"] = "evk"
    agent_id: str | None = None
    channel: Literal["test", "livesh", "live"] | None = None
    scopes: list[str] = Field(default_factory=list)
    environment: str | None = None
    expires_at: datetime | None = None


class CreateVersionRequest(BaseModel):
    spec: dict = Field(default_factory=dict)
    version_label: str | None = Field(default=None, max_length=32)


class PromoteCapabilityRequest(BaseModel):
    channel: Literal["test", "livesh", "live"]
    evidence_ids: list[str] = Field(default_factory=list)


class RollbackCapabilityRequest(BaseModel):
    channel: Literal["test", "livesh", "live"]
    target_version_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=512)


class SdkKeyRequest(BaseModel):
    name: str = Field(default="default", max_length=128)
    expires_at: datetime | None = None


class BindChannelRequest(BaseModel):
    """`POST /api/agents/{id}/channels/{channel}/bind`。"""

    version_id: str = Field(min_length=1, max_length=64)


class DeploymentKeyRequest(BaseModel):
    """`POST /api/agents/{id}/deployment-keys`：签发一把**限定通道**的 `evl_` 密钥。"""

    channel: Literal["test", "livesh", "live"]
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


class DeploymentKeyDTO(BaseModel):
    """部署密钥。`key` 只在本响应里出现一次。"""

    id: str
    key: str
    prefix: str
    last_four: str
    agent_id: str
    channel: str
    invoke_url: str
    name: str
    expires_at: datetime | None
    created_at: datetime

# --------------------------------------------------------------------------- #
# 能力资产（Skill / MCP / 知识库）
# --------------------------------------------------------------------------- #

#: 对外只暴露规范值。前端历史值 `knowledge` 在请求里作为别名接受，出口一律 `knowledge_base`。
CapabilityKind = Literal["skill", "mcp", "knowledge_base"]


class RegisterCapabilityRequest(BaseModel):
    """`POST /api/assets`。`spec` 由对应 kind 的校验器校验，失败返回 422 + 字段路径。"""

    kind: Literal["skill", "mcp", "knowledge_base", "knowledge"]
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    spec: dict[str, Any] = Field(default_factory=dict)
    #: 知识库常按租户隔离；填了就是 tenant_bound。
    tenant_id: str | None = None


class CapabilityChannelDTO(BaseModel):
    """通道**指针**。版本详情走 `CapabilityVersionDTO`，两者不要混。"""

    channel: str
    version_id: str | None
    version_label: str | None
    bound_at: datetime | None
    bound_by: str | None


class CapabilityVersionDTO(BaseModel):
    id: str
    version_label: str
    lifecycle: str
    spec: dict[str, Any]
    created_by: str
    created_at: datetime


class CapabilityAssetDTO(BaseModel):
    id: str
    kind: str
    name: str
    description: str
    owner: str
    lifecycle: str
    tenant_scope: str
    tenant_id: str | None = None
    version_count: int = 0
    binding_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None
    latest_version: CapabilityVersionDTO | None = None
    channels: list[CapabilityChannelDTO] = Field(default_factory=list)


class CreateBindingRequest(BaseModel):
    provider_asset_id: str
    resolve_mode: Literal["channel", "pinned"] = "channel"
    #: resolve_mode=channel 时有效，缺省 live。
    provider_channel: Literal["test", "livesh", "live"] | None = None
    #: resolve_mode=pinned 时必填。
    provider_version_id: str | None = None
    #: 空 = 该 Agent 的所有版本共用这条引用。
    consumer_version_id: str | None = None
    tenant_scope: str = "workspace_shared"


class CapabilityBindingDTO(BaseModel):
    id: str
    consumer_asset_id: str
    consumer_asset_name: str | None = None
    consumer_version_id: str | None = None
    provider_asset_id: str
    provider_kind: str
    resolve_mode: str
    provider_channel: str | None = None
    provider_version_id: str | None = None
    resolved_version_id: str | None = None
    resolved_version_label: str | None = None
    tenant_scope: str
    created_at: datetime


class CredentialDTO(BaseModel):
    id: str
    name: str
    prefix: str
    last_four: str
    kind: str
    agent_id: str | None
    tenant_id: str | None
    #: 凭证限定的通道（部署凭证才有）；SDK 上报密钥为 None
    channel: str | None = None
    #: 前端凭证表用 `scopes` / `environment` / `agent_ids` 表达「能干什么、属于哪个环境、被谁用」
    scopes: list[str] = []
    agent_ids: list[str] = []
    environment: str | None = None
    status: str
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class PutSecretRequest(BaseModel):
    """存一把资源密钥。**同名可以有多把**——轮换就是再存一把，旧的不动。"""

    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4096)
    description: str = Field(default="", max_length=512)


class SecretDTO(BaseModel):
    """**不含明文**：只给指纹，用于确认「用的是哪一把」。"""

    id: str
    name: str
    fingerprint: str
    description: str
    created_at: datetime


class BindSecretRequest(BaseModel):
    resource_secret_id: str = Field(min_length=1, max_length=64)
    secret_name: str = Field(min_length=1, max_length=128)
    #: 绑到**工作区默认**（对该工作区所有 Agent 生效）而不是某个具体版本。
    workspace_default: bool = False


class SecretBindingDTO(BaseModel):
    id: str
    #: `*` 表示工作区默认——对该工作区所有 Agent 生效。
    asset_version_id: str
    channel: str
    secret_name: str
    resource_secret_id: str
    #: 该密钥当前绑的是哪一把（指纹），便于界面显示「实际生效的是哪个」。
    fingerprint: str | None = None
    bound_at: datetime


class ModelConfigRequest(BaseModel):
    """工作区**默认模型配置**。三项都可不填——不填的那项就不注入。

    这是 Agent 的兜底：单个 Agent 想在 spec 里声明同名密钥即可覆盖。
    """

    base_url: str | None = Field(default=None, max_length=512)
    auth_token: str | None = Field(default=None, max_length=4096)
    model_name: str | None = Field(default=None, max_length=128)

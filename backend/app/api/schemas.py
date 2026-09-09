from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    identifier: str
    password: str


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    owner: str | None = None
    connect_type: Literal["http", "mcp", "cli", "package", "python", "git", "sdk"]
    environment: Literal["sandbox", "staging", "production"] = "sandbox"


class AgentStatusBody(BaseModel):
    status: Literal["active", "paused", "disabled"]


class CredentialCreate(BaseModel):
    agent_id: str | None = None
    agent_ids: list[str] = Field(default_factory=list)
    provider: str
    name: str
    value: str = Field(min_length=1)


class CredentialBindingBody(BaseModel):
    agent_ids: list[str] = Field(default_factory=list)


class InstanceCreate(BaseModel):
    agent_version_id: str


class DeploymentTokenCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)


class SdkKeyCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)


class RunCreate(BaseModel):
    name: str = "New evaluation run"
    agent_version_id: str
    template_id: str
    limits: dict[str, Any] = Field(default_factory=dict)


class PolicyCreate(BaseModel):
    name: str
    dataset_id: str
    lifecycle: str = "regression"
    evaluators: list[str] = Field(default_factory=lambda: ["deterministic_match"])
    trigger_type: str = "manual"
    gates: dict[str, Any] = Field(default_factory=dict)
    max_steps: int = 50
    max_cost_usd: float = 10


class EnabledBody(BaseModel):
    enabled: bool


class BenchmarkAdapterCreate(BaseModel):
    name: str
    version: str = "1.0.0"
    protocol: str = "http"
    endpoint: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AgentConfigChange(BaseModel):
    endpoint: str
    environment: Literal["sandbox", "staging", "production"]
    owner: str


class BindingCreate(BaseModel):
    policy_id: str
    agent_version_id: str | None = None
    schedule: str = "manual"
    failure_threshold: float = 0.8
    auto_regression: bool = True
    notify_owner: bool = True


class ReleaseCreate(BaseModel):
    version: str
    channel: Literal["candidate", "stable", "canary"] = "candidate"
    changelog: str = ""


class RollbackCreate(BaseModel):
    target_version_id: str


class WorkspaceSettingsUpdate(BaseModel):
    refresh_interval_seconds: int = Field(default=30, ge=5, le=3600)
    trace_retention_days: int = Field(default=30, ge=1, le=3650)
    confirm_destructive: bool = True


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    agent_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    prompt: str = Field(min_length=1)
    agent_id: str | None = None


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    transport: str = "streamable-http"
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    agent_id: str | None = None

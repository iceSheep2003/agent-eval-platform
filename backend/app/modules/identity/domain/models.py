"""identity 领域实体。

纯 Python，零框架依赖：不 import fastapi / sqlalchemy / httpx。
仓储负责在「实体」与「ORM 行」之间转换。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from ....contracts.common import Id, OrgRole, WorkspaceRole

UserStatus = Literal["active", "disabled"]
AuthMethod = Literal["password", "oidc"]
TenantScope = Literal["all"] | tuple[Id, ...]


@dataclass(frozen=True, slots=True)
class User:
    id: Id
    username: str
    display_name: str
    email: str | None
    password_hash: str | None  # 纯 OIDC 用户为 None
    status: UserStatus
    created_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def can_login_with_password(self) -> bool:
        return self.is_active and self.password_hash is not None


@dataclass(frozen=True, slots=True)
class Organization:
    """组织：平台最上层单位（对齐 Langfuse）。

    管成员、计费、建/删项目；**不直接持有评测资产**。
    """

    id: Id
    slug: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OrganizationMembership:
    """组织级角色。只管组织层的事，不参与工作区内权限判定。"""

    organization_id: Id
    user_id: Id
    role: OrgRole
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Workspace:
    """项目：评测资产的隔离单位（对齐 Langfuse 的 Project）。"""

    id: Id
    organization_id: Id
    slug: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Tenant:
    """Agent 运行时的业务分区。M1 只自动建「默认租户」，完整租户管理到 M4。"""

    id: Id
    workspace_id: Id
    external_key: str  # 幂等键，调用侧定义
    name: str
    status: Literal["active", "suspended", "purged"]
    created_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True, slots=True)
class Membership:
    workspace_id: Id
    user_id: Id
    role: WorkspaceRole
    tenant_scope: TenantScope
    created_at: datetime

    def covers_tenant(self, tenant_id: Id) -> bool:
        if self.tenant_scope == "all":
            return True
        return tenant_id in self.tenant_scope


@dataclass(frozen=True, slots=True)
class Session:
    """服务端会话。Cookie 里只有明文 token，库里只存哈希。"""

    id: Id
    user_id: Id
    token_hash: str
    auth_method: AuthMethod
    provider_id: Id | None
    created_at: datetime
    expires_at: datetime  # 绝对上限
    last_seen_at: datetime
    user_agent: str | None = None
    ip: str | None = None

    def is_expired(self, now: datetime, idle_limit: timedelta) -> bool:
        if now >= self.expires_at:
            return True
        return now - self.last_seen_at >= idle_limit

    def is_idle(self, now: datetime, idle_limit: timedelta) -> bool:
        return now - self.last_seen_at >= idle_limit

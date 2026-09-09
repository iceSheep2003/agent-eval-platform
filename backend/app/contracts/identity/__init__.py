"""身份与鉴权契约。

定义方：identity（它没有上游）。消费方：所有模块。
`AuthorizerPort` 是全平台唯一的权限判定入口——任何模块都不得自行判断角色。

**当前只发布 M0 真正被消费的项**（实施计划 §二 G2/G3）。
`TenantRef` / `TenantQueryPort` / `MembershipQueryPort` / `SessionRevokePort` 等
在 M1（observability 需要租户校验）与 M2（execution 需要成员查询）出现消费方时再加。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from ..common import Id, WorkspaceRole

# --------------------------------------------------------------------------- #
# 权限点
# --------------------------------------------------------------------------- #


class Permission(StrEnum):
    """权限点常量。命名 `<resource>:<action>`，与架构文档 §5.2 矩阵一一对应。"""

    # workspace / member
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_SETTINGS_WRITE = "workspace:settings:write"
    MEMBER_INVITE = "member:invite"
    MEMBER_ROLE_WRITE = "member:role:write"
    MEMBER_REMOVE = "member:remove"

    # asset
    ASSET_READ = "asset:read"
    ASSET_CREATE = "asset:create"
    ASSET_UPDATE = "asset:update"
    ASSET_ARCHIVE = "asset:archive"
    ASSET_VERSION_CREATE = "asset:version:create"
    ASSET_CREDENTIAL_CREATE = "asset:credential:create"
    ASSET_CREDENTIAL_REVOKE = "asset:credential:revoke"

    # dataset
    DATASET_READ = "dataset:read"
    DATASET_CREATE = "dataset:create"
    DATASET_IMPORT = "dataset:import"
    DATASET_VERSION_FINALIZE = "dataset:version:finalize"
    DATASET_EXPORT = "dataset:export"

    # evaluation
    TEMPLATE_READ = "template:read"
    TEMPLATE_CREATE = "template:create"
    TEMPLATE_UPDATE = "template:update"
    TEMPLATE_DISABLE = "template:disable"
    TEMPLATE_BIND = "template:bind"
    GATE_CONFIGURE = "gate:configure"

    # execution
    RUN_READ = "run:read"
    RUN_CREATE = "run:create"
    RUN_CONTROL = "run:control"

    # observability
    TRACE_READ = "trace:read"
    TRACE_READ_RAW = "trace:read_raw"
    METRICS_READ = "metrics:read"

    # improvement
    PROPOSAL_READ = "proposal:read"
    PROPOSAL_SUBMIT = "proposal:submit"
    PROPOSAL_REVIEW = "proposal:review"

    # delivery
    VERSION_PROMOTE_LIVESH = "version:promote:livesh"
    VERSION_PROMOTE_LIVE = "version:promote:live"
    VERSION_ROLLBACK = "version:rollback"
    SHADOW_CONFIGURE = "shadow:configure"

    # portal（展示平台：运营侧供给项目/成员/挂载，展示平台自身只读+对话）
    PORTAL_PROVISION = "portal:provision"

    # tenant
    TENANT_EXPORT = "tenant:export"
    TENANT_PURGE = "tenant:purge"
    TENANT_SYNC = "tenant:sync"  # 仅机器凭证 evs_ 持有，任何用户角色都不具备


# --------------------------------------------------------------------------- #
# 主体与资源
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Subject:
    """鉴权主体。用户会话与机器凭证统一成这个形状，`Authorizer` 只认它。"""

    kind: Literal["user", "credential"]
    id: str
    workspace_id: Id
    role: WorkspaceRole | None = None
    tenant_scope: Literal["all"] | tuple[Id, ...] = "all"
    credential_kind: Literal["evl", "evk", "evs"] | None = None

    def covers_tenant(self, tenant_id: Id) -> bool:
        if self.tenant_scope == "all":
            return True
        return tenant_id in self.tenant_scope


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """被操作的资源。`owner_id` 用于资源级放权，`tenant_id` 用于第二道边界。"""

    kind: str
    id: Id
    workspace_id: Id
    tenant_id: Id | None = None
    owner_id: Id | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str | None = None
    requires_reauth: bool = False
    denied_by: Literal[
        "workspace", "tenant_scope", "role", "ownership", "auto_subject", "credential"
    ] | None = None

    @classmethod
    def allow(cls, requires_reauth: bool = False) -> "Decision":
        return cls(allowed=True, requires_reauth=requires_reauth)

    @classmethod
    def deny(cls, reason: str, denied_by: str | None = None) -> "Decision":
        return cls(allowed=False, reason=reason, denied_by=denied_by)  # type: ignore[arg-type]


@runtime_checkable
class AuthorizerPort(Protocol):
    """全平台唯一的权限判定入口。纯函数，无 IO，便于单测穷举权限矩阵。"""

    def decide(
        self,
        subject: Subject,
        action: Permission,
        resource: ResourceRef | None = None,
    ) -> Decision: ...


@dataclass(frozen=True, slots=True)
class ActorContext:
    """一次已认证请求的上下文。

    这是**跨模块**的：每个模块的路由都需要「谁、在哪个工作区、什么角色」，
    所以它属于契约层，而不是 identity 的应用层类型。
    """

    user_id: Id
    display_name: str
    email: str | None
    workspace_id: Id
    workspace_name: str
    role: WorkspaceRole | None
    subject: Subject

    @property
    def tenant_scope(self) -> Literal["all"] | tuple[Id, ...]:
        return self.subject.tenant_scope


@runtime_checkable
class AuthContextPort(Protocol):
    """由 identity 实现；`app/api/deps.py` 用它把 Cookie 换成 `ActorContext`。"""

    async def resolve(self, raw_token: str, workspace_ref: str | None) -> ActorContext | None: ...


@runtime_checkable
class TenantProvisioningPort(Protocol):
    """由 identity 实现；asset 签发 SDK 密钥时按需取用租户。

    只返回租户 ID——消费方不需要租户的其他字段，少一个 DTO 就少一处耦合。
    """

    async def ensure_tenant(self, workspace_id: Id, external_key: str, name: str) -> Id: ...


__all__ = [
    "ActorContext",
    "AuthorizerPort",
    "AuthContextPort",
    "Decision",
    "Permission",
    "ResourceRef",
    "Subject",
    "TenantProvisioningPort",
]

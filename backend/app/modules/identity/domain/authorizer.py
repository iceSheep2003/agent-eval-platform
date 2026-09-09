"""权限判定。

**纯函数**：无 IO、无时间依赖、无全局状态。全平台唯一的鉴权入口——
任何模块都不得自行判断角色，否则权限模型会散落成几十处 if。

判定顺序（架构文档 §5.4）：机器凭证约束 → 工作区隔离 → 租户范围 → 角色 → 资源归属 → 再认证。
"""

from __future__ import annotations

from ....contracts.identity import AuthorizerPort, Decision, Permission, ResourceRef, Subject
from .permission import (
    MACHINE_FORBIDDEN,
    OWNER_SCOPED,
    REAUTH_REQUIRED,
    ROLE_PERMISSIONS,
    UNRESTRICTED_ROLES,
)


class Authorizer(AuthorizerPort):
    """`contracts.identity.AuthorizerPort` 的实现。"""

    def decide(
        self,
        subject: Subject,
        action: Permission,
        resource: ResourceRef | None = None,
    ) -> Decision:
        if subject.kind == "credential":
            return self._decide_for_credential(subject, action, resource)

        if resource is not None and resource.workspace_id != subject.workspace_id:
            return Decision.deny("资源不属于当前工作区", "workspace")

        if (
            resource is not None
            and resource.tenant_id is not None
            and not subject.covers_tenant(resource.tenant_id)
        ):
            return Decision.deny(f"租户 {resource.tenant_id} 不在你的可见范围内", "tenant_scope")

        if subject.role is None:
            return Decision.deny("主体没有工作区角色", "role")

        if action not in ROLE_PERMISSIONS.get(subject.role, frozenset()):
            return Decision.deny(f"角色 {subject.role} 缺少 {action} 权限", "role")

        if action in OWNER_SCOPED and subject.role not in UNRESTRICTED_ROLES:
            if resource is None or resource.owner_id != subject.id:
                return Decision.deny(f"{action} 只对本人负责的资源生效", "ownership")

        return Decision.allow(requires_reauth=action in REAUTH_REQUIRED)

    def _decide_for_credential(
        self,
        subject: Subject,
        action: Permission,
        resource: ResourceRef | None,
    ) -> Decision:
        # 机器凭证永远不能审查提案或推进版本——这是需求 §9.13 的代码级保证。
        if action in MACHINE_FORBIDDEN:
            return Decision.deny(
                "机器凭证不能执行审查、晋级或发布类操作", "auto_subject"
            )

        # M0 只有租户同步一种机器权限；evl_ / evk_ 的鉴权在各自端点内完成。
        if action is not Permission.TENANT_SYNC or subject.credential_kind != "evs":
            return Decision.deny(f"凭证类型 {subject.credential_kind} 不允许 {action}", "credential")

        if resource is not None and resource.workspace_id != subject.workspace_id:
            return Decision.deny("资源不属于该凭证的工作区", "workspace")

        return Decision.allow()

    # -- 便捷方法，供用例内部使用 -------------------------------------------------

    def allowed(
        self,
        subject: Subject,
        action: Permission,
        resource: ResourceRef | None = None,
    ) -> bool:
        return self.decide(subject, action, resource).allowed

    def permissions_of(self, subject: Subject) -> frozenset[Permission]:
        """该主体在当前工作区的全部权限点（前端据此隐藏按钮）。"""
        if subject.kind == "credential":
            return frozenset({Permission.TENANT_SYNC}) if subject.credential_kind == "evs" else frozenset()
        if subject.role is None:
            return frozenset()
        return ROLE_PERMISSIONS.get(subject.role, frozenset())

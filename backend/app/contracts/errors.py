"""跨模块错误码表。

每条错误码带稳定的 `code`（前端据此做文案与分支）和 HTTP 状态。
**不要在业务代码里裸抛 HTTPException**——抛 `DomainError`，由 API 层统一映射。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ErrorCode:
    code: str
    http_status: int
    message: str


class Errors:
    """全部错误码。命名分组，便于按域检索。"""

    # ---- 通用 ----
    NOT_FOUND = ErrorCode("not_found", 404, "资源不存在")
    VALIDATION_FAILED = ErrorCode("validation_failed", 422, "参数校验失败")
    IDEMPOTENCY_CONFLICT = ErrorCode("idempotency_conflict", 409, "幂等键冲突且内容不一致")
    CONTRACT_VERSION_MISMATCH = ErrorCode("contract_version_mismatch", 500, "契约版本不匹配")
    RATE_LIMITED = ErrorCode("rate_limited", 429, "请求过于频繁")

    # ---- 隔离 ----
    WORKSPACE_MISMATCH = ErrorCode("workspace_mismatch", 403, "资源不属于当前工作区")
    TENANT_OUT_OF_SCOPE = ErrorCode("tenant_out_of_scope", 403, "租户不在你的可见范围内")
    TENANT_UNKNOWN = ErrorCode("tenant_unknown", 422, "租户未登记")
    TENANT_SUSPENDED = ErrorCode("tenant_suspended", 422, "租户已停用")

    # ---- 鉴权 ----
    UNAUTHENTICATED = ErrorCode("unauthenticated", 401, "未登录或会话已过期")
    PERMISSION_DENIED = ErrorCode("permission_denied", 403, "没有该操作的权限")
    REAUTH_REQUIRED = ErrorCode("reauth_required", 401, "该操作需要重新认证")
    CSRF_TOKEN_INVALID = ErrorCode("csrf_token_invalid", 403, "CSRF 校验失败")

    # ---- 资产与版本 ----
    VERSION_IMMUTABLE = ErrorCode("version_immutable", 409, "已固化的版本不可修改")
    VERSION_DIGEST_CONFLICT = ErrorCode("version_digest_conflict", 409, "相同内容的版本已存在")
    CHANNEL_CONFLICT = ErrorCode("channel_conflict", 409, "该通道已绑定其他版本")
    CHANNEL_UNBOUND = ErrorCode("channel_unbound", 409, "该通道尚未绑定版本，无法调用")
    PROMOTION_ORDER_VIOLATION = ErrorCode("promotion_order_violation", 409, "版本只能按 TEST→LIVESH→LIVE 晋级")
    GATE_BLOCKED = ErrorCode("gate_blocked", 409, "质量门禁未通过，禁止晋级")
    CREDENTIAL_SCOPE_VIOLATION = ErrorCode("credential_scope_violation", 403, "凭证不允许该操作")
    CREDENTIAL_EXPIRED = ErrorCode("credential_expired", 401, "凭证已过期或已吊销")

    # ---- 数据集 ----
    DATASET_VERSION_IMMUTABLE = ErrorCode("dataset_version_immutable", 409, "数据集版本已固化")
    IMPORT_VALIDATION_FAILED = ErrorCode("import_validation_failed", 422, "导入预检未通过")
    SAMPLE_NOT_FOUND = ErrorCode("sample_not_found", 404, "样本不存在")

    # ---- 运行 ----
    RUN_FINALIZED = ErrorCode("run_finalized", 409, "运行已结束，结果不可修改")
    RUN_STATE_CONFLICT = ErrorCode("run_state_conflict", 409, "当前状态下不允许该操作")
    RUN_SUBJECT_INCOMPLETE = ErrorCode("run_subject_incomplete", 422, "被测对象缺少明确版本")

    # ---- 上报 ----
    INGEST_TENANT_MISMATCH = ErrorCode("ingest_tenant_mismatch", 422, "事件租户与密钥绑定租户不一致")
    INGEST_BATCH_TOO_LARGE = ErrorCode("ingest_batch_too_large", 413, "单批超过 1000 事件 / 5 MiB")
    INGEST_MALFORMED_EVENT = ErrorCode("ingest_malformed_event", 400, "事件格式非法")

    # ---- 模板与门禁 ----
    TEMPLATE_DISABLED = ErrorCode("template_disabled", 409, "策略已停用，不参与门禁判定")
    EVALUATOR_UNKNOWN = ErrorCode("evaluator_unknown", 422, "评估器未注册")


class DomainError(Exception):
    """业务错误基类。携带稳定的 ErrorCode，由 API 层映射为响应。"""

    __slots__ = ("error", "detail", "context")

    def __init__(
        self,
        error: ErrorCode,
        detail: str | None = None,
        **context: object,
    ) -> None:
        self.error = error
        self.detail = detail
        self.context: Mapping[str, object] = context
        super().__init__(detail or error.message)

    @property
    def code(self) -> str:
        return self.error.code

    @property
    def http_status(self) -> int:
        return self.error.http_status

    def __str__(self) -> str:
        base = self.error.message
        return f"{base}：{self.detail}" if self.detail else base


class NotFound(DomainError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(Errors.NOT_FOUND, f"{resource} {resource_id} 不存在", resource=resource)


class PermissionDenied(DomainError):
    def __init__(self, action: str, reason: str | None = None) -> None:
        super().__init__(Errors.PERMISSION_DENIED, reason or f"缺少 {action} 权限", action=action)


class WorkspaceMismatch(DomainError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            Errors.WORKSPACE_MISMATCH, f"{resource} {resource_id} 不属于当前工作区"
        )


class TenantOutOfScope(DomainError):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(Errors.TENANT_OUT_OF_SCOPE, f"租户 {tenant_id} 不在你的可见范围内")


class GateBlocked(DomainError):
    def __init__(self, blocked_rules: tuple[str, ...]) -> None:
        rules = "、".join(blocked_rules) if blocked_rules else "未知"
        super().__init__(Errors.GATE_BLOCKED, f"未通过的门禁：{rules}", blocked_rules=blocked_rules)


class VersionImmutable(DomainError):
    def __init__(self, version_id: str) -> None:
        super().__init__(Errors.VERSION_IMMUTABLE, f"版本 {version_id} 已固化")


class RunFinalized(DomainError):
    def __init__(self, run_id: str) -> None:
        super().__init__(Errors.RUN_FINALIZED, f"运行 {run_id} 已结束")

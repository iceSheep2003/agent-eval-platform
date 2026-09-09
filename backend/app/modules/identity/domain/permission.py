"""角色 → 权限点矩阵（纯数据）。

与架构文档 §5.2 的表格一一对应。改这张表等于改产品权限模型，
必须同时更新文档与 `tests/unit/identity/domain/test_authorizer.py`。
"""

from __future__ import annotations

from typing import Mapping

from ....contracts.common import WorkspaceRole
from ....contracts.identity import Permission as P

_R = frozenset

#: 只读权限：所有角色都有。
_READONLY = _R(
    {
        P.WORKSPACE_READ,
        P.ASSET_READ,
        P.DATASET_READ,
        P.TEMPLATE_READ,
        P.RUN_READ,
        P.TRACE_READ,
        P.METRICS_READ,
        P.PROPOSAL_READ,
    }
)

#: 开发者的日常写入：接入 Agent、建版本、发起运行、提提案。
_DEVELOPER = _READONLY | _R(
    {
        P.ASSET_CREATE,
        P.ASSET_UPDATE,
        P.ASSET_VERSION_CREATE,
        P.ASSET_CREDENTIAL_CREATE,
        P.ASSET_CREDENTIAL_REVOKE,
        P.ASSET_BIND,
        P.RUN_CREATE,
        P.RUN_CONTROL,
        P.PROPOSAL_SUBMIT,
    }
)

#: 评测负责人：数据集、策略、门禁、评审。
_EVALUATOR = _READONLY | _R(
    {
        P.DATASET_CREATE,
        P.DATASET_IMPORT,
        P.DATASET_VERSION_FINALIZE,
        P.DATASET_EXPORT,
        P.TEMPLATE_CREATE,
        P.TEMPLATE_UPDATE,
        P.TEMPLATE_DISABLE,
        P.TEMPLATE_BIND,
        P.GATE_CONFIGURE,
        P.RUN_CREATE,
        P.RUN_CONTROL,
        P.PROPOSAL_SUBMIT,
        P.PROPOSAL_REVIEW,
        P.VERSION_PROMOTE_LIVESH,
    }
)

#: 管理员：除「发布到生产」与「回退」以外的全部。
_ADMIN = _DEVELOPER | _EVALUATOR | _R(
    {
        P.WORKSPACE_SETTINGS_WRITE,
        P.MEMBER_INVITE,
        P.MEMBER_ROLE_WRITE,
        P.MEMBER_REMOVE,
        P.ASSET_ARCHIVE,
        P.SHADOW_CONFIGURE,
        P.TRACE_READ_RAW,
    }
)

#: 所有者：再加生产发布、回退、租户数据处置。
_OWNER = _ADMIN | _R(
    {
        P.VERSION_PROMOTE_LIVE,
        P.VERSION_ROLLBACK,
        P.TENANT_EXPORT,
        P.TENANT_PURGE,
    }
)

ROLE_PERMISSIONS: Mapping[WorkspaceRole, frozenset[P]] = {
    WorkspaceRole.OWNER: _OWNER,
    WorkspaceRole.ADMIN: _ADMIN,
    WorkspaceRole.EVALUATOR: _EVALUATOR,
    WorkspaceRole.DEVELOPER: _DEVELOPER,
    WorkspaceRole.VIEWER: _READONLY,
}

#: 这些权限即便角色有，也**只对自己负责的资源**生效（`resource.owner_id == subject.id`）。
#: owner / admin 不受此限制。
OWNER_SCOPED: frozenset[P] = _R(
    {
        P.ASSET_VERSION_CREATE,
        P.ASSET_CREDENTIAL_CREATE,
        P.ASSET_CREDENTIAL_REVOKE,
        P.ASSET_BIND,
        P.RUN_CONTROL,
    }
)

#: owner / admin 对 OWNER_SCOPED 权限不做资源归属检查。
UNRESTRICTED_ROLES: frozenset[WorkspaceRole] = _R(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}
)

#: 机器凭证（evl_ / evk_ / evs_）**永远**不能执行的动作。
#: 这是「自动生成的改进不能直接修改生产版本」的代码级保证。
MACHINE_FORBIDDEN: frozenset[P] = _R(
    {
        P.PROPOSAL_REVIEW,
        P.VERSION_PROMOTE_LIVESH,
        P.VERSION_PROMOTE_LIVE,
        P.VERSION_ROLLBACK,
        P.GATE_CONFIGURE,
        P.TEMPLATE_BIND,
        P.MEMBER_INVITE,
        P.MEMBER_ROLE_WRITE,
        P.MEMBER_REMOVE,
        P.WORKSPACE_SETTINGS_WRITE,
        P.TENANT_EXPORT,
        P.TENANT_PURGE,
    }
)

#: 需要二次认证（re-auth ticket）的动作。P1 落地。
REAUTH_REQUIRED: frozenset[P] = _R({P.VERSION_PROMOTE_LIVE, P.VERSION_ROLLBACK})

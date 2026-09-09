"""权限矩阵与硬约束的逐格验证。

这张表就是产品权限模型的可执行规格——改权限必须同时改这里。
"""

from __future__ import annotations

import pytest

from backend.app.contracts.common import WorkspaceRole
from backend.app.contracts.identity import Permission as P, ResourceRef, Subject
from backend.app.modules.identity.domain.authorizer import Authorizer
from backend.app.modules.identity.domain.permission import ROLE_PERMISSIONS

WS = "ws_test"
OTHER_WS = "ws_other"
ME = "usr_me"
OTHER = "usr_other"
TENANT = "tn_a"
OTHER_TENANT = "tn_b"


@pytest.fixture()
def authorizer() -> Authorizer:
    return Authorizer()


def subject(
    role: WorkspaceRole | None = WorkspaceRole.DEVELOPER,
    *,
    kind: str = "user",
    workspace_id: str = WS,
    tenant_scope="all",
    credential_kind: str | None = None,
) -> Subject:
    return Subject(
        kind=kind,  # type: ignore[arg-type]
        id=ME,
        workspace_id=workspace_id,
        role=role,
        tenant_scope=tenant_scope,
        credential_kind=credential_kind,  # type: ignore[arg-type]
    )


def resource(
    *,
    workspace_id: str = WS,
    tenant_id: str | None = None,
    owner_id: str | None = ME,
) -> ResourceRef:
    return ResourceRef(
        kind="asset", id="ast_1", workspace_id=workspace_id, tenant_id=tenant_id, owner_id=owner_id
    )


# --------------------------------------------------------------------------- #
# 角色矩阵
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "role,permission,expected",
    [
        (WorkspaceRole.OWNER, P.VERSION_PROMOTE_LIVE, True),
        (WorkspaceRole.ADMIN, P.VERSION_PROMOTE_LIVE, False),
        (WorkspaceRole.EVALUATOR, P.VERSION_PROMOTE_LIVE, False),
        (WorkspaceRole.OWNER, P.VERSION_ROLLBACK, True),
        (WorkspaceRole.ADMIN, P.VERSION_ROLLBACK, False),
        (WorkspaceRole.EVALUATOR, P.VERSION_PROMOTE_LIVESH, True),
        (WorkspaceRole.DEVELOPER, P.VERSION_PROMOTE_LIVESH, False),
        (WorkspaceRole.EVALUATOR, P.PROPOSAL_REVIEW, True),
        (WorkspaceRole.DEVELOPER, P.PROPOSAL_REVIEW, False),
        (WorkspaceRole.DEVELOPER, P.PROPOSAL_SUBMIT, True),
        (WorkspaceRole.VIEWER, P.PROPOSAL_SUBMIT, False),
        (WorkspaceRole.VIEWER, P.RUN_CREATE, False),
        (WorkspaceRole.VIEWER, P.TRACE_READ, True),
        (WorkspaceRole.VIEWER, P.TRACE_READ_RAW, False),
        (WorkspaceRole.ADMIN, P.TRACE_READ_RAW, True),
        (WorkspaceRole.ADMIN, P.GATE_CONFIGURE, True),
        (WorkspaceRole.DEVELOPER, P.GATE_CONFIGURE, False),
        (WorkspaceRole.OWNER, P.TENANT_PURGE, True),
        (WorkspaceRole.ADMIN, P.TENANT_PURGE, False),
    ],
)
def test_role_matrix(authorizer: Authorizer, role, permission, expected) -> None:
    decision = authorizer.decide(subject(role), permission)
    assert decision.allowed is expected, decision.reason


def test_every_role_has_a_matrix_entry() -> None:
    assert set(ROLE_PERMISSIONS) == set(WorkspaceRole)


def test_owner_has_superset_of_admin(authorizer: Authorizer) -> None:
    owner = ROLE_PERMISSIONS[WorkspaceRole.OWNER]
    admin = ROLE_PERMISSIONS[WorkspaceRole.ADMIN]
    assert admin <= owner


# --------------------------------------------------------------------------- #
# 资源级 owner 约束
# --------------------------------------------------------------------------- #


def test_developer_can_create_version_only_on_own_resource(authorizer: Authorizer) -> None:
    assert authorizer.decide(subject(), P.ASSET_VERSION_CREATE, resource(owner_id=ME)).allowed
    denied = authorizer.decide(subject(), P.ASSET_VERSION_CREATE, resource(owner_id=OTHER))
    assert not denied.allowed and denied.denied_by == "ownership"


def test_admin_ignores_resource_ownership(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(WorkspaceRole.ADMIN), P.ASSET_VERSION_CREATE, resource(owner_id=OTHER)
    )
    assert decision.allowed


def test_owner_scoped_action_without_resource_is_denied(authorizer: Authorizer) -> None:
    decision = authorizer.decide(subject(), P.RUN_CONTROL)
    assert not decision.allowed and decision.denied_by == "ownership"


# --------------------------------------------------------------------------- #
# 隔离
# --------------------------------------------------------------------------- #


def test_cross_workspace_is_denied_first(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(WorkspaceRole.OWNER), P.ASSET_READ, resource(workspace_id=OTHER_WS)
    )
    assert not decision.allowed and decision.denied_by == "workspace"


def test_tenant_out_of_scope_is_denied(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(tenant_scope=(TENANT,)), P.TRACE_READ, resource(tenant_id=OTHER_TENANT)
    )
    assert not decision.allowed and decision.denied_by == "tenant_scope"


def test_tenant_in_scope_passes(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(tenant_scope=(TENANT,)), P.TRACE_READ, resource(tenant_id=TENANT)
    )
    assert decision.allowed


def test_workspace_check_precedes_tenant_check(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(tenant_scope=(TENANT,)),
        P.TRACE_READ,
        resource(workspace_id=OTHER_WS, tenant_id=OTHER_TENANT),
    )
    assert decision.denied_by == "workspace"


# --------------------------------------------------------------------------- #
# 机器凭证
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "permission",
    [P.PROPOSAL_REVIEW, P.VERSION_PROMOTE_LIVESH, P.VERSION_PROMOTE_LIVE, P.VERSION_ROLLBACK],
)
def test_credentials_can_never_review_or_promote(authorizer: Authorizer, permission) -> None:
    """需求 §9.13：自动生成的改进不能直接修改生产版本。"""
    decision = authorizer.decide(
        subject(kind="credential", role=None, credential_kind="evs"), permission
    )
    assert not decision.allowed and decision.denied_by == "auto_subject"


def test_tenant_sync_credential_can_sync(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(kind="credential", role=None, credential_kind="evs"), P.TENANT_SYNC
    )
    assert decision.allowed


def test_trace_credential_cannot_sync_tenants(authorizer: Authorizer) -> None:
    decision = authorizer.decide(
        subject(kind="credential", role=None, credential_kind="evk"), P.TENANT_SYNC
    )
    assert not decision.allowed and decision.denied_by == "credential"


# --------------------------------------------------------------------------- #
# 再认证
# --------------------------------------------------------------------------- #


def test_promote_live_requires_reauth(authorizer: Authorizer) -> None:
    decision = authorizer.decide(subject(WorkspaceRole.OWNER), P.VERSION_PROMOTE_LIVE)
    assert decision.allowed and decision.requires_reauth


def test_promote_livesh_does_not_require_reauth(authorizer: Authorizer) -> None:
    decision = authorizer.decide(subject(WorkspaceRole.EVALUATOR), P.VERSION_PROMOTE_LIVESH)
    assert decision.allowed and not decision.requires_reauth


def test_permissions_of_viewer(authorizer: Authorizer) -> None:
    assert P.TRACE_READ in authorizer.permissions_of(subject(WorkspaceRole.VIEWER))
    assert P.ASSET_CREATE not in authorizer.permissions_of(subject(WorkspaceRole.VIEWER))

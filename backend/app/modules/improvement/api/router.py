"""演化路由：提案、审批、应用、公共目录与派生。

权限边界（`MACHINE_FORBIDDEN` 已硬性收窄）：
- 提交提案：`proposal:submit`
- 审批：`proposal:review`——**机器凭证永远没有**，所以 Agent 改不了自己
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ....api.deps import Actor, assert_permission, get_container
from ....container import Container
from ....contracts.asset import AssetRef
from ....contracts.common import AssetKind
from ....contracts.errors import NotFound
from ....contracts.identity import Permission, ResourceRef
from ....contracts.improvement import ProposalEvidence
from ....schemas.response import list_response, ok
from .schemas import (
    ForkAssetRequest,
    ReviewProposalRequest,
    SubmitProposalRequest,
)

router = APIRouter(tags=["improvement"])


def _proposal_dto(proposal) -> dict:
    return {
        "id": proposal.id,
        "kind": proposal.kind,
        "status": proposal.status,
        "target_asset_id": proposal.target_asset_id,
        "base_version_id": proposal.base_version_id,
        "applied_version_id": proposal.applied_version_id,
        "rationale": proposal.rationale,
        "evidence": [
            {
                "kind": item.kind,
                "ref": item.ref,
                "summary": item.summary,
                "metrics": dict(item.metrics),
            }
            for item in proposal.evidence
        ],
        "created_by": proposal.created_by,
        "reviewed_by": proposal.reviewed_by,
        "review_note": proposal.review_note,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "reviewed_at": (
            proposal.reviewed_at.isoformat() if proposal.reviewed_at else None
        ),
    }


@router.post("/proposals")
async def submit_proposal(
    payload: SubmitProposalRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """提交演化提案。**必须带证据**——指向具体的失败 Trace 或指标回退。"""
    assert_permission(container, actor, Permission.PROPOSAL_SUBMIT)
    proposal = await container.proposals.submit(
        workspace_id=actor.workspace_id,
        kind=payload.kind,
        target_asset_id=payload.target_asset_id,
        created_by=actor.user_id,
        proposed_spec=payload.proposed_spec,
        base_version_id=payload.base_version_id,
        evidence=tuple(
            ProposalEvidence(
                kind=item.kind,
                ref=item.ref,
                summary=item.summary,
                metrics=dict(item.metrics),
            )
            for item in payload.evidence
        ),
        rationale=payload.rationale,
    )
    return ok(_proposal_dto(proposal))


@router.get("/proposals")
async def list_proposals(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    status: str | None = None,
) -> dict:
    assert_permission(container, actor, Permission.PROPOSAL_READ)
    if status == "submitted":
        items = await container.proposals.list_pending(actor.workspace_id)
    else:
        from ....persistence import UnitOfWork
        from ..infrastructure.repositories import ProposalRepository

        async with UnitOfWork(container.database) as uow:
            items = await ProposalRepository(uow.session).list_for_workspace(
                actor.workspace_id, status
            )
    return list_response([_proposal_dto(item) for item in items])


@router.get("/assets/{asset_id}/proposals")
async def list_asset_proposals(
    asset_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    assert_permission(container, actor, Permission.PROPOSAL_READ)
    items = await container.proposals.list_for_asset(asset_id, actor.workspace_id)
    return list_response([_proposal_dto(item) for item in items])


@router.post("/proposals/{proposal_id}/review")
async def review_proposal(
    proposal_id: str,
    payload: ReviewProposalRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """审批。**不能审自己的**——否则审核形同虚设。"""
    assert_permission(container, actor, Permission.PROPOSAL_REVIEW)
    proposal = await container.proposals.review(
        proposal_id=proposal_id,
        workspace_id=actor.workspace_id,
        approved=payload.approved,
        reviewer_id=actor.user_id,
        note=payload.note,
    )
    return ok(_proposal_dto(proposal))


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """应用已批准的提案。**只有 approved 能应用**，落成新版本、旧版本不动。"""
    assert_permission(container, actor, Permission.PROPOSAL_REVIEW)
    proposal = await container.proposals.apply(
        proposal_id=proposal_id,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
    )
    return ok(_proposal_dto(proposal))


@router.get("/public-assets")
async def list_public_assets(
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
    kind: AssetKind | None = None,
) -> dict:
    """公共目录：可以被其他 Agent 引用的共享资产。"""
    assert_permission(container, actor, Permission.ASSET_READ)
    items = await container.assets.list_publishable(actor.workspace_id, kind)
    return list_response(
        [
            {
                "id": item.id,
                "kind": item.kind.value,
                "name": item.name,
                "description": item.description,
                "owner": item.owner_id,
            }
            for item in items
        ]
    )


@router.post("/public-assets/fork")
async def fork_public_asset(
    payload: ForkAssetRequest,
    actor: Actor,
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """从公共资产派生一份自己的。**之后两条线各自独立演化。**"""
    assert_permission(container, actor, Permission.ASSET_CREATE)
    asset: AssetRef = await container.assets.fork_from(
        source_asset_id=payload.source_asset_id,
        workspace_id=actor.workspace_id,
        owner_id=actor.user_id,
        name=payload.name,
        description=payload.description,
    )
    return ok(
        {
            "id": asset.id,
            "name": asset.name,
            "description": asset.description,
            "forked_from": payload.source_asset_id,
        }
    )

"""演化用例：起草提案、审批、应用。

**应用是唯一改资产的地方**，而且必须先 `approved`——机器凭证连
`PROPOSAL_REVIEW` 都没有（`MACHINE_FORBIDDEN` 里收窄了），所以
「Agent 自己改自己」在权限层就不成立。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ....contracts.common import Channel, Id
from ....contracts.errors import DomainError, Errors, NotFound
from ....contracts.improvement import (
    ImpactReport,
    Proposal,
    ProposalEvidence,
    ProposalKind,
)
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.models import can_apply, can_transition, requires_spec
from ..infrastructure.repositories import ProposalRepository
from .ports import AssetEvolutionPort, ImpactQueryPort


class ProposalService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        assets: AssetEvolutionPort,
        impact: ImpactQueryPort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._assets = assets
        self._impact = impact

    # -- 起草 ----------------------------------------------------------------

    async def submit(
        self,
        *,
        workspace_id: str,
        kind: ProposalKind,
        target_asset_id: str,
        created_by: str,
        proposed_spec: Mapping[str, Any] | None = None,
        base_version_id: str | None = None,
        evidence: Sequence[ProposalEvidence] = (),
        rationale: str = "",
    ) -> Proposal:
        """起草并提交。**证据是硬要求**——没有证据就无从判断该不该批。"""
        if not evidence:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                "提案必须带证据：指向具体的失败 Trace 或指标回退，不能只写一段说明",
            )
        if requires_spec(kind) and not proposed_spec:
            raise DomainError(
                Errors.VALIDATION_FAILED, f"{kind} 提案必须给出新的 spec"
            )
        # 资产必须真实存在——避免提案指向一个不存在或不属于本工作区的资产。
        await self._assets.get_asset_ref(target_asset_id, workspace_id)

        proposal = Proposal(
            id=new_id("proposal"),
            workspace_id=workspace_id,
            kind=kind,
            status="submitted",
            target_asset_id=target_asset_id,
            proposed_spec=dict(proposed_spec or {}),
            base_version_id=base_version_id,
            evidence=tuple(evidence),
            rationale=rationale,
            created_by=created_by,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            await ProposalRepository(uow.session).add(proposal)
            await uow.commit()
        return proposal

    # -- 审批 ----------------------------------------------------------------

    async def review(
        self,
        *,
        proposal_id: str,
        workspace_id: str,
        approved: bool,
        reviewer_id: str,
        note: str = "",
    ) -> Proposal:
        proposal = await self.get(proposal_id, workspace_id)
        target = "approved" if approved else "rejected"
        if not can_transition(proposal.status, target):  # type: ignore[arg-type]
            raise DomainError(
                Errors.RUN_STATE_CONFLICT,
                f"提案当前是 {proposal.status}，不能变成 {target}",
            )
        if proposal.created_by == reviewer_id:
            raise DomainError(
                Errors.PERMISSION_DENIED, "不能审批自己的提案——否则审核形同虚设"
            )
        async with UnitOfWork(self._db) as uow:
            await ProposalRepository(uow.session).set_status(
                proposal_id,
                status=target,
                reviewed_by=reviewer_id,
                review_note=note,
                reviewed_at=self._clock.now(),
            )
            await uow.commit()
        return await self.get(proposal_id, workspace_id)

    # -- 应用 ----------------------------------------------------------------

    async def apply(
        self, *, proposal_id: str, workspace_id: str, actor_id: str
    ) -> Proposal:
        """把批准的提案落成**新版本**。旧版本不动——回退就是把指针改回去。"""
        proposal = await self.get(proposal_id, workspace_id)
        if not can_apply(proposal.status):
            raise DomainError(
                Errors.RUN_STATE_CONFLICT,
                f"提案是 {proposal.status}，只有已批准的才能应用",
            )
        if proposal.kind == "promote":
            await self._assets.promote_asset(proposal.target_asset_id, workspace_id)
            async with UnitOfWork(self._db) as uow:
                await ProposalRepository(uow.session).set_status(
                    proposal_id, status="applied"
                )
                await uow.commit()
            return await self.get(proposal_id, workspace_id)

        version = await self._assets.create_version_from_proposal(
            asset_id=proposal.target_asset_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            spec=proposal.proposed_spec,
        )
        async with UnitOfWork(self._db) as uow:
            await ProposalRepository(uow.session).mark_applied(proposal_id, version)
            await uow.commit()
        return await self.get(proposal_id, workspace_id)

    # -- 查询 ----------------------------------------------------------------

    async def get(self, proposal_id: str, workspace_id: str) -> Proposal:
        async with UnitOfWork(self._db) as uow:
            proposal = await ProposalRepository(uow.session).get(proposal_id, workspace_id)
        if proposal is None:
            raise NotFound("提案", proposal_id)
        return proposal

    async def list_for_asset(self, asset_id: str, workspace_id: str) -> Sequence[Proposal]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await ProposalRepository(uow.session).list_for_asset(asset_id, workspace_id)
            )

    async def list_pending(self, workspace_id: str) -> Sequence[Proposal]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await ProposalRepository(uow.session).list_for_workspace(
                    workspace_id, status="submitted"
                )
            )

    # -- 影响面 --------------------------------------------------------------

    async def impact(self, asset_id: str, workspace_id: str) -> ImpactReport:
        """改之前先看会影响谁——公共资产可能被几十个 Agent 引用。"""
        return await self._impact.impact_of(asset_id, workspace_id)


__all__ = ["ProposalService"]

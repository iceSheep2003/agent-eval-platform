"""提案仓储。**没有 delete**——证据链不删。"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.improvement import (
    Proposal,
    ProposalEvidence,
    ProposalKind,
    ProposalStatus,
)
from ....shared.clock import ensure_aware
from .tables import ProposalRow


def _proposal(row: ProposalRow) -> Proposal:
    return Proposal(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        target_asset_id=row.target_asset_id,
        proposed_spec=dict(row.proposed_spec or {}),
        base_version_id=row.base_version_id,
        evidence=tuple(
            ProposalEvidence(
                kind=item.get("kind", "manual"),
                ref=item.get("ref", ""),
                summary=item.get("summary", ""),
                metrics=dict(item.get("metrics") or {}),
            )
            for item in (row.evidence or [])
        ),
        rationale=row.rationale,
        applied_version_id=row.applied_version_id,
        created_by=row.created_by,
        reviewed_by=row.reviewed_by,
        review_note=row.review_note,
        created_at=ensure_aware(row.created_at),
        reviewed_at=ensure_aware(row.reviewed_at) if row.reviewed_at else None,
    )


class ProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, proposal_id: str, workspace_id: str) -> Proposal | None:
        stmt = select(ProposalRow).where(
            ProposalRow.id == proposal_id, ProposalRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _proposal(row) if row else None

    async def list_for_asset(
        self, asset_id: str, workspace_id: str
    ) -> Sequence[Proposal]:
        stmt = (
            select(ProposalRow)
            .where(
                ProposalRow.target_asset_id == asset_id,
                ProposalRow.workspace_id == workspace_id,
            )
            .order_by(ProposalRow.created_at.desc())
        )
        return [_proposal(row) for row in (await self._session.execute(stmt)).scalars().all()]

    async def list_for_workspace(
        self, workspace_id: str, status: str | None = None, limit: int = 100
    ) -> Sequence[Proposal]:
        stmt = select(ProposalRow).where(ProposalRow.workspace_id == workspace_id)
        if status is not None:
            stmt = stmt.where(ProposalRow.status == status)
        stmt = stmt.order_by(ProposalRow.created_at.desc()).limit(limit)
        return [_proposal(row) for row in (await self._session.execute(stmt)).scalars().all()]

    async def add(self, proposal: Proposal) -> None:
        self._session.add(
            ProposalRow(
                id=proposal.id,
                workspace_id=proposal.workspace_id,
                kind=proposal.kind,
                status=proposal.status,
                target_asset_id=proposal.target_asset_id,
                base_version_id=proposal.base_version_id,
                proposed_spec=dict(proposal.proposed_spec),
                evidence=[
                    {
                        "kind": item.kind,
                        "ref": item.ref,
                        "summary": item.summary,
                        "metrics": dict(item.metrics),
                    }
                    for item in proposal.evidence
                ],
                rationale=proposal.rationale,
                created_by=proposal.created_by,
            )
        )

    async def set_status(
        self,
        proposal_id: str,
        *,
        status: str,
        reviewed_by: str | None = None,
        review_note: str = "",
        reviewed_at: datetime | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status}
        if reviewed_by is not None:
            values["reviewed_by"] = reviewed_by
            values["review_note"] = review_note
            values["reviewed_at"] = reviewed_at
        await self._session.execute(
            update(ProposalRow).where(ProposalRow.id == proposal_id).values(**values)
        )

    async def mark_applied(self, proposal_id: str, version_id: str) -> None:
        await self._session.execute(
            update(ProposalRow)
            .where(ProposalRow.id == proposal_id)
            .values(status="applied", applied_version_id=version_id)
        )

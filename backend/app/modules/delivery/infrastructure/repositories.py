"""delivery 仓储。"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import Channel
from ....shared.clock import ensure_aware
from ..domain.models import Promotion, Rollback, ShadowRoute
from .tables import PromotionRow, RollbackRow, ShadowRouteRow


def _promotion(row: PromotionRow) -> Promotion:
    return Promotion(
        id=row.id,
        workspace_id=row.workspace_id,
        asset_id=row.asset_id,
        version_id=row.version_id,
        from_channel=Channel(row.from_channel),
        to_channel=Channel(row.to_channel),
        run_id=row.run_id,
        gate_passed=bool(row.gate_passed),
        blocked_rules=tuple(row.blocked_rules or ()),
        requested_by=row.requested_by,
        created_at=ensure_aware(row.created_at),
    )


def _rollback(row: RollbackRow) -> Rollback:
    return Rollback(
        id=row.id,
        workspace_id=row.workspace_id,
        asset_id=row.asset_id,
        channel=Channel(row.channel),
        from_version_id=row.from_version_id,
        to_version_id=row.to_version_id,
        reason=row.reason,
        actor_id=row.actor_id,
        created_at=ensure_aware(row.created_at),
    )


def _shadow(row: ShadowRouteRow) -> ShadowRoute:
    return ShadowRoute(
        id=row.id,
        workspace_id=row.workspace_id,
        asset_id=row.asset_id,
        candidate_version_id=row.candidate_version_id,
        baseline_version_id=row.baseline_version_id,
        sample_rate=float(row.sample_rate),
        direction=row.direction,  # type: ignore[arg-type]
        enabled=bool(row.enabled),
        created_at=ensure_aware(row.created_at),
    )


class PromotionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_asset(self, asset_id: str, workspace_id: str) -> Sequence[Promotion]:
        stmt = (
            select(PromotionRow)
            .where(PromotionRow.asset_id == asset_id, PromotionRow.workspace_id == workspace_id)
            .order_by(PromotionRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_promotion(row) for row in rows]

    def add(self, promotion: Promotion) -> None:
        self._session.add(
            PromotionRow(
                id=promotion.id,
                workspace_id=promotion.workspace_id,
                asset_id=promotion.asset_id,
                version_id=promotion.version_id,
                from_channel=promotion.from_channel.value,
                to_channel=promotion.to_channel.value,
                run_id=promotion.run_id,
                gate_passed=promotion.gate_passed,
                blocked_rules=list(promotion.blocked_rules),
                requested_by=promotion.requested_by,
            )
        )


class RollbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_asset(self, asset_id: str, workspace_id: str) -> Sequence[Rollback]:
        stmt = (
            select(RollbackRow)
            .where(RollbackRow.asset_id == asset_id, RollbackRow.workspace_id == workspace_id)
            .order_by(RollbackRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_rollback(row) for row in rows]

    def add(self, rollback: Rollback) -> None:
        self._session.add(
            RollbackRow(
                id=rollback.id,
                workspace_id=rollback.workspace_id,
                asset_id=rollback.asset_id,
                channel=rollback.channel.value,
                from_version_id=rollback.from_version_id,
                to_version_id=rollback.to_version_id,
                reason=rollback.reason,
                actor_id=rollback.actor_id,
            )
        )


class ShadowRouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, asset_id: str, workspace_id: str) -> ShadowRoute | None:
        stmt = (
            select(ShadowRouteRow)
            .where(ShadowRouteRow.asset_id == asset_id, ShadowRouteRow.workspace_id == workspace_id)
            .order_by(ShadowRouteRow.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _shadow(row) if row else None

    def add(self, route: ShadowRoute) -> None:
        self._session.add(
            ShadowRouteRow(
                id=route.id,
                workspace_id=route.workspace_id,
                asset_id=route.asset_id,
                candidate_version_id=route.candidate_version_id,
                baseline_version_id=route.baseline_version_id,
                sample_rate=route.sample_rate,
                direction=route.direction,
                enabled=route.enabled,
            )
        )

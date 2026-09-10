"""deployment 仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....contracts.common import Channel
from ....shared.clock import ensure_aware
from ..domain.models import Instance, InstanceState
from .tables import InstanceRow


def _instance(row: InstanceRow) -> Instance:
    return Instance(
        id=row.id,
        workspace_id=row.workspace_id,
        asset_id=row.asset_id,
        asset_version_id=row.asset_version_id,
        channel=Channel(row.channel),
        state=InstanceState(row.state),
        runtime_type=row.runtime_type,
        handle_id=row.handle_id,
        endpoint=row.endpoint,
        error=row.error,
        started_at=ensure_aware(row.started_at) if row.started_at else None,
        stopped_at=ensure_aware(row.stopped_at) if row.stopped_at else None,
        last_health_at=ensure_aware(row.last_health_at) if row.last_health_at else None,
        created_at=ensure_aware(row.created_at),
    )


class InstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, instance_id: str, workspace_id: str) -> Instance | None:
        stmt = select(InstanceRow).where(
            InstanceRow.id == instance_id, InstanceRow.workspace_id == workspace_id
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _instance(row) if row else None

    async def get_by_channel(
        self, asset_id: str, channel: Channel, workspace_id: str
    ) -> Instance | None:
        stmt = select(InstanceRow).where(
            InstanceRow.asset_id == asset_id,
            InstanceRow.channel == channel.value,
            InstanceRow.workspace_id == workspace_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _instance(row) if row else None

    async def list_for_asset(self, asset_id: str, workspace_id: str) -> Sequence[Instance]:
        stmt = (
            select(InstanceRow)
            .where(InstanceRow.asset_id == asset_id, InstanceRow.workspace_id == workspace_id)
            .order_by(InstanceRow.channel)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_instance(row) for row in rows]

    async def upsert(
        self,
        *,
        instance_id: str,
        workspace_id: str,
        asset_id: str,
        asset_version_id: str,
        channel: Channel,
        runtime_type: str,
        state: InstanceState,
        handle_id: str | None,
        endpoint: str | None,
        error: str | None,
        started_at: datetime | None,
        stopped_at: datetime | None,
    ) -> None:
        """一个 (资产, 通道) 一行——重复启动更新同一行，不产生第二条。"""
        existing = await self.get_by_channel(asset_id, channel, workspace_id)
        values: dict[str, Any] = {
            "asset_version_id": asset_version_id,
            "runtime_type": runtime_type,
            "state": state.value,
            "handle_id": handle_id,
            "endpoint": endpoint,
            "error": error,
            "started_at": started_at,
            "stopped_at": stopped_at,
        }
        if existing is None:
            self._session.add(
                InstanceRow(
                    id=instance_id,
                    workspace_id=workspace_id,
                    asset_id=asset_id,
                    channel=channel.value,
                    **values,
                )
            )
        else:
            await self._session.execute(
                update(InstanceRow).where(InstanceRow.id == existing.id).values(**values)
            )

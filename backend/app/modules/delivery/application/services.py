"""发布控制用例：晋级、回退、影子路由。

**门禁是硬约束**：晋级必须持有该版本一次「发布门禁阶段 + 已完成 + 判定通过」的 Run。
门禁未通过时抛 409 `gate_blocked`——不是 403，因为这不是权限问题。
"""

from __future__ import annotations

from typing import Sequence

from ....contracts.asset import AssetQueryPort, ChannelWritePort
from ....contracts.common import Channel, EvaluationStage, Id, VersionLifecycle
from ....contracts.errors import DomainError, Errors, GateBlocked, NotFound
from ....contracts.execution import RunQueryPort
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ..domain.models import (
    REQUIRED_STAGE,
    Promotion,
    Rollback,
    ShadowRoute,
    resolve_promotion,
)
from ..infrastructure.repositories import (
    PromotionRepository,
    RollbackRepository,
    ShadowRouteRepository,
)


class DeliveryService:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        assets: AssetQueryPort,
        channels: ChannelWritePort,
        runs: RunQueryPort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._assets = assets
        self._channels = channels
        self._runs = runs

    # -- 晋级 ----------------------------------------------------------------

    async def request_promotion(
        self,
        *,
        asset_id: Id,
        version_id: Id,
        to_channel: Channel,
        run_id: Id | None,
        workspace_id: Id,
        actor_id: Id,
    ) -> Promotion:
        version = await self._assets.get_version_ref(version_id, workspace_id)
        if version is None or version.asset_id != asset_id:
            raise NotFound("版本", version_id)

        bindings = await self._assets.channel_map(asset_id, workspace_id)
        try:
            from_channel = resolve_promotion(version_id, bindings, to_channel)
        except ValueError as exc:
            raise DomainError(Errors.PROMOTION_ORDER_VIOLATION, str(exc)) from exc

        stage = EvaluationStage(REQUIRED_STAGE[to_channel])
        run = (
            await self._runs.get_run_ref(run_id, workspace_id)
            if run_id is not None
            else await self._runs.find_gate_run(version_id, stage, workspace_id)
        )
        if run is None:
            raise DomainError(
                Errors.GATE_BLOCKED,
                f"版本 {version.version_label} 没有可用于晋级的评测结果"
                f"（需要一次 {stage.value} 阶段且已完成的运行）",
            )
        if run.subject_version_id != version_id:
            raise DomainError(
                Errors.VALIDATION_FAILED, "所选运行评的不是这个版本，不能作为晋级依据"
            )
        if not run.gate_passed:
            blocked = tuple((run.gate_decision or {}).get("blocked_rules") or ())
            raise GateBlocked(blocked)

        await self._channels.bind_channel(
            asset_id=asset_id,
            channel=to_channel,
            version_id=version_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
        )
        await self._channels.set_version_lifecycle(
            version_id, VersionLifecycle.READY, workspace_id
        )

        promotion = Promotion(
            id=new_id("promotion"),
            workspace_id=workspace_id,
            asset_id=asset_id,
            version_id=version_id,
            from_channel=from_channel,
            to_channel=to_channel,
            run_id=run.id,
            gate_passed=True,
            blocked_rules=(),
            requested_by=actor_id,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            PromotionRepository(uow.session).add(promotion)
            await uow.commit()
        return promotion

    async def list_promotions(self, asset_id: Id, workspace_id: Id) -> Sequence[Promotion]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await PromotionRepository(uow.session).list_for_asset(asset_id, workspace_id)
            )

    # -- 回退 ----------------------------------------------------------------

    async def rollback(
        self,
        *,
        asset_id: Id,
        channel: Channel,
        to_version_id: Id,
        reason: str,
        workspace_id: Id,
        actor_id: Id,
    ) -> Rollback:
        """回退 = 通道指针改回历史版本。**问题版本与证据全部保留。**"""
        target = await self._assets.get_version_ref(to_version_id, workspace_id)
        if target is None or target.asset_id != asset_id:
            raise NotFound("版本", to_version_id)
        if not reason.strip():
            raise DomainError(Errors.VALIDATION_FAILED, "回退必须填写原因")

        bindings = await self._assets.channel_map(asset_id, workspace_id)
        current_version_id = bindings.get(channel)
        if current_version_id == to_version_id:
            raise DomainError(Errors.RUN_STATE_CONFLICT, "该通道已经指向这个版本")

        await self._channels.bind_channel(
            asset_id=asset_id,
            channel=channel,
            version_id=to_version_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
        )
        rollback = Rollback(
            id=new_id("rollback"),
            workspace_id=workspace_id,
            asset_id=asset_id,
            channel=channel,
            from_version_id=current_version_id,
            to_version_id=to_version_id,
            reason=reason,
            actor_id=actor_id,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            RollbackRepository(uow.session).add(rollback)
            await uow.commit()
        return rollback

    async def list_rollbacks(self, asset_id: Id, workspace_id: Id) -> Sequence[Rollback]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await RollbackRepository(uow.session).list_for_asset(asset_id, workspace_id)
            )

    # -- 影子 ----------------------------------------------------------------

    async def configure_shadow(
        self,
        *,
        asset_id: Id,
        candidate_version_id: Id,
        baseline_version_id: Id | None,
        sample_rate: float,
        workspace_id: Id,
        enabled: bool = True,
    ) -> ShadowRoute:
        candidate = await self._assets.get_version_ref(candidate_version_id, workspace_id)
        if candidate is None or candidate.asset_id != asset_id:
            raise NotFound("版本", candidate_version_id)
        if baseline_version_id is not None:
            baseline = await self._assets.get_version_ref(baseline_version_id, workspace_id)
            if baseline is None or baseline.asset_id != asset_id:
                raise NotFound("基线版本", baseline_version_id)

        route = ShadowRoute(
            id=new_id("shadow_route"),
            workspace_id=workspace_id,
            asset_id=asset_id,
            candidate_version_id=candidate_version_id,
            baseline_version_id=baseline_version_id,
            sample_rate=sample_rate,
            direction="copy_in_only",  # 固定：影子输出永不返回给真实用户
            enabled=enabled,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            ShadowRouteRepository(uow.session).add(route)
            await uow.commit()
        return route

    async def get_shadow(self, asset_id: Id, workspace_id: Id) -> ShadowRoute | None:
        async with UnitOfWork(self._db) as uow:
            return await ShadowRouteRepository(uow.session).get(asset_id, workspace_id)

"""发布控制用例：晋级、回退、影子路由。

**门禁是硬约束**：晋级必须持有该版本一次「发布门禁阶段 + 已完成 + 判定通过」的 Run。
门禁未通过时抛 409 `gate_blocked`——不是 403，因为这不是权限问题。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from datetime import timedelta

from ....contracts.asset import AssetQueryPort, ChannelWritePort
from ....contracts.common import Channel, EvaluationStage, Id, TraceOrigin, VersionLifecycle, Window
from ....contracts.errors import DomainError, Errors, GateBlocked, NotFound
from ....contracts.execution import RunQueryPort, RunRef
from ....contracts.observability import VersionMetrics, VersionMetricsPort
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
    #: 影子验证的观察窗口
    SHADOW_WINDOW_DAYS = 7
    #: 影子样本少于这个数就不下结论——小样本的通过率抖动大
    SHADOW_MIN_SAMPLES = 30
    #: 允许候选比基线低 2 个百分点的成功率
    SUCCESS_RATE_TOLERANCE = 0.02
    #: 允许候选的 P95 比基线高 20%
    LATENCY_TOLERANCE = 0.20

    def __init__(
        self,
        database: Database,
        clock: Clock,
        assets: AssetQueryPort,
        channels: ChannelWritePort,
        runs: RunQueryPort,
        metrics: VersionMetricsPort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._assets = assets
        self._channels = channels
        self._runs = runs
        self._metrics = metrics

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

        # 两个通道都先过发布门禁；再按目标通道追加各自的前置条件。
        run = await self._require_passing_gate(
            version_id, version.version_label, run_id, to_channel, workspace_id
        )
        if to_channel is Channel.LIVESH:
            await self._require_shadow_route(asset_id, version_id, workspace_id)
        elif to_channel is Channel.LIVE:
            await self._require_shadow_verification(
                asset_id, version_id, version.version_label, workspace_id
            )

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

    async def _require_passing_gate(
        self,
        version_id: Id,
        version_label: str,
        run_id: Id | None,
        to_channel: Channel,
        workspace_id: Id,
    ) -> RunRef:
        """发布门禁：必须有该版本一次「release 阶段 + 已完成 + 判定通过」的 Run。"""
        stage = EvaluationStage(REQUIRED_STAGE[to_channel])
        run = (
            await self._runs.get_run_ref(run_id, workspace_id)
            if run_id is not None
            else await self._runs.find_gate_run(version_id, stage, workspace_id)
        )
        if run is None:
            raise DomainError(
                Errors.GATE_BLOCKED,
                f"版本 {version_label} 没有可用于晋级的评测结果"
                f"（需要一次 {stage.value} 阶段且已完成的运行）",
            )
        if run.subject_version_id != version_id:
            raise DomainError(
                Errors.VALIDATION_FAILED, "所选运行评的不是这个版本，不能作为晋级依据"
            )
        if not run.gate_passed:
            blocked = tuple((run.gate_decision or {}).get("blocked_rules") or ())
            raise GateBlocked(blocked)
        return run

    async def _require_shadow_route(
        self, asset_id: Id, version_id: Id, workspace_id: Id
    ) -> None:
        """进入 LIVESH 前必须配好影子路由——否则「影子验证」无从谈起。"""
        route = await self.get_shadow(asset_id, workspace_id)
        if route is None or not route.enabled:
            raise DomainError(
                Errors.GATE_BLOCKED,
                "进入 LIVESH 前需要先配置影子路由（复制多少生产流量、以哪个版本为基线）",
                channel=Channel.LIVESH.value,
            )
        if route.candidate_version_id != version_id:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                "影子路由指向的是另一个候选版本，请先改为本次要晋级的版本",
            )

    async def _require_shadow_verification(
        self, asset_id: Id, version_id: Id, version_label: str, workspace_id: Id
    ) -> None:
        """LIVESH → LIVE：候选要在**真实分布**下不劣于当前 LIVE 基线。

        比对的是「候选版本在 shadow 下的指标」与「LIVE 版本在 production 下的指标」，
        而不是同一个 Agent 的整体平均——后者会把两个版本混在一起，看不出退化。
        """
        route = await self.get_shadow(asset_id, workspace_id)
        if route is None or not route.enabled:
            raise DomainError(
                Errors.GATE_BLOCKED, "没有生效中的影子路由，无法判断影子验证是否通过"
            )
        if route.candidate_version_id != version_id:
            raise DomainError(
                Errors.VALIDATION_FAILED, "影子路由的候选版本与本次晋级版本不一致"
            )

        now = self._clock.now()
        window = Window(
            start=now - timedelta(days=self.SHADOW_WINDOW_DAYS), end=now
        )
        candidate = await self._metrics.version_metrics(
            version_id, TraceOrigin.SHADOW, window
        )
        if candidate.trace_count < self.SHADOW_MIN_SAMPLES:
            raise DomainError(
                Errors.GATE_BLOCKED,
                f"影子样本不足：{candidate.trace_count} < {self.SHADOW_MIN_SAMPLES}，"
                f"还不能判断候选是否稳定",
                trace_count=candidate.trace_count,
            )

        baseline_version_id = route.baseline_version_id or (
            await self._assets.channel_map(asset_id, workspace_id)
        ).get(Channel.LIVE)

        # 首次发布：LIVE 还没有版本，没有基线可比。此时不阻断，但样本门槛仍然要过
        # ——它证明候选在真实流量分布下跑得起来。比对留到第二次及以后。
        if baseline_version_id is None:
            return
        baseline = await self._metrics.version_metrics(
            baseline_version_id, TraceOrigin.PRODUCTION, window
        )
        if not baseline.has_samples:
            return

        broken: list[str] = []
        if (
            baseline.success_rate is not None
            and candidate.success_rate is not None
            and candidate.success_rate < baseline.success_rate - self.SUCCESS_RATE_TOLERANCE
        ):
            broken.append("shadow_success_rate")
        if (
            baseline.p95_latency_ms
            and candidate.p95_latency_ms
            and candidate.p95_latency_ms > baseline.p95_latency_ms * (1 + self.LATENCY_TOLERANCE)
        ):
            broken.append("shadow_p95_latency")

        if broken:
            raise GateBlocked(tuple(broken))

    async def shadow_comparison(
        self, asset_id: Id, version_id: Id, workspace_id: Id
    ) -> Mapping[str, Any]:
        """给前端展示「候选 vs 基线」的原始指标，便于解释为什么被阻断。"""
        now = self._clock.now()
        window = Window(start=now - timedelta(days=self.SHADOW_WINDOW_DAYS), end=now)
        route = await self.get_shadow(asset_id, workspace_id)
        baseline_version_id = (route.baseline_version_id if route else None) or (
            await self._assets.channel_map(asset_id, workspace_id)
        ).get(Channel.LIVE)
        return {
            "window_days": self.SHADOW_WINDOW_DAYS,
            "min_samples": self.SHADOW_MIN_SAMPLES,
            "candidate": await self._metrics.version_metrics(
                version_id, TraceOrigin.SHADOW, window
            ),
            "baseline": (
                await self._metrics.version_metrics(
                    baseline_version_id, TraceOrigin.PRODUCTION, window
                )
                if baseline_version_id
                else None
            ),
        }

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

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
from ..domain.lifecycle import (
    DEFAULT_POLICY,
    CheckName,
    LifecyclePolicy,
    TransitionRule,
    current_channel,
)
from ..domain.models import (
    Promotion,
    Rollback,
    ShadowRoute,
    resolve_promotion,
)
from .checks import CheckContext, check_for
from ..infrastructure.repositories import (
    LifecyclePolicyRepository,
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
        metrics: VersionMetricsPort,
    ) -> None:
        self._db = database
        self._clock = clock
        self._assets = assets
        self._channels = channels
        self._runs = runs
        self._metrics = metrics

    # -- 晋级 ----------------------------------------------------------------

    async def pending_transition(
        self, asset_id: Id, version_id: Id, to_channel: Channel, workspace_id: Id
    ) -> TransitionRule:
        """这次晋级要走的迁移规则。

        控制器先拿它做**权限**校验，再调 `request_promotion` 真正执行——
        权限点写在策略里，不再散落在路由文件。
        """
        bindings = await self._assets.channel_map(asset_id, workspace_id)
        current = current_channel(version_id, bindings)
        if current is None:
            raise DomainError(
                Errors.PROMOTION_ORDER_VIOLATION,
                f"版本 {version_id} 当前没有绑定任何通道，不能晋级",
            )
        policy = await self.policy_for(workspace_id)
        rule = policy.rule_for(current, to_channel)
        if rule is None:
            expected = policy.next_channel(current)
            if expected is None:
                raise DomainError(
                    Errors.PROMOTION_ORDER_VIOLATION, f"{current.value} 已经是最高通道，不能再晋级"
                )
            raise DomainError(
                Errors.PROMOTION_ORDER_VIOLATION,
                f"只能从 {current.value} 晋级到 {expected.value}，不能直接到 {to_channel.value}",
            )
        return rule

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

        # 1) 迁移是否合法（逐级、不跳级）
        rule = await self.pending_transition(asset_id, version_id, to_channel, workspace_id)

        # 2) 按声明**顺序**跑检查。第一个不通过就停——后面的检查通常依赖前面成立。
        blocked: list[str] = []
        for spec in rule.enabled_checks():
            outcome = await check_for(spec.name)(
                CheckContext(
                    workspace_id=workspace_id,
                    asset_id=asset_id,
                    version_id=version_id,
                    version_label=version.version_label,
                    to_channel=to_channel,
                    params=spec.params,
                    runs=self._runs,
                    assets=self._assets,
                    metrics=self._metrics,
                    clock=self._clock,
                    shadow_route=lambda: self.get_shadow(asset_id, workspace_id),
                )
            )
            if not outcome.passed:
                # 把该检查声明的阻断理由一并抛出，前端能直接展示
                blocked.append(outcome.rule)
                raise GateBlocked(tuple(blocked)) if len(blocked) > 1 else DomainError(
                    Errors.GATE_BLOCKED, outcome.reason or outcome.rule
                )

        # 3) 落指针 + 生命周期
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
            from_channel=rule.from_channel,
            to_channel=to_channel,
            run_id=await self._audit_run_id(version_id, rule, workspace_id),
            gate_passed=True,
            blocked_rules=(),
            requested_by=actor_id,
            created_at=self._clock.now(),
        )
        async with UnitOfWork(self._db) as uow:
            PromotionRepository(uow.session).add(promotion)
            await uow.commit()
        return promotion

    async def _audit_run_id(
        self, version_id: Id, rule: TransitionRule, workspace_id: Id
    ) -> str:
        """审计行里记下「哪次 Run 的门禁放行了这次晋级」。"""
        gate = next(
            (spec for spec in rule.checks if spec.name is CheckName.PROMOTION_GATE),
            None,
        )
        if gate is None:
            return ""
        stage = EvaluationStage(gate.params.get("stage", EvaluationStage.RELEASE.value))
        run = await self._runs.find_gate_run(version_id, stage, workspace_id)
        return run.id if run else ""

    # -- 治理策略 ------------------------------------------------------------

    async def policy_for(self, workspace_id: Id) -> LifecyclePolicy:
        """工作区没自定义就用平台默认策略。"""
        async with UnitOfWork(self._db) as uow:
            stored = await LifecyclePolicyRepository(uow.session).get(workspace_id)
        return stored or DEFAULT_POLICY

    async def save_policy(
        self, workspace_id: Id, policy: LifecyclePolicy, actor_id: Id
    ) -> LifecyclePolicy:
        async with UnitOfWork(self._db) as uow:
            await LifecyclePolicyRepository(uow.session).upsert(workspace_id, policy, actor_id)
            await uow.commit()
        return policy

    async def reset_policy(self, workspace_id: Id) -> LifecyclePolicy:
        async with UnitOfWork(self._db) as uow:
            await LifecyclePolicyRepository(uow.session).remove(workspace_id)
            await uow.commit()
        return DEFAULT_POLICY

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

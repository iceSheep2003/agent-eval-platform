"""实例启停用例。

**启动是显式动作**：冻结版本不启动，晋级也不启动（LIVE 除外——见 `delivery`）。
启动的前提是「该通道已绑定一个版本」，否则没有东西可跑。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Sequence

from ....contracts.asset import AssetQueryPort
from ....contracts.common import Channel, Id
from ....contracts.deployment import InstanceRef
from ....contracts.errors import DomainError, Errors, NotFound
from ....persistence import UnitOfWork
from ....persistence.database import Database
from ....shared.clock import Clock
from ....shared.ids import new_id
from ....contracts.execution import (
    HealthResult,
    InvocationContext,
    RuntimeHandle,
    RuntimePort,
    RuntimeSpec,
)
from ..domain.models import (
    ACTIVE_STATES,
    SERVING_STATES,
    INSTANCE_CHANNELS,
    Instance,
    InstanceMachine,
    InstanceState,
)
from ..infrastructure.repositories import InstanceRepository

logger = logging.getLogger(__name__)

#: 启动/停止的宽限期。生产环境起 Pod 可能很久，这里只用于本地与测试。
DEFAULT_START_TIMEOUT_SECONDS = 120.0


class DeploymentService:
    """实现 `contracts.deployment.InstanceLookupPort` 与 `InstanceControlPort`。"""

    def __init__(
        self,
        database: Database,
        clock: Clock,
        assets: AssetQueryPort,
        runtime: RuntimePort,
        *,
        health_interval_seconds: int = 30,
        health_failure_threshold: int = 3,
    ) -> None:
        self._db = database
        self._clock = clock
        self._assets = assets
        self._runtime = runtime
        self._interval = timedelta(seconds=health_interval_seconds)
        self._failure_threshold = health_failure_threshold

    # -- 查询 ----------------------------------------------------------------

    async def list_instances(self, asset_id: Id, workspace_id: Id) -> Sequence[Instance]:
        async with UnitOfWork(self._db) as uow:
            return list(
                await InstanceRepository(uow.session).list_for_asset(asset_id, workspace_id)
            )

    async def get(self, instance_id: Id, workspace_id: Id) -> Instance:
        async with UnitOfWork(self._db) as uow:
            instance = await InstanceRepository(uow.session).get(instance_id, workspace_id)
        if instance is None:
            raise NotFound("实例", instance_id)
        return instance

    async def running_for(
        self, asset_id: Id, channel: Channel, workspace_id: Id
    ) -> InstanceRef | None:
        """实现 `InstanceLookupPort`：网关调用时查这个通道有没有在跑的实例。"""
        async with UnitOfWork(self._db) as uow:
            instance = await InstanceRepository(uow.session).get_by_channel(
                asset_id, channel, workspace_id
            )
        # DEGRADED 不返回——不健康的实例必须被摘出流量，否则探活只是装饰
        return _to_ref(instance) if instance and instance.is_serving else None

    # -- 探活 ----------------------------------------------------------------

    async def probe(self, instance_id: Id, workspace_id: Id) -> Instance:
        """探活一次，按结果迁移状态。

        成功 → 计数清零；若之前是 DEGRADED 则恢复到 RUNNING。
        失败 → 累计计数，先降为 DEGRADED（摘出流量），超过阈值才 FAILED。
        **不自动重启**：沉默的重试会掩盖真实故障。
        """
        instance = await self.get(instance_id, workspace_id)
        if instance.state not in ACTIVE_STATES:
            return instance  # 只有活跃实例需要探活

        result: HealthResult = await self._runtime.health(_handle(instance))
        now = self._clock.now()
        failures = 0 if result.healthy else instance.consecutive_failures + 1
        machine = InstanceMachine(state=instance.state)

        if result.healthy:
            # STARTING → RUNNING（首次探活）、DEGRADED → RUNNING（恢复）
            machine.to(InstanceState.RUNNING)
        elif failures >= self._failure_threshold:
            machine.to(InstanceState.FAILED)
        elif machine.state is InstanceState.RUNNING:
            machine.to(InstanceState.DEGRADED)

        async with UnitOfWork(self._db) as uow:
            await InstanceRepository(uow.session).record_health(
                instance.id,
                state=machine.state,
                failures=failures,
                detail=result.detail,
                checked_at=now,
            )
            await uow.commit()
        return await self.get(instance_id, workspace_id)

    async def probe_due(self) -> int:
        """扫描所有到期的活跃实例并探活，返回探活数量。

        **谁调用它决定调度形态**：现在由 Worker 的循环周期性调用；
        上 k8s 后换成 CronJob 或独立的探活 Deployment 调同一个方法，
        业务逻辑与状态机完全不动。
        """
        cutoff = self._clock.now() - self._interval
        async with UnitOfWork(self._db) as uow:
            due = await InstanceRepository(uow.session).list_due(cutoff)
        probed = 0
        for instance in due:
            try:
                await self.probe(instance.id, instance.workspace_id)
                probed += 1
            except Exception as exc:  # noqa: BLE001 - 单个实例探活失败不该中断整轮
                logger.warning("实例探活异常 %s: %r", instance.id, exc)
        return probed

    # -- 启停 ----------------------------------------------------------------

    async def start(
        self, *, asset_id: Id, channel: Channel, workspace_id: Id, actor_id: Id
    ) -> Instance:
        """把该通道当前绑定的版本跑起来。

        三条前置：通道得支持常驻实例、通道得绑了版本、不能已经有实例在跑。
        """
        if channel not in INSTANCE_CHANNELS:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                f"{channel.value} 是候选通道，不需要常驻实例；调试走临时沙箱即可",
            )

        bindings = await self._assets.channel_map(asset_id, workspace_id)
        version_id = bindings.get(channel)
        if version_id is None:
            raise DomainError(
                Errors.VALIDATION_FAILED,
                f"{channel.value} 通道还没有绑定版本，先晋级一个版本再启动",
            )

        async with UnitOfWork(self._db) as uow:
            existing = await InstanceRepository(uow.session).get_by_channel(
                asset_id, channel, workspace_id
            )
        if existing is not None and existing.state in ACTIVE_STATES:
            raise DomainError(
                Errors.RUN_STATE_CONFLICT,
                f"{channel.value} 通道已有实例（{existing.state.value}），不能重复启动",
            )

        version = await self._assets.get_version_ref(version_id, workspace_id)
        if version is None or not version.entrypoint:
            raise DomainError(
                Errors.VALIDATION_FAILED, "该版本没有 entrypoint，无法启动实例"
            )

        machine = InstanceMachine(state=existing.state if existing else InstanceState.STOPPED)
        machine.to(InstanceState.STARTING)
        await self._persist(existing, asset_id, version.id, channel, workspace_id, machine.state)

        ctx = InvocationContext(
            workspace_id=workspace_id,
            tenant_id=None,
            timeout_seconds=DEFAULT_START_TIMEOUT_SECONDS,
            cost_budget_usd=0.0,
        )
        try:
            handle = await self._runtime.provision(
                RuntimeSpec(
                    asset_id=asset_id,
                    asset_version_id=version.id,
                    workspace_id=workspace_id,
                    entrypoint=version.entrypoint,
                    spec=version.spec,
                ),
                ctx,
            )
        except Exception as exc:  # noqa: BLE001 - 起不来要如实记录，不吞
            logger.warning("实例启动失败 asset=%s channel=%s: %r", asset_id, channel, exc)
            machine.to(InstanceState.FAILED)
            await self._persist(
                existing, asset_id, version.id, channel, workspace_id,
                machine.state, error=str(exc),
            )
            raise DomainError(
                Errors.RUN_STATE_CONFLICT, f"实例启动失败：{exc}", channel=channel.value
            ) from exc

        # provision 返回 ≠ 已经能服务。本地沙箱几乎立刻可用，但 k8s 的 Pod
        # 还要等 readiness——所以这里**不直接写 RUNNING**，而是立刻探一次活，
        # 由观测结果决定。本地与 k8s 因此是同一条路径。
        await self._persist(
            existing, asset_id, version.id, channel, workspace_id, machine.state,
            handle_id=handle.id, endpoint=handle.endpoint,
            runtime_type=handle.runtime_type, started=True,
        )
        return await self.probe(instance_id=await self._instance_id(asset_id, channel, workspace_id),
                                workspace_id=workspace_id)

    async def stop(self, *, instance_id: Id, workspace_id: Id, actor_id: Id) -> Instance:
        instance = await self.get(instance_id, workspace_id)
        if instance.state is InstanceState.STOPPED:
            return instance

        machine = InstanceMachine(state=instance.state)
        machine.to(InstanceState.STOPPING)
        await self._persist_by_id(instance, machine.state)

        if instance.handle_id:
            try:
                await self._runtime.teardown(
                    _handle(instance)
                )
            except Exception as exc:  # noqa: BLE001 - 销毁失败不该把停止卡住
                logger.warning("实例 teardown 失败 %s: %r", instance.id, exc)

        machine.to(InstanceState.STOPPED)
        await self._persist_by_id(instance, machine.state, stopped=True)
        return await self.get(instance_id, workspace_id)

    async def restart(self, *, instance_id: Id, workspace_id: Id, actor_id: Id) -> Instance:
        instance = await self.get(instance_id, workspace_id)
        if instance.state in ACTIVE_STATES:
            await self.stop(instance_id=instance_id, workspace_id=workspace_id, actor_id=actor_id)
        return await self.start(
            asset_id=instance.asset_id,
            channel=instance.channel,
            workspace_id=workspace_id,
            actor_id=actor_id,
        )

    # -- 内部 ----------------------------------------------------------------

    async def _persist(
        self,
        existing: Instance | None,
        asset_id: Id,
        version_id: Id,
        channel: Channel,
        workspace_id: Id,
        state: InstanceState,
        *,
        handle_id: str | None = None,
        endpoint: str | None = None,
        error: str | None = None,
        runtime_type: str = "local",
        started: bool = False,
    ) -> None:
        now = self._clock.now()
        async with UnitOfWork(self._db) as uow:
            await InstanceRepository(uow.session).upsert(
                instance_id=existing.id if existing else new_id("instance"),
                workspace_id=workspace_id,
                asset_id=asset_id,
                asset_version_id=version_id,
                channel=channel,
                runtime_type=runtime_type,
                state=state,
                handle_id=handle_id,
                endpoint=endpoint,
                error=error,
                started_at=now if started else (existing.started_at if existing else None),
                stopped_at=None,
            )
            await uow.commit()

    async def _persist_by_id(
        self, instance: Instance, state: InstanceState, *, stopped: bool = False
    ) -> None:
        async with UnitOfWork(self._db) as uow:
            await InstanceRepository(uow.session).upsert(
                instance_id=instance.id,
                workspace_id=instance.workspace_id,
                asset_id=instance.asset_id,
                asset_version_id=instance.asset_version_id,
                channel=instance.channel,
                runtime_type=instance.runtime_type,
                state=state,
                handle_id=None if stopped else instance.handle_id,
                endpoint=None if stopped else instance.endpoint,
                error=None,
                started_at=instance.started_at,
                stopped_at=self._clock.now() if stopped else instance.stopped_at,
            )
            await uow.commit()

    async def _instance_id(self, asset_id: Id, channel: Channel, workspace_id: Id) -> Id:
        return (await self._get_by_channel(asset_id, channel, workspace_id)).id

    async def _get_by_channel(
        self, asset_id: Id, channel: Channel, workspace_id: Id
    ) -> Instance:
        async with UnitOfWork(self._db) as uow:
            instance = await InstanceRepository(uow.session).get_by_channel(
                asset_id, channel, workspace_id
            )
        if instance is None:
            raise NotFound("实例", f"{asset_id}/{channel.value}")
        return instance


def _handle(instance: Instance) -> RuntimeHandle:
    return RuntimeHandle(
        id=instance.handle_id or instance.id,
        asset_version_id=instance.asset_version_id,
        endpoint=instance.endpoint,
    )


def _to_ref(instance: Instance) -> InstanceRef:
    return InstanceRef(
        id=instance.id,
        workspace_id=instance.workspace_id,
        asset_id=instance.asset_id,
        asset_version_id=instance.asset_version_id,
        channel=instance.channel,
        state=instance.state.value,
        runtime_type=instance.runtime_type,
        handle_id=instance.handle_id,
        endpoint=instance.endpoint,
        error=instance.error,
    )

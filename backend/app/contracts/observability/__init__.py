"""可观测性契约。

定义方：消费方（delivery 在 LIVESH→LIVE 晋级时要比对影子与基线的真实指标）。
实现方：observability。

**Score 不在这里**：它是 Trial 的产物，与 Run/Trial 同生命周期，归 execution。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from ..common import Id, TraceOrigin, Window


@dataclass(frozen=True, slots=True)
class VersionMetrics:
    """某个**具体版本**在某个来源下的运行质量。

    口径显式命名——`success_rate` 是调用成功率，不是任务完成率。
    """

    asset_version_id: Id
    origin: TraceOrigin
    trace_count: int
    success_rate: float | None
    p95_latency_ms: int | None
    average_cost_usd: Decimal

    @property
    def has_samples(self) -> bool:
        return self.trace_count > 0


@runtime_checkable
class VersionMetricsPort(Protocol):
    """由 observability 实现；按「版本 + 来源」取指标。

    影子验证要的正是这个切面：候选版本在 `shadow` 下的表现 vs LIVE 版本在
    `production` 下的表现——不是同一个 Agent 的整体平均。
    """

    async def version_metrics(
        self, asset_version_id: Id, origin: TraceOrigin, window: Window
    ) -> VersionMetrics: ...


__all__ = ["VersionMetrics", "VersionMetricsPort"]

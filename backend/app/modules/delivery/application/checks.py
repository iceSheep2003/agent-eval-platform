"""检查项注册表。

每条检查是 `(上下文) -> 结论` 的纯编排逻辑，参数由策略里的 `CheckSpec.params` 传入——
所以「影子样本至少 30 条」这种阈值是**配置**，不是类常量。

新增一种检查 = 写一个函数 + 在 `CHECKS` 注册，然后在策略里引用它的名字。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Awaitable, Callable, Mapping

from ....contracts.asset import AssetQueryPort
from ....contracts.common import Channel, EvaluationStage, Id, TraceOrigin, Window
from ....contracts.errors import DomainError, Errors
from ....contracts.execution import RunQueryPort
from ....contracts.observability import VersionMetricsPort
from ....shared.clock import Clock
from ..domain.lifecycle import CheckName
from ..domain.models import ShadowRoute, next_channel

#: 拿当前生效的影子路由。由 DeliveryService 注入，避免检查项反向依赖用例层。
ShadowRouteLookup = Callable[[], Awaitable[ShadowRoute | None]]


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """检查结论。`rule` 用于填 `blocked_rules`，前端据此展示。"""

    passed: bool
    rule: str
    reason: str | None = None

    @classmethod
    def ok(cls, rule: str) -> "CheckOutcome":
        return cls(passed=True, rule=rule)

    @classmethod
    def blocked(cls, rule: str, reason: str) -> "CheckOutcome":
        return cls(passed=False, rule=rule, reason=reason)


@dataclass(frozen=True, slots=True)
class CheckContext:
    workspace_id: Id
    asset_id: Id
    version_id: Id
    version_label: str
    to_channel: Channel
    params: Mapping[str, Any]
    runs: RunQueryPort
    assets: AssetQueryPort
    metrics: VersionMetricsPort
    clock: Clock
    shadow_route: ShadowRouteLookup


CheckFn = Callable[[CheckContext], Awaitable[CheckOutcome]]


# --------------------------------------------------------------------------- #
# 检查实现
# --------------------------------------------------------------------------- #


async def promotion_gate(ctx: CheckContext) -> CheckOutcome:
    """必须有该版本一次「指定阶段 + 已完成 + 判定通过」的 Run。

    `stage` 默认 release——开发验证的宽松样本不能拿来放行。
    """
    rule_name = CheckName.PROMOTION_GATE.value
    stage = EvaluationStage(ctx.params.get("stage", EvaluationStage.RELEASE.value))
    run = await ctx.runs.find_gate_run(ctx.version_id, stage, ctx.workspace_id)
    if run is None:
        raise DomainError(
            Errors.GATE_BLOCKED,
            f"版本 {ctx.version_label} 没有可用于晋级的评测结果"
            f"（需要一次 {stage.value} 阶段且已完成的运行）",
        )
    if not run.gate_passed:
        return CheckOutcome.blocked(
            rule_name,
            "发布门禁未通过：" + "、".join((run.gate_decision or {}).get("blocked_rules") or ()),
        )
    return CheckOutcome.ok(rule_name)


async def shadow_route(ctx: CheckContext) -> CheckOutcome:
    """影子路由已配置、启用，且候选就是本次要晋级的版本。"""
    rule_name = CheckName.SHADOW_ROUTE.value
    route = await ctx.shadow_route()
    if route is None or not route.enabled:
        return CheckOutcome.blocked(
            rule_name,
            "进入 LIVESH 前需要先配置影子路由（复制多少生产流量、以哪个版本为基线）",
        )
    if route.candidate_version_id != ctx.version_id:
        return CheckOutcome.blocked(
            rule_name, "影子路由指向的是另一个候选版本，请先改为本次要晋级的版本"
        )
    return CheckOutcome.ok(rule_name)


async def shadow_verification(ctx: CheckContext) -> CheckOutcome:
    """候选在**真实分布**下不劣于当前 LIVE 基线。

    比对的是「候选版本在 shadow 下」与「LIVE 版本在 production 下」，
    而不是同一个 Agent 的整体平均——后者会把两个版本混在一起，看不出退化。
    """
    rule_name = CheckName.SHADOW_VERIFICATION.value
    window_days = int(ctx.params.get("window_days", 7))
    min_samples = int(ctx.params.get("min_samples", 30))
    rate_tolerance = float(ctx.params.get("success_rate_tolerance", 0.02))
    latency_tolerance = float(ctx.params.get("latency_tolerance", 0.20))

    route = await ctx.shadow_route()
    if route is None or not route.enabled:
        return CheckOutcome.blocked(rule_name, "没有生效中的影子路由，无法判断影子验证是否通过")
    if route.candidate_version_id != ctx.version_id:
        return CheckOutcome.blocked(rule_name, "影子路由的候选版本与本次晋级版本不一致")

    now = ctx.clock.now()
    window = Window(start=now - timedelta(days=window_days), end=now)
    candidate = await ctx.metrics.version_metrics(ctx.version_id, TraceOrigin.SHADOW, window)
    if candidate.trace_count < min_samples:
        return CheckOutcome.blocked(
            rule_name,
            f"影子样本不足：{candidate.trace_count} < {min_samples}，还不能判断候选是否稳定",
        )

    bindings = await ctx.assets.channel_map(ctx.asset_id, ctx.workspace_id)
    baseline_version_id = route.baseline_version_id or bindings.get(Channel.LIVE)
    # 首次发布：LIVE 还没有版本，没有基线可比。样本门槛已经过了，比对留到第二次起。
    if baseline_version_id is None:
        return CheckOutcome.ok(rule_name)
    baseline = await ctx.metrics.version_metrics(
        baseline_version_id, TraceOrigin.PRODUCTION, window
    )
    if not baseline.has_samples:
        return CheckOutcome.ok(rule_name)

    broken: list[str] = []
    if (
        baseline.success_rate is not None
        and candidate.success_rate is not None
        and candidate.success_rate < baseline.success_rate - rate_tolerance
    ):
        broken.append(f"成功率 {candidate.success_rate:.2%} < 基线 {baseline.success_rate:.2%}")
    if (
        baseline.p95_latency_ms
        and candidate.p95_latency_ms
        and candidate.p95_latency_ms > baseline.p95_latency_ms * (1 + latency_tolerance)
    ):
        broken.append(f"P95 {candidate.p95_latency_ms}ms > 基线 {baseline.p95_latency_ms}ms")
    if broken:
        return CheckOutcome.blocked(rule_name, "影子验证未通过：" + "；".join(broken))
    return CheckOutcome.ok(rule_name)


CHECKS: Mapping[CheckName, CheckFn] = {
    CheckName.PROMOTION_GATE: promotion_gate,
    CheckName.SHADOW_ROUTE: shadow_route,
    CheckName.SHADOW_VERIFICATION: shadow_verification,
}


def check_for(name: CheckName) -> CheckFn:
    fn = CHECKS.get(name)
    if fn is None:
        raise NotImplementedError(f"检查项 {name} 没有实现；请在 CHECKS 里注册")
    return fn


__all__ = [
    "CHECKS",
    "CheckContext",
    "CheckFn",
    "CheckOutcome",
    "ShadowRouteLookup",
    "check_for",
    "next_channel",
]

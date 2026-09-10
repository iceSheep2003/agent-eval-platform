"""检查项注册表。

每条检查是 `(上下文) -> 结论` 的纯编排逻辑，参数由策略里的 `CheckSpec.params` 传入——
所以「影子样本至少 30 条」这种阈值是**配置**，不是类常量。

新增一种检查 = 写一个函数 + 在 `CHECKS` 注册，然后在策略里引用它的名字。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Awaitable, Callable, Literal, Mapping

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


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """一个检查参数的描述。前端据此渲染表单——加检查项不用改界面。"""

    key: str
    label: str
    type: Literal["number", "select", "text"]
    default: Any
    options: tuple[str, ...] = ()
    step: float | None = None
    help: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "options": list(self.options),
            "step": self.step,
            "help": self.help,
        }


@dataclass(frozen=True, slots=True)
class CheckSchema:
    name: CheckName
    label: str
    description: str
    params: tuple[ParamSpec, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "label": self.label,
            "description": self.description,
            "params": [item.as_dict() for item in self.params],
        }


#: 检查项的自描述。策略编辑器读它来渲染表单，**不用在前端写死参数**。
CHECK_SCHEMAS: Mapping[CheckName, CheckSchema] = {
    CheckName.PROMOTION_GATE: CheckSchema(
        name=CheckName.PROMOTION_GATE,
        label="发布门禁",
        description="必须有该版本一次「指定阶段 + 已完成 + 判定通过」的运行",
        params=(
            ParamSpec(
                key="stage",
                label="评测阶段",
                type="select",
                default=EvaluationStage.RELEASE.value,
                options=tuple(item.value for item in EvaluationStage),
                help="只认这个阶段的结果——开发验证的宽松样本不能拿来放行",
            ),
        ),
    ),
    CheckName.SHADOW_ROUTE: CheckSchema(
        name=CheckName.SHADOW_ROUTE,
        label="影子路由已配置",
        description="影子路由必须启用，且候选版本就是本次要晋级的版本",
    ),
    CheckName.SHADOW_VERIFICATION: CheckSchema(
        name=CheckName.SHADOW_VERIFICATION,
        label="影子验证不劣于基线",
        description="候选在真实流量分布下的表现不得明显差于当前 LIVE 版本",
        params=(
            ParamSpec(key="window_days", label="观察窗口（天）", type="number", default=7),
            ParamSpec(key="min_samples", label="最少影子样本", type="number", default=30,
                      help="样本不足时不给结论，避免小样本抖动误伤发布"),
            ParamSpec(key="success_rate_tolerance", label="成功率容差", type="number",
                      default=0.02, step=0.01, help="允许比基线低多少（0.02 = 2 个百分点）"),
            ParamSpec(key="latency_tolerance", label="P95 延迟容差", type="number",
                      default=0.20, step=0.05, help="允许比基线高多少（0.20 = 20%）"),
        ),
    ),
}


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
    "CHECK_SCHEMAS",
    "CheckSchema",
    "ParamSpec",
    "CheckContext",
    "CheckFn",
    "CheckOutcome",
    "ShadowRouteLookup",
    "check_for",
    "next_channel",
]

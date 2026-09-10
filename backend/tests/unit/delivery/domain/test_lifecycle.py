"""治理状态机：策略是数据，不是散在四个文件里的硬编码。

这些测试锁的是「**改配置就能改行为**」这件事——加检查、关检查、调阈值、
换权限点，都不应该需要动 domain / application / api。
"""

from __future__ import annotations

import pytest

from backend.app.contracts.common import Channel
from backend.app.contracts.identity import Permission
from backend.app.modules.delivery.domain.lifecycle import (
    CHANNELS_ASCENDING,
    DEFAULT_POLICY,
    CheckName,
    CheckSpec,
    LifecyclePolicy,
    TransitionRule,
    current_channel,
)


def test_default_policy_is_a_linear_pipeline() -> None:
    """默认只能逐级：TEST → LIVESH → LIVE，没有跳级的边。"""
    assert DEFAULT_POLICY.next_channel(Channel.TEST) is Channel.LIVESH
    assert DEFAULT_POLICY.next_channel(Channel.LIVESH) is Channel.LIVE
    assert DEFAULT_POLICY.next_channel(Channel.LIVE) is None
    # 跳级没有对应的迁移规则
    assert DEFAULT_POLICY.rule_for(Channel.TEST, Channel.LIVE) is None


def test_default_checks_per_transition() -> None:
    """离线验证要门禁 + 影子路由；影子验证要门禁 + 不劣于基线。"""
    to_livesh = DEFAULT_POLICY.rule_for(Channel.TEST, Channel.LIVESH)
    assert to_livesh is not None
    assert [spec.name for spec in to_livesh.enabled_checks()] == [
        CheckName.PROMOTION_GATE,
        CheckName.ASSETS_READY,
        CheckName.SHADOW_ROUTE,
    ]
    assert to_livesh.permission is Permission.VERSION_PROMOTE_LIVESH
    assert to_livesh.requires_reauth is False

    to_live = DEFAULT_POLICY.rule_for(Channel.LIVESH, Channel.LIVE)
    assert to_live is not None
    assert [spec.name for spec in to_live.enabled_checks()] == [
        CheckName.PROMOTION_GATE,
        CheckName.ASSETS_READY,
        CheckName.SHADOW_VERIFICATION,
    ]
    assert to_live.permission is Permission.VERSION_PROMOTE_LIVE
    # 发布到生产必须二次确认
    assert to_live.requires_reauth is True


def test_shadow_thresholds_are_configuration_not_constants() -> None:
    """阈值写在策略里，不是类常量——调它不用改代码。"""
    to_live = DEFAULT_POLICY.rule_for(Channel.LIVESH, Channel.LIVE)
    assert to_live is not None
    spec = next(
        item for item in to_live.checks if item.name is CheckName.SHADOW_VERIFICATION
    )
    assert spec.params["min_samples"] == 30
    assert spec.params["window_days"] == 7
    assert spec.params["success_rate_tolerance"] == 0.02
    assert spec.params["latency_tolerance"] == 0.20


# --------------------------------------------------------------------------- #
# 改配置 → 改行为
# --------------------------------------------------------------------------- #


def test_policy_round_trips_through_json() -> None:
    """策略要能存库再读回来——覆盖配置靠的就是这个。"""
    restored = LifecyclePolicy.from_dict(DEFAULT_POLICY.as_dict())
    assert restored.as_dict() == DEFAULT_POLICY.as_dict()


def test_disabling_a_check_takes_effect() -> None:
    """关掉一个检查就真的不跑它——不用改代码。"""
    payload = DEFAULT_POLICY.as_dict()
    for transition in payload["transitions"]:
        transition["checks"] = [
            {**check, "enabled": check["name"] != CheckName.SHADOW_ROUTE.value}
            for check in transition["checks"]
        ]
    policy = LifecyclePolicy.from_dict(payload)
    to_livesh = policy.rule_for(Channel.TEST, Channel.LIVESH)
    assert to_livesh is not None
    assert [spec.name for spec in to_livesh.enabled_checks()] == [
        CheckName.PROMOTION_GATE,
        CheckName.ASSETS_READY,
    ]


def test_tuning_thresholds_takes_effect() -> None:
    payload = DEFAULT_POLICY.as_dict()
    for transition in payload["transitions"]:
        for check in transition["checks"]:
            if check["name"] == CheckName.SHADOW_VERIFICATION.value:
                check["params"]["min_samples"] = 500
    policy = LifecyclePolicy.from_dict(payload)
    to_live = policy.rule_for(Channel.LIVESH, Channel.LIVE)
    assert to_live is not None
    spec = next(item for item in to_live.checks if item.name is CheckName.SHADOW_VERIFICATION)
    assert spec.params["min_samples"] == 500


def test_permission_can_be_reassigned() -> None:
    """把「谁能发布到 LIVE」收紧成 evaluator，也是一行配置。"""
    payload = DEFAULT_POLICY.as_dict()
    for transition in payload["transitions"]:
        if transition["to_channel"] == Channel.LIVE.value:
            transition["permission"] = Permission.VERSION_PROMOTE_LIVESH.value
    policy = LifecyclePolicy.from_dict(payload)
    to_live = policy.rule_for(Channel.LIVESH, Channel.LIVE)
    assert to_live is not None
    assert to_live.permission is Permission.VERSION_PROMOTE_LIVESH


def test_custom_policy_can_add_a_stage() -> None:
    """加一个 CANARY 中间态 = 多两条边，不动任何代码。"""
    policy = LifecyclePolicy(
        transitions=(
            TransitionRule(
                from_channel=Channel.TEST,
                to_channel=Channel.LIVESH,
                permission=Permission.VERSION_PROMOTE_LIVESH,
                checks=(CheckSpec(CheckName.PROMOTION_GATE),),
            ),
            TransitionRule(
                from_channel=Channel.LIVESH,
                to_channel=Channel.LIVE,
                permission=Permission.VERSION_PROMOTE_LIVE,
                checks=(CheckSpec(CheckName.SHADOW_VERIFICATION),),
            ),
        )
    )
    assert policy.next_channel(Channel.TEST) is Channel.LIVESH
    assert policy.rule_for(Channel.LIVESH, Channel.LIVE) is not None


def test_empty_policy_is_rejected() -> None:
    with pytest.raises(ValueError):
        LifecyclePolicy.from_dict({"transitions": []})


# --------------------------------------------------------------------------- #
# 当前通道
# --------------------------------------------------------------------------- #


def test_current_channel_is_the_highest_one() -> None:
    """晋级到 LIVESH 后版本仍绑在 TEST 上，取高的那个才不会误判成跳级。"""
    bindings = {Channel.TEST: "ver_1", Channel.LIVESH: "ver_1", Channel.LIVE: None}
    assert current_channel("ver_1", bindings) is Channel.LIVESH

    bindings = {Channel.TEST: "ver_1", Channel.LIVESH: None, Channel.LIVE: None}
    assert current_channel("ver_1", bindings) is Channel.TEST


def test_current_channel_is_none_when_unbound() -> None:
    bindings = {channel: None for channel in CHANNELS_ASCENDING}
    assert current_channel("ver_1", bindings) is None


def test_every_check_has_implementation_and_schema() -> None:
    """检查项的三份声明必须一一对应。

    漏一份的后果各不相同：缺实现 → 跑到时才炸；缺 schema → 策略编辑器渲染不出表单，
    用户以为「这项没有参数」。所以在这里一次性锁住。
    """
    from backend.app.modules.delivery.application.checks import CHECKS, CHECK_SCHEMAS

    assert set(CHECK_SCHEMAS) == set(CheckName), "有检查项没写 schema"
    assert set(CHECKS) == set(CheckName), "有检查项没写实现"
    # 默认策略里引用的检查项都得存在
    for transition in DEFAULT_POLICY.transitions:
        for spec in transition.checks:
            assert spec.name in CHECKS


def test_schema_params_match_what_checks_read() -> None:
    """schema 里声明的参数，就是检查实现真正会读的那些。"""
    from backend.app.modules.delivery.application.checks import CHECK_SCHEMAS

    declared = {param.key for param in CHECK_SCHEMAS[CheckName.SHADOW_VERIFICATION].params}
    assert declared == {
        "window_days",
        "min_samples",
        "success_rate_tolerance",
        "latency_tolerance",
    }
    gate = {param.key for param in CHECK_SCHEMAS[CheckName.PROMOTION_GATE].params}
    assert gate == {"stage"}

"""Trial 状态机：合法迁移、非法迁移、终态不可出。

状态错乱不允许被静默接受——写错的迁移路径必须当场炸，而不是落一个错的状态进库。
"""

from __future__ import annotations

import pytest

from backend.app.contracts.common import ExecutionStatus
from backend.app.modules.execution.domain.trial_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    IllegalTransition,
    TrialMachine,
    TrialState,
)


def test_starts_pending_and_records_history() -> None:
    machine = TrialMachine()
    assert machine.state is TrialState.PENDING
    assert machine.path() == "pending"


def test_single_turn_happy_path() -> None:
    machine = TrialMachine()
    for state in (
        TrialState.PROVISIONING,
        TrialState.RUNNING,
        TrialState.SCORING,
        TrialState.SETTLED,
    ):
        machine.to(state)
    assert machine.state is TrialState.SETTLED
    assert machine.path() == "pending → provisioning → running → scoring → settled"


def test_tool_loop_can_repeat_running() -> None:
    machine = TrialMachine()
    machine.to(TrialState.PROVISIONING)
    machine.to(TrialState.RUNNING)
    machine.to(TrialState.RUNNING)
    machine.to(TrialState.RUNNING)
    machine.to(TrialState.SCORING)
    assert machine.state is TrialState.SCORING


@pytest.mark.parametrize(
    "start,forbidden",
    [
        (TrialState.PENDING, TrialState.RUNNING),  # 没起环境就调用
        (TrialState.PENDING, TrialState.SETTLED),  # 没产出就结算
        (TrialState.PROVISIONING, TrialState.SCORING),  # 没调用就评分
        (TrialState.RUNNING, TrialState.SETTLED),  # 没评分就结算
        (TrialState.SCORING, TrialState.RUNNING),  # 评完分不能再调用
    ],
)
def test_illegal_transitions_are_rejected(start: TrialState, forbidden: TrialState) -> None:
    machine = TrialMachine(state=start)
    with pytest.raises(IllegalTransition):
        machine.to(forbidden)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES, key=str))
def test_terminal_states_have_no_exit(terminal: TrialState) -> None:
    machine = TrialMachine(state=terminal)
    assert machine.is_terminal
    assert ALLOWED_TRANSITIONS[terminal] == frozenset()
    # 原地迁移是 no-op，其余一律拒绝
    assert machine.to(terminal) is terminal
    for other in TrialState:
        if other is not terminal:
            with pytest.raises(IllegalTransition):
                machine.to(other)


def test_failure_can_happen_before_provisioning() -> None:
    """版本没有 entrypoint 时还没起环境就失败了。"""
    machine = TrialMachine()
    machine.to(TrialState.FAILED)
    assert machine.storage_status is ExecutionStatus.FAILED


def test_skipped_is_a_terminal_state_not_a_failure() -> None:
    """不支持的协议明确跳过——它跑完了流程，只是没有结论。"""
    machine = TrialMachine()
    machine.to(TrialState.SKIPPED)
    assert machine.is_terminal
    assert machine.storage_status is ExecutionStatus.SUCCEEDED


@pytest.mark.parametrize(
    "state,expected",
    [
        (TrialState.PENDING, ExecutionStatus.PENDING),
        (TrialState.PROVISIONING, ExecutionStatus.RUNNING),
        (TrialState.RUNNING, ExecutionStatus.RUNNING),
        (TrialState.SCORING, ExecutionStatus.RUNNING),
        (TrialState.SETTLED, ExecutionStatus.SUCCEEDED),
        (TrialState.FAILED, ExecutionStatus.FAILED),
        (TrialState.TIMED_OUT, ExecutionStatus.TIMED_OUT),
        (TrialState.CANCELLED, ExecutionStatus.CANCELLED),
    ],
)
def test_storage_mapping(state: TrialState, expected: ExecutionStatus) -> None:
    """更细的状态机映射到给查询用的粗粒度落库状态。"""
    assert TrialMachine(state=state).storage_status is expected


def test_every_state_is_reachable_and_has_a_mapping() -> None:
    from backend.app.modules.execution.domain.trial_machine import STORAGE_STATUS

    assert set(ALLOWED_TRANSITIONS) == set(TrialState)
    assert set(STORAGE_STATUS) == set(TrialState)
    # 除起点外，每个状态都要能从某处到达，否则是死代码
    reachable = {TrialState.PENDING}
    for targets in ALLOWED_TRANSITIONS.values():
        reachable |= targets
    assert reachable == set(TrialState)

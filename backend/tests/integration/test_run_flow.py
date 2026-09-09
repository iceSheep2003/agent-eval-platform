"""M3 验收：创建 Run → Worker 推进 Trial → 评分 → 门禁 → 固化。

覆盖两条硬约束：
1. `expected_output` **不进 Runtime 的 payload**（评分用的东西不能泄漏给被测对象）；
2. `execution_status` 与 `verdict` 正交——「跑完了但没达标」不等于「没跑起来」。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.app.container import Container
from backend.app.contracts.common import (
    Channel,
    DatasetPurpose,
    EvaluationStage,
    ExecutionStatus,
    RunStatus,
    Verdict,
)
from backend.app.contracts.execution import ChannelInvocation
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock
from backend.runtime.worker import Worker

#: 被测函数记录收到的参数——用来断言 payload 里没有 expected_output。
CALLS: list[dict] = []


def echo_agent(input: str) -> str:  # noqa: A002 - 参数名由协议决定
    CALLS.append({"input": input})
    return input


ENTRYPOINT = f"{__name__}:echo_agent"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'run.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _drain(container: Container, rounds: int = 12) -> None:
    """把队列跑到空——run.prepare → trial.execute × N → run.finalize。"""
    worker = Worker(container, [container.execution_handlers], worker_id="test")
    for _ in range(rounds):
        if await worker.run_once() == 0:
            break


async def _scenario(tmp_path) -> None:
    CALLS.clear()
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]

        # 接入 Agent 并冻结一个带 entrypoint 的版本
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="echo-agent",
            connect_type="package",
            source={"artifact_id": "artifact-1", "entrypoint": ENTRYPOINT},
        )
        version = await container.assets.create_version(
            asset_id=agent.id,
            workspace_id=workspace_id,
            created_by=owner,
            spec={
                "kind": "agent",
                "connect_type": "package",
                "artifact_id": "artifact-1",
                "entrypoint": ENTRYPOINT,
            },
        )

        # portal 路径：按通道调用当前绑定的版本
        invoked = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.TEST,  # 注册时自动绑定 TEST
                input="ping",
            )
        )
        assert invoked.error is None
        assert invoked.output == "ping"
        assert invoked.version_label == "0.1.0"

        # 没绑定版本的通道 → 明确报错，而不是静默打别的版本
        from backend.app.contracts.errors import DomainError as _Err

        with pytest.raises(_Err):
            await container.invoke.invoke_channel(
                ChannelInvocation(
                    workspace_id=workspace_id,
                    asset_id=agent.id,
                    channel=Channel.LIVE,
                    input="ping",
                )
            )

        CALLS.clear()  # 上面 portal 的调用也走了同一个函数，先清掉

        # 数据集：2 条样本，一条会通过、一条不会
        dataset = await container.datasets.create_dataset(
            workspace_id=workspace_id,
            owner_id=owner,
            name="回显测试集",
            purpose=DatasetPurpose.GATE,
        )
        outcome = await container.datasets.import_file(
            dataset_id=dataset.id,
            workspace_id=workspace_id,
            actor_id=owner,
            filename="samples.json",
            content=json.dumps(
                [
                    {"input": "hello", "expected_output": "hello"},
                    {"input": "world", "expected_output": "nope"},
                ]
            ).encode(),
        )
        finalized = await container.datasets.finalize_version(outcome.version.id, workspace_id)
        assert finalized.lifecycle == "finalized"

        # 策略：门禁要求 task_success_rate ≥ 0.9（实际会有一半失败）
        template = await container.evaluations.create_template(
            workspace_id=workspace_id,
            created_by=owner,
            name="门禁策略",
            stage=EvaluationStage.RELEASE,
            dataset_version_id=finalized.id,
            evaluator_names=["answer_exact_match"],
            gates={"task_success_rate": 0.9},
        )

        run = await container.runs.create_run(
            workspace_id=workspace_id,
            created_by=owner,
            name="回显评测",
            asset_version_id=version.id,
            dataset_version_id=finalized.id,
            template_id=template.id,
        )
        assert run.status is RunStatus.QUEUED
        assert run.total_trials == 2
        # 冻结的快照里带着门禁，后续改策略不影响这次运行
        assert run.template_snapshot["gates"][0]["metric_key"] == "task_success_rate"

        await _drain(container)

        # Run 完成
        completed = await container.runs.get_run(run.id, workspace_id)
        assert completed.status is RunStatus.COMPLETED

        trials = await container.runs.list_trials(run.id, workspace_id)
        assert len(trials) == 2
        assert all(item.execution_status is ExecutionStatus.SUCCEEDED for item in trials)
        assert {item.verdict for item in trials} == {Verdict.PASS, Verdict.FAIL}

        # **expected_output 没有进 payload**
        assert CALLS and all(set(call) == {"input"} for call in CALLS)
        assert {call["input"] for call in CALLS} == {"hello", "world"}

        # 分数按 trial 落库
        scores = await container.runs.list_scores(run.id, workspace_id)
        assert len(scores) == 2
        assert {item.status for item in scores} == {"pass", "fail"}

        # 固化结果 + 门禁判定：通过率 0.5 < 0.9 → 阻断
        result = await container.runs.get_result(run.id, workspace_id)
        assert result is not None
        assert result.pass_rate == 0.5
        assert result.trial_counts == {"succeeded": 2}
        assert result.verdict_counts == {"pass": 1, "fail": 1}
        assert result.gate_decision is not None
        assert result.gate_decision["passed"] is False
        assert result.gate_decision["blocked_rules"] == ["task_success_rate"]

        # 终态后不允许再控制
        from backend.app.contracts.errors import DomainError

        with pytest.raises(DomainError):
            await container.runs.control(run.id, workspace_id, "pause")

        # 重复投递不产生重复 Trial（幂等）
        await _drain(container)
        assert len(await container.runs.list_trials(run.id, workspace_id)) == 2

        # 回流：把失败的那条沉淀为回归样本
        regression = await container.datasets.create_dataset(
            workspace_id=workspace_id,
            owner_id=owner,
            name="回归集",
            purpose=DatasetPurpose.REGRESSION,
        )
        failed = next(item for item in trials if item.verdict is Verdict.FAIL)
        trial_ref = await container.runs.get_trial_ref(failed.id, workspace_id)
        assert trial_ref is not None and trial_ref.verdict is Verdict.FAIL

        item = await container.datasets.append_regression_sample(
            dataset_id=regression.id,
            workspace_id=workspace_id,
            actor_id=owner,
            trial=trial_ref,
            reason="生产失败复现",
        )
        # 没有标准答案 → 必须人工复核，不能直接进固化版本
        assert item.validation.value == "needs_review"
        assert item.task.instruction == "world"
        assert item.private is None
        assert item.raw["trial_id"] == failed.id

        # 去重：同一条失败反复沉淀只留一条
        again = await container.datasets.append_regression_sample(
            dataset_id=regression.id,
            workspace_id=workspace_id,
            actor_id=owner,
            trial=trial_ref,
        )
        assert again.id == item.id
        items, total = await container.datasets.list_items(
            item.dataset_version_id, workspace_id
        )
        assert total == 1

        # 有待复核样本时不能固化——正是这条约束挡住了「未确认的样本进回归集」
        from backend.app.contracts.errors import DomainError as _DomainError

        with pytest.raises(_DomainError):
            await container.datasets.finalize_version(item.dataset_version_id, workspace_id)
    finally:
        await container.shutdown()


def test_run_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

"""记忆：分区、检索、注入、以及**不串味**。

记忆最容易出的不是「存不下」，是**串**：把别人的会话、别的租户、甚至旧版本的
上下文读出来。所以这里的断言围绕分区展开。
"""

from __future__ import annotations

import asyncio

from backend.app.container import Container
from backend.app.contracts.common import Channel
from backend.app.contracts.execution import ChannelInvocation
from backend.app.contracts.memory import MemoryKey, MemoryTurn
from backend.app.modules.memory.application.services import MemoryService
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

#: 记录 Agent 从 `memory` 形参里读到了什么。
SEEN: dict[str, list[str]] = {}

ENTRYPOINT = f"{__name__}:remembering_agent"


async def remembering_agent(input: str, memory=None) -> str:  # noqa: A002
    """**用收窄后的接口**读历史——Agent 不知道也改不了分区键。

    把历史贴进 SEEN，测试据此断言注入的是哪一片记忆。
    """
    history = await memory.recent(limit=10) if memory else []
    SEEN["history"] = [f"{turn.role}:{turn.content}" for turn in history]
    if memory:
        await memory.remember(role="user", content=input)
    return f"见过 {len(history)} 轮"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'mem.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]

        # -- 1. 分区：同一版本，不同会话互不可见 ---------------------------
        service = MemoryService(container.database, clock, workspace_id=workspace_id)
        version_id = "ver_1"
        thread_a = MemoryKey(agent_version_id=version_id, thread_id="th_a", scope="thread")
        thread_b = MemoryKey(agent_version_id=version_id, thread_id="th_b", scope="thread")

        await service.remember_turns(
            thread_a, [MemoryTurn(role="user", content="订单 A001 能退款吗")]
        )
        assert len(await service.recent_turns(thread_a)) == 1
        assert await service.recent_turns(thread_b) == [], "不同会话之间不能互相看见"

        # -- 2. 分区：同会话，不同版本互不可见（换版本 = 换记忆）-----------
        other_version = MemoryKey(
            agent_version_id="ver_2", thread_id="th_a", scope="thread"
        )
        assert await service.recent_turns(other_version) == [], "不同版本之间不能互相看见"

        # -- 3. 分区：不同租户互不可见 ------------------------------------
        tenant_x = MemoryKey(
            agent_version_id=version_id, thread_id="th_a", tenant_id="tn_x", scope="thread"
        )
        assert await service.recent_turns(tenant_x) == [], "不同租户之间不能互相看见"

        # -- 4. 轮次保序 --------------------------------------------------
        await service.remember_turns(
            thread_a,
            [
                MemoryTurn(role="assistant", content="可以退款"),
                MemoryTurn(role="user", content="几天内要申请"),
            ],
        )
        turns = await service.recent_turns(thread_a)
        assert [t.role for t in turns] == ["user", "assistant", "user"]
        assert turns[-1].content == "几天内要申请"

        # -- 5. 事实检索：相关的排前面，无关的不返回 ----------------------
        await service.remember_fact(thread_a, "order:A001", "订单 A001 已发货，金额 249 元")
        await service.remember_fact(thread_a, "order:A002", "订单 A002 已退款")
        hits = await service.recall_facts(thread_a, "A001 的退款情况")
        assert hits and hits[0].key == "order:A001", [h.key for h in hits]
        assert await service.recall_facts(thread_a, "今天天气怎么样") == []

        # -- 6. 注入：Agent 声明了 memory 形参就能拿到句柄 ------------------
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="memory-agent",
            connect_type="package",
            source={
                "artifact_id": "a-1",
                "entrypoint": ENTRYPOINT,
                "memory": {"scope": "thread"},
                "secrets": [],
            },
        )
        version = (await container.assets.list_versions(agent.id, workspace_id))[0]
        for channel in (Channel.TEST, Channel.LIVE):
            await container.assets.bind_channel(
                asset_id=agent.id,
                channel=channel,
                version_id=version.id,
                workspace_id=workspace_id,
                actor_id=owner,
            )

        # 先给这个版本 + 会话埋两轮历史
        bound_key = MemoryKey(
            agent_version_id=version.id, thread_id="th_live", scope="thread"
        )
        await service.remember_turns(
            bound_key,
            [
                MemoryTurn(role="user", content="我叫小明"),
                MemoryTurn(role="assistant", content="你好小明"),
            ],
        )

        result = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.LIVE,
                input="我是谁",
                thread_id="th_live",
            )
        )
        assert result.error is None, result.error
        assert result.output == "见过 2 轮", result.output
        assert SEEN["history"] == ["user:我叫小明", "assistant:你好小明"]

        # -- 7. 换个会话就看不到上一条会话的历史 ---------------------------
        fresh = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.LIVE,
                input="我是谁",
                thread_id="th_another",
            )
        )
        assert fresh.output == "见过 0 轮", fresh.output

        # -- 8. forget 只清自己那一片 --------------------------------------
        # 3 = 预埋的 2 轮 + 上面那次调用里 Agent 自己 remember 的 1 轮
        removed = await service.forget(bound_key)
        assert removed == 3
        assert await service.recent_turns(bound_key) == []
        assert len(await service.recent_turns(thread_a)) == 3, "别片不能被误伤"
    finally:
        await container.shutdown()


def test_memory_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

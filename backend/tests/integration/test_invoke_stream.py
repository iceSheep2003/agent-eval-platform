"""流式调用：真增量、退化兼容、以及失败时的收尾。

三条容易被写错的事：
1. 异步生成器 entrypoint 要**逐段**产出，而不是攒完再吐；
2. 普通函数 entrypoint 退化成**一段**，调用方不必区分；
3. 流到一半失败时，已经吐出去的字**不能丢**。
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.container import Container
from backend.app.contracts.common import Channel
from backend.app.contracts.execution import ChannelInvocation
from backend.app.main import create_app
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

PIECES = ["退款", "政策", "：7 天内。"]


async def streaming_agent(input: str):  # noqa: A002 - 参数名由协议决定
    """异步生成器 entrypoint —— 平台应当逐段下发。"""
    for piece in PIECES:
        await asyncio.sleep(0)
        yield piece


def plain_agent(input: str) -> str:  # noqa: A002
    """普通函数 entrypoint —— 应当退化成一段。"""
    return f"echo:{input}"


async def broken_stream_agent(input: str):  # noqa: A002
    """吐两段之后炸掉——已产出的字必须跟着 error 一起送出去。"""
    yield "已经说了一半"
    raise RuntimeError("模型连接断了")


STREAMING = f"{__name__}:streaming_agent"
PLAIN = f"{__name__}:plain_agent"
BROKEN = f"{__name__}:broken_stream_agent"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'stream.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _bind(container: Container, workspace_id: str, owner: str, entrypoint: str):
    agent = await container.assets.register_agent(
        workspace_id=workspace_id,
        owner_id=owner,
        name=f"agent-{entrypoint.rsplit(':', 1)[-1]}",
        connect_type="package",
        source={"artifact_id": "a-1", "entrypoint": entrypoint},
    )
    version = (await container.assets.list_versions(agent.id, workspace_id))[0]
    await container.assets.bind_channel(
        asset_id=agent.id,
        channel=Channel.LIVE,
        version_id=version.id,
        workspace_id=workspace_id,
        actor_id=owner,
    )
    return agent


async def _deltas(container: Container, agent_id: str, workspace_id: str) -> list[str]:
    request = ChannelInvocation(
        workspace_id=workspace_id,
        asset_id=agent_id,
        channel=Channel.LIVE,
        input="问",
    )
    out: list[str] = []
    async for event in container.invoke.stream_channel(request):
        if event.delta:
            out.append(event.delta)
    return out


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]

        # -- 1. 异步生成器：逐段产出 --------------------------------------
        streaming = await _bind(container, workspace_id, owner, STREAMING)
        assert await _deltas(container, streaming.id, workspace_id) == PIECES

        # -- 2. 普通函数：退化成一段 --------------------------------------
        plain = await _bind(container, workspace_id, owner, PLAIN)
        assert await _deltas(container, plain.id, workspace_id) == ["echo:问"]

        # -- 3. 中途失败：已产出的字要带在 error 事件里 --------------------
        broken = await _bind(container, workspace_id, owner, BROKEN)
        request = ChannelInvocation(
            workspace_id=workspace_id,
            asset_id=broken.id,
            channel=Channel.LIVE,
            input="问",
        )
        deltas: list[str] = []
        error: str | None = None
        async for event in container.invoke.stream_channel(request):
            if event.delta:
                deltas.append(event.delta)
            if event.error:
                error = event.error
        assert deltas == ["已经说了一半"]
        assert error is not None and "模型连接断了" in error

        # -- 4. 非流式调用同样支持异步生成器：拼回完整输出 -----------------
        result = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=streaming.id,
                channel=Channel.LIVE,
                input="问",
            )
        )
        assert result.error is None
        assert result.output == "".join(PIECES)

        # -- 5. 端到端：SSE 分块是**多段**，不是攒完一次吐 -----------------
        app = create_app(container)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/login", json={"identifier": "admin", "password": "admin123"}
            )
            await client.post(
                "/api/portal-admin/users",
                json={"username": "dora", "display_name": "Dora", "password": "portal-pass-123"},
            )
            hub = (
                await client.post(
                    "/api/portal-admin/hubs", json={"slug": "s", "name": "流式门户"}
                )
            ).json()["data"]
            user_id = (
                await client.get("/api/portal-admin/users")
            ).json()["data"]["items"][0]["id"]
            await client.post(
                f"/api/portal-admin/hubs/{hub['id']}/members",
                json={"portal_user_id": user_id, "role": "owner"},
            )
            portal_agent = (
                await client.post(
                    f"/api/portal-admin/hubs/{hub['id']}/agents",
                    json={"asset_id": streaming.id},
                )
            ).json()["data"]

            credential = (
                await client.post(
                    f"/api/agents/{streaming.id}/deployment-keys",
                    json={"channel": "live"},
                )
            ).json()["data"]["id"]
            await client.post(
                f"/api/portal-admin/agents/{portal_agent['id']}/channels/live/bind",
                json={"deployment_credential_id": credential},
            )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
            await portal.post(
                "/api/portal/auth/login",
                json={"identifier": "dora", "password": "portal-pass-123"},
            )
            contents: list[str] = []
            async with portal.stream(
                "POST",
                f"/api/portal/hubs/{hub['id']}/agents/{portal_agent['id']}"
                f"/channels/live/chat",
                json={"messages": [{"role": "user", "content": "问"}], "stream": True},
            ) as response:
                assert response.status_code == 200
                event = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and line != "data: [DONE]":
                        payload = line[6:]
                        if event == "error":
                            continue
                        import json as _json

                        delta = _json.loads(payload)["choices"][0]["delta"].get("content")
                        if delta:
                            contents.append(delta)
            assert contents == PIECES, f"SSE 应当是逐段下发，实际拿到 {contents}"
    finally:
        await container.shutdown()


def test_invoke_stream(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

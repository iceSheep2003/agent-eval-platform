"""展示平台端到端：运营供给 → 外部用户登录 → 切通道 → 对话。

覆盖四条硬约束：
1. 非成员拿不到门户（404，不是 403——不给门户枚举留缝）；
2. 通道列表恒为三条，LIVESH 带「影子预览」提示；
3. 对话走的是**该通道绑定的版本**，且线格式是 OpenAI 兼容 SSE；
4. 撤销部署凭证后对话立刻失效——portal 只存凭证引用，不存密钥。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from backend.app.container import Container
from backend.app.contracts.common import Channel, CredentialKind
from backend.app.main import create_app
from backend.app.modules.portal.application.services import CHAT_LIMIT_PER_MINUTE
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def echo_agent(input: str) -> str:  # noqa: A002 - 参数名由协议决定
    return f"echo:{input}"


def shadow_agent(input: str) -> str:  # noqa: A002
    return f"shadow:{input}"


ECHO = f"{__name__}:echo_agent"
SHADOW = f"{__name__}:shadow_agent"

PORTAL_PASSWORD = "portal-pass-123"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'portal.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _sse_lines(client: httpx.AsyncClient, url: str, payload: dict) -> list[str]:
    lines: list[str] = []
    async with client.stream("POST", url, json=payload) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            lines.append(line)
    return lines


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]

        # 被测 Agent：一个带 entrypoint 的版本
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="portal-agent",
            connect_type="package",
            source={"artifact_id": "artifact-1", "entrypoint": ECHO},
        )
        version = (await container.assets.list_versions(agent.id, workspace_id))[0]
        shadow = await container.assets.create_version(
            asset_id=agent.id,
            workspace_id=workspace_id,
            created_by=owner,
            spec={
                "kind": "agent",
                "connect_type": "package",
                "artifact_id": "artifact-2",
                "entrypoint": SHADOW,
            },
        )

        app = create_app(container)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # -- 运营侧：平台账号登录 ---------------------------------------
            login = await client.post(
                "/api/auth/login", json={"identifier": "admin", "password": "admin123"}
            )
            assert login.status_code == 200, login.text

            # -- 供给：建 portal 账号 / 门户 / 成员 / 挂 Agent / 签发密钥 ------
            created_user = await client.post(
                "/api/portal-admin/users",
                json={
                    "username": "alice",
                    "display_name": "Alice",
                    "password": PORTAL_PASSWORD,
                },
            )
            assert created_user.status_code == 200, created_user.text
            alice_id = created_user.json()["data"]["id"]

            created_hub = await client.post(
                "/api/portal-admin/hubs",
                json={"slug": "support", "name": "客服门户"},
            )
            assert created_hub.status_code == 200, created_hub.text
            hub_id = created_hub.json()["data"]["id"]

            member = await client.post(
                f"/api/portal-admin/hubs/{hub_id}/members",
                json={"portal_user_id": alice_id, "role": "owner"},
            )
            assert member.status_code == 200, member.text

            attached = await client.post(
                f"/api/portal-admin/hubs/{hub_id}/agents",
                json={"asset_id": agent.id},
            )
            assert attached.status_code == 200, attached.text
            portal_agent_id = attached.json()["data"]["id"]

            # 把 LIVE 绑到一个有 entrypoint 的版本
            bound = await client.post(
                f"/api/agents/{agent.id}/channels/live/bind",
                json={"version_id": version.id},
            )
            assert bound.status_code == 200, bound.text

            live_key = await client.post(
                f"/api/agents/{agent.id}/deployment-keys",
                json={"channel": "live"},
            )
            assert live_key.status_code == 200, live_key.text
            credential_id = live_key.json()["data"]["id"]

            wired = await client.post(
                f"/api/portal-admin/agents/{portal_agent_id}/channels/live/bind",
                json={"deployment_credential_id": credential_id},
            )
            assert wired.status_code == 200, wired.text

            # 影子通道也配一把密钥，绑到影子版本
            await container.assets.bind_channel(
                asset_id=agent.id,
                channel=Channel.LIVESH,
                version_id=shadow.id,
                workspace_id=workspace_id,
                actor_id=owner,
            )
            shadow_key = await client.post(
                f"/api/agents/{agent.id}/deployment-keys",
                json={"channel": "livesh"},
            )
            shadow_credential_id = shadow_key.json()["data"]["id"]
            await client.post(
                f"/api/portal-admin/agents/{portal_agent_id}/channels/livesh/bind",
                json={"deployment_credential_id": shadow_credential_id},
            )

            # 非成员：bob 不属于任何门户
            await client.post(
                "/api/portal-admin/users",
                json={
                    "username": "bob",
                    "display_name": "Bob",
                    "password": PORTAL_PASSWORD,
                },
            )

            # -- 外部用户：登录 --------------------------------------------
            portal_login = await client.post(
                "/api/portal/auth/login",
                json={"identifier": "alice", "password": PORTAL_PASSWORD},
            )
            assert portal_login.status_code == 200, portal_login.text
            assert portal_login.json()["data"]["hubs"][0]["slug"] == "support"

            # -- 通道列表：恒三条，LIVESH 带提示 ----------------------------
            agents = await client.get(f"/api/portal/hubs/{hub_id}/agents")
            assert agents.status_code == 200, agents.text
            items = agents.json()["data"]["items"]
            assert len(items) == 1
            channels = {item["channel"]: item for item in items[0]["channels"]}
            assert set(channels) == {"test", "livesh", "live"}
            assert channels["live"]["bound"] is True
            assert channels["live"]["version_label"] == version.version_label
            assert channels["livesh"]["notice"] == "影子预览 · 未返回真实用户"
            assert channels["test"]["notice"] is None

            # -- 对话：打的是通道绑定的版本 --------------------------------
            chat = await client.post(
                f"/api/portal/hubs/{hub_id}/agents/{portal_agent_id}"
                f"/channels/live/chat",
                json={"message": "你好"},
            )
            assert chat.status_code == 200, chat.text
            body = chat.json()["data"]
            assert body["choices"][0]["message"]["content"] == "echo:你好"
            assert body["version"] == version.version_label

            shadow_chat = await client.post(
                f"/api/portal/hubs/{hub_id}/agents/{portal_agent_id}"
                f"/channels/livesh/chat",
                json={"message": "你好"},
            )
            assert shadow_chat.json()["data"]["choices"][0]["message"]["content"] == (
                "shadow:你好"
            )
            assert shadow_chat.json()["data"]["notice"] == "影子预览 · 未返回真实用户"

            # -- 流式：OpenAI 兼容分块 --------------------------------------
            lines = await _sse_lines(
                client,
                f"/api/portal/hubs/{hub_id}/agents/{portal_agent_id}"
                f"/channels/livesh/chat",
                {"message": "你好", "stream": True},
            )
            data_lines = [line for line in lines if line.startswith("data: ")]
            first = json.loads(data_lines[0][6:])
            assert first["choices"][0]["delta"]["role"] == "assistant"
            assert data_lines[-1] == "data: [DONE]"
            contents = "".join(
                json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                for line in data_lines[1:-1]
            )
            assert contents == "shadow:你好"

            # -- 限流：超过每分钟上限后 429，而不是把执行面打满 ----------------
            chat_path = (
                f"/api/portal/hubs/{hub_id}/agents/{portal_agent_id}"
                f"/channels/live/chat"
            )
            codes = [chat.status_code]
            for _ in range(CHAT_LIMIT_PER_MINUTE + 2):
                codes.append(
                    (await client.post(chat_path, json={"message": "hi"})).status_code
                )
                if codes[-1] == 429:
                    break
            assert codes[-1] == 429, f"没有触发限流：{codes}"
            assert codes.count(429) == 1, "限流后应持续拒绝，而不是偶尔放行"

            # -- 审计：登录、供给、对话都留痕 --------------------------------
            audit = await client.get("/api/portal-admin/audit?limit=200")
            assert audit.status_code == 200, audit.text
            actions = {item["action"] for item in audit.json()["data"]["items"]}
            assert {
                "portal.login",
                "portal.chat",
                "portal_admin.user.create",
                "portal_admin.hub.create",
                "portal_admin.member.add",
                "portal_admin.agent.attach",
                "portal_admin.channel.bind",
            } <= actions, actions

            # -- 非成员：404 而不是 403 -------------------------------------
            await client.post("/api/portal/auth/logout")
            bob_login = await client.post(
                "/api/portal/auth/login",
                json={"identifier": "bob", "password": PORTAL_PASSWORD},
            )
            assert bob_login.status_code == 200
            forbidden = await client.get(f"/api/portal/hubs/{hub_id}")
            assert forbidden.status_code == 404

        # -- 撤销凭证 → 对话失效 -------------------------------------------
        # 先把限流窗口推过去，否则这里会先撞 429 而不是我们想验的 401
        clock.advance(seconds=61)
        await container.assets.revoke_credential(credential_id, workspace_id)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/api/portal/auth/login",
                json={"identifier": "alice", "password": PORTAL_PASSWORD},
            )
            broken = await client.post(
                f"/api/portal/hubs/{hub_id}/agents/{portal_agent_id}"
                f"/channels/live/chat",
                json={"message": "你好"},
            )
            # 网关侧解析不到可用密钥 → 401
            assert broken.status_code == 401, broken.text
    finally:
        await container.shutdown()


def test_portal_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

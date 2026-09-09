"""按通道调用（网关 / 展示平台对话）的验收。

覆盖四件容易写错的事：
1. 通道没绑版本 → `channel_unbound`(409)，不是 500；
2. 绑了 `sdk` 版本（无 entrypoint）→ 422，不是 500；
3. 每次调用落一条 Trace，`ingested_via="gateway"`，且 origin 随通道变化；
4. 部署密钥**限定通道**——拿 LIVE 的密钥打 TEST 必须被拒。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.container import Container
from backend.app.contracts.common import Channel, CredentialKind, TraceOrigin
from backend.app.contracts.errors import DomainError, Errors
from backend.app.contracts.execution import ChannelInvocation
from backend.app.main import create_app
from backend.app.modules.observability.application.services import TraceQuery
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

CALLS: list[dict] = []


def echo_agent(input: str) -> str:  # noqa: A002 - 参数名由协议决定
    CALLS.append({"input": input})
    return f"echo:{input}"


def shadow_agent(input: str) -> str:  # noqa: A002
    return f"shadow:{input}"


ECHO = f"{__name__}:echo_agent"
SHADOW = f"{__name__}:shadow_agent"


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'invoke.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _register(container: Container, workspace_id: str, owner: str):
    agent = await container.assets.register_agent(
        workspace_id=workspace_id,
        owner_id=owner,
        name="echo-agent",
        connect_type="package",
        source={"artifact_id": "artifact-1", "entrypoint": ECHO},
    )
    return agent


async def _traces(container: Container, workspace_id: str, asset_id: str):
    items, _ = await container.traces.list_traces(
        workspace_id, TraceQuery(asset_id=asset_id), None
    )
    return list(items)


async def _scenario(tmp_path) -> None:
    CALLS.clear()
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        agent = await _register(container, workspace_id, owner)

        # -- 1. 接入即绑定 TEST；LIVESH / LIVE 未绑定 -----------------------
        states = await container.assets.channel_states(agent.id, workspace_id)
        assert states[Channel.TEST].version_id is not None
        assert states[Channel.LIVESH].version_id is None

        with pytest.raises(DomainError) as unbound:
            await container.invoke.invoke_channel(
                ChannelInvocation(
                    workspace_id=workspace_id,
                    asset_id=agent.id,
                    channel=Channel.LIVESH,
                    input="hi",
                )
            )
        assert unbound.value.error is Errors.CHANNEL_UNBOUND

        # -- 2. 打 TEST：拿到输出，且落一条 evaluation Trace ---------------
        invoked = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.TEST,
                input="ping",
            )
        )
        assert invoked.error is None
        assert invoked.output == "echo:ping"
        assert invoked.trace_id is not None

        recorded = await _traces(container, workspace_id, agent.id)
        assert len(recorded) == 1
        assert recorded[0].ingested_via == "gateway"
        assert recorded[0].origin is TraceOrigin.EVALUATION
        assert recorded[0].channel is Channel.TEST

        # -- 3. 把影子版本绑到 LIVESH：origin 变成 shadow -------------------
        shadow_version = await container.assets.create_version(
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
        await container.assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.LIVESH,
            version_id=shadow_version.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )
        shadow = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.LIVESH,
                input="ping",
            )
        )
        assert shadow.output == "shadow:ping"

        recorded = await _traces(container, workspace_id, agent.id)
        by_origin = {item.origin: item for item in recorded}
        assert by_origin[TraceOrigin.SHADOW].channel is Channel.LIVESH

        # -- 4. 绑一个没有 entrypoint 的 sdk 版本 → 422 而不是 500 ---------
        sdk_version = await container.assets.create_version(
            asset_id=agent.id,
            workspace_id=workspace_id,
            created_by=owner,
            spec={"kind": "agent", "connect_type": "sdk"},
        )
        await container.assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.LIVE,
            version_id=sdk_version.id,
            workspace_id=workspace_id,
            bound_by=owner,
        )
        with pytest.raises(DomainError) as not_invokable:
            await container.invoke.invoke_channel(
                ChannelInvocation(
                    workspace_id=workspace_id,
                    asset_id=agent.id,
                    channel=Channel.LIVE,
                    input="hi",
                )
            )
        assert not_invokable.value.error is Errors.RUN_SUBJECT_INCOMPLETE
        assert not_invokable.value.http_status == 422

        # -- 5. 网关鉴权：密钥限定通道、跨 Agent、已吊销 --------------------
        key = await container.assets.mint_credential(
            workspace_id=workspace_id,
            kind=CredentialKind.DEPLOY,
            asset_id=agent.id,
            channel=Channel.TEST,
        )
        app = create_app(container)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ok_response = await client.post(
                f"/v1/agents/{agent.id}/invoke",
                headers={"Authorization": f"Bearer {key.secret}"},
                json={"input": "hi", "channel": "test"},
            )
            assert ok_response.status_code == 200, ok_response.text
            body = ok_response.json()["data"]
            assert body["output"] == "echo:hi"
            assert body["channel"] == "test"

            # 密钥限定 TEST，打 LIVESH 必须被拒
            crossed = await client.post(
                f"/v1/agents/{agent.id}/invoke",
                headers={"Authorization": f"Bearer {key.secret}"},
                json={"input": "hi", "channel": "liversh"},
            )
            assert crossed.status_code == 403
            assert crossed.json()["errorCode"] == Errors.CREDENTIAL_SCOPE_VIOLATION.code

            # 别的密钥前缀不接受
            wrong_prefix = await client.post(
                f"/v1/agents/{agent.id}/invoke",
                headers={"Authorization": "Bearer evk_not-a-deploy-key"},
                json={"input": "hi", "channel": "test"},
            )
            assert wrong_prefix.status_code == 403

        await container.assets.revoke_credential(key.credential.id, workspace_id)
        assert await container.assets.resolve_credential(key.secret) is None

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            after_revoke = await client.post(
                f"/v1/agents/{agent.id}/invoke",
                headers={"Authorization": f"Bearer {key.secret}"},
                json={"input": "hi", "channel": "test"},
            )
            assert after_revoke.status_code == 401
            assert after_revoke.json()["errorCode"] == Errors.CREDENTIAL_EXPIRED.code
    finally:
        await container.shutdown()


def test_invoke_channel(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))


def test_sandbox_filters_payload_by_signature() -> None:
    """多传的 `messages` 不能把单参数 entrypoint 打挂。"""
    from backend.app.runtime_adapters.local_sandbox import _public_arguments

    assert _public_arguments(echo_agent, {"input": "x", "messages": [{"a": 1}]}) == {
        "input": "x"
    }

    def takes_kwargs(**kwargs):  # noqa: ANN003
        return kwargs

    assert _public_arguments(takes_kwargs, {"input": "x", "extra": 1}) == {
        "input": "x",
        "extra": 1,
    }

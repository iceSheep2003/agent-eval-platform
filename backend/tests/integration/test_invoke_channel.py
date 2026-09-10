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
    """接入 Agent。返回 (asset, 首个版本)——新冻结的版本会自动成为 TEST 候选。"""
    agent = await container.assets.register_agent(
        workspace_id=workspace_id,
        owner_id=owner,
        name="echo-agent",
        connect_type="package",
        source={"artifact_id": "artifact-1", "entrypoint": ECHO, "memory": {"scope": "stateless"}},
    )
    versions = await container.assets.list_versions(agent.id, workspace_id)
    return agent, versions[0]


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
        agent, first_version = await _register(container, workspace_id, owner)

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
                "memory": {"scope": "stateless"},
            },
        )
        await container.assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.LIVESH,
            version_id=shadow_version.id,
            workspace_id=workspace_id,
            actor_id=owner,
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
            spec={"kind": "agent", "connect_type": "sdk", "memory": {"scope": "stateless"}},
        )
        await container.assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.LIVE,
            version_id=sdk_version.id,
            workspace_id=workspace_id,
            actor_id=owner,
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
        # 上面冻结的 sdk 版本把 TEST 指针带走了（新版本即 TEST 候选），
        # 这里指回有 entrypoint 的版本，否则测的是「无 entrypoint」那条分支。
        await container.assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.TEST,
            version_id=first_version.id,
            workspace_id=workspace_id,
            actor_id=owner,
        )
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
                json={"input": "hi", "channel": "livesh"},
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


async def _tree_scenario(tmp_path) -> None:
    """调用树：编排调子 Agent 时，两次调用必须连成一棵树。

    断链的后果不是「难看」，是拿不到系统级指标：整棵子树的总成本、总成功率、
    「子 Agent 失败到底是它自己的问题还是编排喂错了输入」都无从判断。
    """
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        agent, _ = await _register(container, workspace_id, owner)

        # 父调用（模拟编排自己那次）
        parent = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.TEST,
                input="编排的输入",
            )
        )
        assert parent.invocation_id, "调用结果必须回传自己的 invocation_id"

        # 子调用：挂上父 id
        child = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.TEST,
                input="子任务",
                parent_invocation_id=parent.invocation_id,
            )
        )
        assert child.invocation_id != parent.invocation_id

        events, _ = await container.traces.list_traces(
            workspace_id, TraceQuery(asset_id=agent.id), None
        )
        by_external = {item.external_trace_id: item for item in events}
        parent_trace = by_external[f"gw-{parent.invocation_id}"]
        child_trace = by_external[f"gw-{child.invocation_id}"]

        assert parent_trace.parent_invocation_id is None
        # 存的是**调用方传进来的那个 id**（不做惊喜变换），
        # 与父 Trace 的对应关系是确定性的：`external_trace_id == f"gw-{parent_invocation_id}"`。
        assert child_trace.parent_invocation_id == parent.invocation_id
        assert parent_trace.external_trace_id == f"gw-{child_trace.parent_invocation_id}"

        # 整棵子树可以这样一次查出来（编排拿它算系统级成本/成功率）
        subtree = [
            item
            for item in events
            if f"gw-{item.parent_invocation_id}" == parent_trace.external_trace_id
        ]
        assert len(subtree) == 1
    finally:
        await container.shutdown()


def test_invocation_tree_is_linked(tmp_path) -> None:
    asyncio.run(_tree_scenario(tmp_path))


RECEIVED: dict[str, object] = {}


def structured_agent(input: object) -> str:  # noqa: A002
    """把收到的 input **原样**留档——用来断言它没有被序列化成字符串。"""
    RECEIVED["input"] = input
    return f"type={type(input).__name__}"


async def _structured_scenario(tmp_path) -> None:
    """结构化输入必须**原样**到达 Agent。

    编排时上游产出的是对象；若中途被序列化成 JSON 文本，下游就得重新解析一遍，
    字段类型与嵌套结构全丢——这正是多 Agent 组合最先坏掉的地方。
    """
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        owner = seeded["admin"]
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner,
            name="structured-agent",
            connect_type="package",
            source={
                "artifact_id": "a-1",
                "entrypoint": f"{__name__}:structured_agent",
                "memory": {"scope": "stateless"},
            },
        )
        version = (await container.assets.list_versions(agent.id, workspace_id))[0]
        await container.assets.bind_channel(
            asset_id=agent.id,
            channel=Channel.LIVE,
            version_id=version.id,
            workspace_id=workspace_id,
            actor_id=owner,
        )

        payload = {"order": {"id": "A001", "amount": 249.0}, "flags": ["vip"]}
        result = await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.LIVE,
                input=payload,
            )
        )
        assert result.error is None, result.error
        assert RECEIVED["input"] == payload, "结构化输入应当原样到达，而不是 JSON 文本"
        assert isinstance(RECEIVED["input"], dict)

        # 字符串仍然照常工作（简写形式）
        await container.invoke.invoke_channel(
            ChannelInvocation(
                workspace_id=workspace_id,
                asset_id=agent.id,
                channel=Channel.LIVE,
                input="纯文本",
            )
        )
        assert RECEIVED["input"] == "纯文本"
    finally:
        await container.shutdown()


def test_structured_input_reaches_agent(tmp_path) -> None:
    asyncio.run(_structured_scenario(tmp_path))


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

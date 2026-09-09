"""M1a 验收：接入 Agent → 冻结版本 → 签发 SDK 密钥 → 用密钥换上下文。

关键不变量：明文密钥只出现一次；`asset_id`/`tenant_id` 只从密钥反查得到。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.container import Container
from backend.app.contracts.common import AssetKind, Channel, CredentialKind
from backend.app.contracts.errors import DomainError
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'asset.db'}",
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
        owner_id = seeded["admin"]
        assets = container.assets

        # 接入：重复接入同名 Agent 返回既有资产，不产生第二行
        agent = await assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner_id,
            name="customer-support-agent",
            description="客服",
            connect_type="sdk",
        )
        again = await assets.register_agent(
            workspace_id=workspace_id,
            owner_id=owner_id,
            name="customer-support-agent",
            connect_type="sdk",
        )
        assert again.id == agent.id
        assert agent.kind is AssetKind.AGENT

        # 首个版本自动生成，并绑定到 TEST 通道
        versions = await assets.list_versions(agent.id, workspace_id)
        assert [v.version_label for v in versions] == ["0.1.0"]
        channels = await assets.channel_states(agent.id, workspace_id)
        assert channels[Channel.TEST].version_id == versions[0].id
        assert channels[Channel.LIVE].version_id is None

        # 相同内容的版本不重复落库
        spec = {"kind": "agent", "connect_type": "sdk"}
        created = await assets.create_version(
            asset_id=agent.id, workspace_id=workspace_id, created_by=owner_id, spec=spec
        )
        duplicate = await assets.create_version(
            asset_id=agent.id, workspace_id=workspace_id, created_by=owner_id, spec=spec
        )
        assert duplicate.id == created.id

        # 非法 spec 被拒绝
        with pytest.raises(DomainError):
            await assets.create_version(
                asset_id=agent.id,
                workspace_id=workspace_id,
                created_by=owner_id,
                spec={"kind": "agent", "connect_type": "github"},  # 缺 repository 等
            )

        # 签发 SDK 密钥：自动建默认租户，密钥绑定 (agent, tenant)
        issued = await assets.mint_credential(
            workspace_id=workspace_id, kind=CredentialKind.TRACE, asset_id=agent.id
        )
        assert issued.secret.startswith("evk_")
        assert issued.credential.secret_hash != issued.secret  # 库里不存明文
        assert issued.credential.asset_id == agent.id
        assert issued.credential.tenant_id is not None

        # 用密钥换上下文
        context = await assets.resolve_credential(issued.secret)
        assert context is not None
        assert context.asset_id == agent.id
        assert context.tenant_id == issued.credential.tenant_id
        assert context.kind is CredentialKind.TRACE

        # 不存在的密钥
        assert await assets.resolve_credential("evk_not-a-real-key") is None

        # 轮换：新密钥可用，旧密钥立即失效
        rotated = await assets.rotate_credential(issued.credential.id, workspace_id)
        assert rotated.secret != issued.secret
        assert await assets.resolve_credential(issued.secret) is None
        assert await assets.resolve_credential(rotated.secret) is not None
    finally:
        await container.shutdown()


def test_asset_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

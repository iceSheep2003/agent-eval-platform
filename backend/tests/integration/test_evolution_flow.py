"""演化：提案 → 审批 → 应用；公共目录 → 派生。

四条硬约束：
1. **没有证据的提案不予受理**——否则无从判断该不该批；
2. **不能审自己的提案**——否则审核形同虚设；
3. **只有批准过的能应用**，且落成新版本、旧版本不动；
4. **派生之后两条线各自独立演化**——这才是「拿一份自己的」的意义。
"""

from __future__ import annotations

import asyncio

import httpx

from backend.app.container import Container
from backend.app.contracts.common import Channel
from backend.app.contracts.errors import DomainError, Errors
from backend.app.contracts.improvement import ProposalEvidence
from backend.app.main import create_app
from backend.app.seed import seed
from backend.app.settings import Settings
from backend.app.shared.clock import FixedClock

SKILL_SPEC = {
    "kind": "skill",
    "instructions": "先确认订单号，再判断是否可退。",
    "max_steps": 3,
    "timeout_ms": 5000,
}


def _container(tmp_path, clock: FixedClock) -> Container:
    return Container.build(
        Settings(
            env="development",
            data_dir=tmp_path,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'evo.db'}",
            master_key="test",
        ),
        clock=clock,
    )


async def _capability(container: Container, workspace_id: str, owner: str, name: str):
    return await container.assets.register_capability(
        workspace_id=workspace_id,
        owner_id=owner,
        kind=__import__(
            "backend.app.contracts.common", fromlist=["AssetKind"]
        ).AssetKind.SKILL,
        name=name,
        spec=SKILL_SPEC,
    )


async def _scenario(tmp_path) -> None:
    clock = FixedClock()
    container = _container(tmp_path, clock)
    await container.startup()
    try:
        seeded = await seed(container)
        workspace_id = seeded["workspace_id"]
        admin = seeded["admin"]
        demo = seeded["demo"]  # evaluator 角色，有 PROPOSAL_SUBMIT/REVIEW

        skill = await _capability(container, workspace_id, admin, "退款判定")
        version = (await container.assets.list_versions(skill.id, workspace_id))[0]
        await container.assets.bind_channel(
            asset_id=skill.id,
            channel=Channel.LIVE,
            version_id=version.id,
            workspace_id=workspace_id,
            actor_id=admin,
        )

        # -- 1. 没有证据 → 拒收 -------------------------------------------
        no_evidence: DomainError | None = None
        try:
            await container.proposals.submit(
                workspace_id=workspace_id,
                kind="revise",
                target_asset_id=skill.id,
                created_by=demo,
                proposed_spec={**SKILL_SPEC, "max_steps": 5},
                evidence=(),
            )
        except DomainError as exc:
            no_evidence = exc
        assert no_evidence is not None, "没有证据的提案应当被拒"
        assert no_evidence.error is Errors.VALIDATION_FAILED

        # -- 2. 带证据的提案可以提交 ---------------------------------------
        proposal = await container.proposals.submit(
            workspace_id=workspace_id,
            kind="revise",
            target_asset_id=skill.id,
            created_by=demo,
            proposed_spec={**SKILL_SPEC, "max_steps": 5},
            base_version_id=version.id,
            evidence=(
                ProposalEvidence(
                    kind="failed_trace",
                    ref="trc_abc",
                    summary="用户问‘几天内能退’时，步数耗尽导致未给出政策",
                    metrics={"pass_rate": 0.71, "previous": 0.93},
                ),
            ),
            rationale="把 max_steps 从 3 提到 5，覆盖「查政策 + 查订单」的多步问法",
        )
        assert proposal.status == "submitted"

        # -- 3. 不能审自己的提案 -------------------------------------------
        self_review: DomainError | None = None
        try:
            await container.proposals.review(
                proposal_id=proposal.id,
                workspace_id=workspace_id,
                approved=True,
                reviewer_id=demo,  # 与 created_by 相同
            )
        except DomainError as exc:
            self_review = exc
        assert self_review is not None, "不能审自己的提案"
        assert self_review.error is Errors.PERMISSION_DENIED

        # -- 4. 未批准的不能应用 -------------------------------------------
        not_approved: DomainError | None = None
        try:
            await container.proposals.apply(
                proposal_id=proposal.id, workspace_id=workspace_id, actor_id=admin
            )
        except DomainError as exc:
            not_approved = exc
        assert not_approved is not None
        assert not_approved.error is Errors.RUN_STATE_CONFLICT

        # -- 5. 换个人审批通过，再应用 -------------------------------------
        approved = await container.proposals.review(
            proposal_id=proposal.id,
            workspace_id=workspace_id,
            approved=True,
            reviewer_id=admin,
            note="证据充分，同意",
        )
        assert approved.status == "approved"

        applied = await container.proposals.apply(
            proposal_id=proposal.id, workspace_id=workspace_id, actor_id=admin
        )
        assert applied.status == "applied"
        assert applied.applied_version_id is not None

        # 旧版本还在，新版本多了一个——**旧版本不动**
        versions = await container.assets.list_versions(skill.id, workspace_id)
        assert len(versions) == 2, [v.version_label for v in versions]
        assert any(v.id == version.id for v in versions)

        # -- 6. 公共目录：默认看不到未公开的 ---------------------------------
        public = await container.assets.list_publishable(workspace_id)
        assert all(item.id != skill.id for item in public), "未提为公共的不该出现"

        await container.assets.promote_asset(skill.id, workspace_id)
        public = await container.assets.list_publishable(workspace_id)
        assert any(item.id == skill.id for item in public), "提为公共后应当出现"

        # -- 7. 派生：拿到一份自己的副本 ------------------------------------
        forked = await container.assets.fork_from(
            source_asset_id=skill.id,
            workspace_id=workspace_id,
            owner_id=admin,
            name="退款判定（我方）",
        )
        forked_versions = await container.assets.list_versions(forked.id, workspace_id)
        assert len(forked_versions) == 1
        assert forked_versions[0].spec["forked_from"]["asset_id"] == skill.id, (
            "派生版本应记录血缘"
        )

        # -- 8. 影响面：谁引用了它 ------------------------------------------
        agent = await container.assets.register_agent(
            workspace_id=workspace_id,
            owner_id=admin,
            name="agent-using-skill",
            connect_type="package",
            source={
                "artifact_id": "a-1",
                "entrypoint": f"{__name__}:noop_agent",
                "memory": {"scope": "stateless"},
            },
        )
        agent_version = (await container.assets.list_versions(agent.id, workspace_id))[0]
        await container.assets.bind_capability(
            workspace_id=workspace_id,
            actor_id=admin,
            consumer_asset_id=agent.id,
            provider_asset_id=forked.id,
            consumer_version_id=agent_version.id,
        )

        report = await container.proposals.impact(forked.id, workspace_id)
        assert agent.id in report.direct_consumers, report.direct_consumers
        assert report.total_consumers >= 1

        # -- 9. 不能派生非公共资产 ------------------------------------------
        refused: DomainError | None = None
        try:
            await container.assets.fork_from(
                source_asset_id=forked.id,  # fork 出来的默认不是公共的
                workspace_id=workspace_id,
                owner_id=admin,
                name="再派生",
            )
        except DomainError as exc:
            refused = exc
        assert refused is not None and refused.error is Errors.PERMISSION_DENIED

        # -- 10. HTTP：接口都在 --------------------------------------------
        app = create_app(container)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/login", json={"identifier": "admin", "password": "admin123"}
            )
            impact = await client.get(f"/api/assets/{forked.id}/impact")
            assert impact.status_code == 200, impact.text
            assert agent.id in impact.json()["data"]["direct_consumers"]

            proposals = await client.get(f"/api/assets/{skill.id}/proposals")
            assert proposals.status_code == 200, proposals.text
            assert len(proposals.json()["data"]["items"]) == 1

            catalog = await client.get("/api/public-assets")
            assert catalog.status_code == 200, catalog.text
    finally:
        await container.shutdown()


def noop_agent(input: str) -> str:  # noqa: A002
    return input


def test_evolution_flow(tmp_path) -> None:
    asyncio.run(_scenario(tmp_path))

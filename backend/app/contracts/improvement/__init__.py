"""演化契约：能力资产怎么从「现在这样」变成「更好的样子」。

**为什么提案必须带证据**：没有证据的改动只是「换了一个版本」，无法回答
「为什么改」「改好了没有」。所以每个提案都锚在**具体的失败事实**上
（哪条 Trace、哪个版本的哪个指标），并且关掉时要给出结论。

三条正交的演化路径：
- `revise`   —— 改自己的能力资产（新版本，旧版本不动）；
- `fork`     —— 从公共资产派生一份自己的，之后独立演化；
- `promote`  —— 把自己的资产提为公共，供他人派生。

审批与机器凭证的边界：`MACHINE_FORBIDDEN` 已把 `PROPOSAL_REVIEW` 收窄，
**Agent 自己不能批自己的提案**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

from ..common import AssetKind, Id

#: 提案做什么。
ProposalKind = Literal["revise", "fork", "promote"]
ProposalStatus = Literal["draft", "submitted", "approved", "rejected", "applied"]

#: 证据从哪来。**没有来源的提案不予受理**——否则无从判断该不该批。
EvidenceKind = Literal["failed_trace", "metric_regression", "manual"]


@dataclass(frozen=True, slots=True)
class ProposalEvidence:
    """一条证据。指向一条可核对的事实，而不是一句描述。"""

    kind: EvidenceKind
    #: 失败 Trace 的 id / 指标名 / 人工说明。
    ref: str
    summary: str
    #: 补充数字，如 `{"pass_rate": 0.71, "previous": 0.93}`。
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Proposal:
    id: Id
    workspace_id: Id
    kind: ProposalKind
    status: ProposalStatus
    #: 要改的资产（revise/promote）；fork 时是派生出来的新资产。
    target_asset_id: Id
    #: 提议的新 spec。`promote` 时为空——它不改内容，只改可见性。
    proposed_spec: Mapping[str, Any] = field(default_factory=dict)
    #: 基线版本：改动要和它比。
    base_version_id: Id | None = None
    evidence: tuple[ProposalEvidence, ...] = ()
    rationale: str = ""
    #: 应用后产生的新版本。
    applied_version_id: Id | None = None
    created_by: Id = ""
    reviewed_by: Id | None = None
    review_note: str = ""
    created_at: datetime | None = None
    reviewed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ImpactReport:
    """改动会影响谁。**先看影响面再改**——公共资产可能被几十个 Agent 引用。"""

    asset_id: Id
    #: 直接引用它的 Agent。
    direct_consumers: tuple[Id, ...] = ()
    #: 引用它的 Agent 们，各自又引用了什么（间接影响）。
    transitive_consumers: tuple[Id, ...] = ()
    #: 它当前绑在哪些通道上。
    channels: Mapping[str, Id | None] = field(default_factory=dict)

    @property
    def total_consumers(self) -> int:
        return len(set(self.direct_consumers) | set(self.transitive_consumers))


__all__ = [
    "ImpactReport",
    "Proposal",
    "ProposalEvidence",
    "ProposalKind",
    "ProposalStatus",
]

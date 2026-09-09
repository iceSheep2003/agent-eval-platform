# Eval Loom 契约层草案（`contracts/`）

> 配套文档：[backend-architecture.md](backend-architecture.md)。
> 本文是 **Track 0 的交付物**：契约一旦冻结，五条 Track 才能并行开工。
> 所有代码为草案，目的是把**跨模块的边界**先钉死，实现细节留给各模块。

---

## 0. 三条铁律

1. **契约只描述边界，不描述实现**。`contracts/` 里不出现 SQLAlchemy、FastAPI、HTTP 客户端。
2. **Port 由消费方定义**。B 需要 A 的数据，B 在 `contracts/` 声明自己需要的 Protocol，A 提供适配器。
   这样依赖方向永远指向契约，不会出现 `asset ↔ evaluation` 的循环 import。
3. **DTO 一旦发布只能追加**。改字段名或改语义 = 破坏性变更，必须走 §14 的评审流程。

### 版本策略

```python
CONTRACT_VERSION = "1.0.0"
```

- 契约包整体一个版本号，写在 `contracts/__init__.py`。
- 事件带独立的 `event_version`，单个事件 payload 变更时递增，不与契约版本耦合。
- 消费者启动时校验 `CONTRACT_VERSION` 主版本一致，不一致直接拒绝启动。

---

## 1. 依赖矩阵

| 契约包 | 定义方 | 实现方 | 消费方 |
| --- | --- | --- | --- |
| `contracts.identity` | identity | identity | **全部模块** |
| `contracts.asset` | execution / observability / evaluation（消费方） | asset | execution、observability、evaluation、delivery |
| `contracts.dataset` | execution（消费方） | dataset | execution、improvement |
| `contracts.evaluation` | execution（消费方） | evaluation | execution、delivery |
| `contracts.execution` | observability / delivery（消费方） | execution | observability、improvement、delivery |
| `contracts.observability` | execution / improvement（消费方） | observability | execution、improvement、delivery |
| `contracts.improvement` | delivery（消费方） | improvement | delivery |
| `contracts.delivery` | — | delivery | api/gateway |

**"定义方 = 消费方"是刻意的**：谁需要数据谁定接口，实现方负责满足。这样新增消费场景时
只需在契约里加一个 Protocol，不必改上游模块。

---

## 2. `contracts/common.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Mapping, Sequence, TypeVar

CONTRACT_VERSION = "1.0.0"

type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
type Id = str          # 带前缀，如 "agent_01H..."、"run_01H..."

T = TypeVar("T")


# ---------- 枚举：全系统唯一真源，前端枚举也以此为准 ----------

class Channel(StrEnum):
    TEST = "test"
    LIVESH = "livesh"
    LIVE = "live"


class VersionLifecycle(StrEnum):          # AssetVersion.lifecycle
    DRAFT = "draft"
    EVALUATING = "evaluating"
    READY = "ready"
    BLOCKED = "blocked"
    RETIRED = "retired"


class AssetKind(StrEnum):
    AGENT = "agent"
    SKILL = "skill"
    MCP = "mcp"
    KNOWLEDGE_BASE = "knowledge_base"


class EvaluationStage(StrEnum):           # 评测阶段，与 Channel 严格区分
    DEVELOPMENT = "development"
    REGRESSION = "regression"
    RELEASE = "release"
    PRODUCTION = "production"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    PROVISIONING = "provisioning"
    EXECUTING = "executing"
    SCORING = "scoring"
    COMPLETED = "completed"


class ExecutionStatus(StrEnum):           # Trial 执行侧
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class Verdict(StrEnum):                   # Trial 质量侧，与 ExecutionStatus 正交
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


class TraceOrigin(StrEnum):
    PRODUCTION = "production"
    SHADOW = "shadow"
    EVALUATION = "evaluation"


class SpanKind(StrEnum):
    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    RETRIEVER = "retriever"


class Determinism(StrEnum):
    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"


class ActorKind(StrEnum):
    USER = "user"
    AGENT = "agent"
    MONITOR = "monitor"
    SERVICE = "service"
    SYSTEM = "system"


class GateAction(StrEnum):
    BLOCK = "block"
    WARN = "warn"


class ScopeKind(StrEnum):                 # Score.scope / GateRule.scope
    CASE = "case"
    TRAJECTORY = "trajectory"
    SPAN = "span"
    RUN = "run"
    ASSET_VERSION = "asset_version"
    WORKSPACE_WINDOW = "workspace_window"
    TENANT = "tenant"


# ---------- 值对象 ----------

@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class Ratio:
    """0–1 的比率。API 层用 Field(ge=0, le=1) 卡死，展示层负责乘 100。"""
    value: float


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class Cursor:
    value: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: Sequence[T]
    next_cursor: str | None
    total: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    field: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    issues: tuple[ValidationIssue, ...] = ()

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(ok=True)

    @classmethod
    def failure(cls, *issues: ValidationIssue) -> "ValidationResult":
        return cls(ok=False, issues=issues)


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Money = Money(Decimal("0"))


JsonObject = Mapping[str, JsonValue]
```

---

## 3. `contracts/errors.py`

错误码是**跨模块的公共词汇**，前端也要据此做文案。每条带稳定 `code` 与 HTTP 状态。

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorCode:
    code: str
    http_status: int
    message: str


class Errors:
    # 通用
    NOT_FOUND = ErrorCode("not_found", 404, "资源不存在")
    VALIDATION_FAILED = ErrorCode("validation_failed", 422, "参数校验失败")
    IDEMPOTENCY_CONFLICT = ErrorCode("idempotency_conflict", 409, "幂等键冲突且内容不一致")
    CONTRACT_VERSION_MISMATCH = ErrorCode("contract_version_mismatch", 500, "契约版本不匹配")

    # 隔离
    WORKSPACE_MISMATCH = ErrorCode("workspace_mismatch", 403, "资源不属于当前工作区")
    TENANT_OUT_OF_SCOPE = ErrorCode("tenant_out_of_scope", 403, "租户不在你的可见范围内")
    TENANT_UNKNOWN = ErrorCode("tenant_unknown", 422, "租户未登记")
    TENANT_SUSPENDED = ErrorCode("tenant_suspended", 422, "租户已停用")

    # 鉴权
    UNAUTHENTICATED = ErrorCode("unauthenticated", 401, "未登录或会话已过期")
    PERMISSION_DENIED = ErrorCode("permission_denied", 403, "没有该操作的权限")
    REAUTH_REQUIRED = ErrorCode("reauth_required", 401, "该操作需要重新认证")

    # 资产与版本
    VERSION_IMMUTABLE = ErrorCode("version_immutable", 409, "已固化的版本不可修改")
    VERSION_DIGEST_CONFLICT = ErrorCode("version_digest_conflict", 409, "相同内容的版本已存在")
    CHANNEL_CONFLICT = ErrorCode("channel_conflict", 409, "该通道已绑定其他版本")
    PROMOTION_ORDER_VIOLATION = ErrorCode("promotion_order_violation", 409, "版本只能按 TEST→LIVESH→LIVE 晋级")
    GATE_BLOCKED = ErrorCode("gate_blocked", 409, "质量门禁未通过，禁止晋级")
    CREDENTIAL_SCOPE_VIOLATION = ErrorCode("credential_scope_violation", 403, "凭证不允许该操作")

    # 数据集
    DATASET_VERSION_IMMUTABLE = ErrorCode("dataset_version_immutable", 409, "数据集版本已固化")
    IMPORT_VALIDATION_FAILED = ErrorCode("import_validation_failed", 422, "导入预检未通过")

    # 运行
    RUN_FINALIZED = ErrorCode("run_finalized", 409, "运行已结束，结果不可修改")
    RUN_STATE_CONFLICT = ErrorCode("run_state_conflict", 409, "当前状态下不允许该操作")

    # 上报
    INGEST_TENANT_MISMATCH = ErrorCode("ingest_tenant_mismatch", 422, "事件租户与密钥绑定租户不一致")
    INGEST_BATCH_TOO_LARGE = ErrorCode("ingest_batch_too_large", 413, "单批超过 1000 事件 / 5 MiB")
```

---

## 4. `contracts/events.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .common import ActorKind, Id, JsonValue


@dataclass(frozen=True, slots=True)
class ActorRef:
    kind: ActorKind
    id: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: Id
    event_type: str                 # 见下方目录
    event_version: int              # payload 结构变更时 +1
    workspace_id: Id
    tenant_id: Id | None
    aggregate_type: str
    aggregate_id: Id
    sequence: int                   # 单聚合内单调递增
    occurred_at: datetime
    actor: ActorRef
    payload: Mapping[str, JsonValue]


class EventType:
    # identity
    MEMBER_ROLE_CHANGED = "identity.member.role_changed"
    MEMBER_REMOVED = "identity.member.removed"
    TENANT_SYNCED = "identity.tenant.synced"
    TENANT_PURGED = "identity.tenant.purged"

    # asset
    ASSET_CREATED = "asset.created"
    VERSION_CREATED = "asset.version.created"
    CHANNEL_BOUND = "asset.channel.bound"
    CREDENTIAL_CREATED = "asset.credential.created"
    CREDENTIAL_REVOKED = "asset.credential.revoked"

    # dataset
    DATASET_VERSION_FINALIZED = "dataset.version.finalized"
    DATASET_IMPORT_FAILED = "dataset.import.failed"

    # evaluation
    TEMPLATE_CREATED = "evaluation.template.created"
    TEMPLATE_UPDATED = "evaluation.template.updated"
    TEMPLATE_DISABLED = "evaluation.template.disabled"

    # execution
    RUN_CREATED = "execution.run.created"
    RUN_STARTED = "execution.run.started"
    RUN_PAUSED = "execution.run.paused"
    RUN_RESUMED = "execution.run.resumed"
    RUN_CANCELLED = "execution.run.cancelled"
    RUN_COMPLETED = "execution.run.completed"
    RUN_FAILED = "execution.run.failed"
    TRIAL_STARTED = "execution.trial.started"
    TRIAL_EXECUTION_FAILED = "execution.trial.execution_failed"
    TRIAL_SCORED = "execution.trial.scored"

    # observability
    TRACE_INGESTED = "observability.trace.ingested"
    SCORE_EMITTED = "observability.score.emitted"
    METRICS_THRESHOLD_BREACHED = "observability.metrics.threshold_breached"

    # improvement
    PROPOSAL_CREATED = "improvement.proposal.created"
    PROPOSAL_REVIEWED = "improvement.proposal.reviewed"
    REGRESSION_SAMPLE_CREATED = "improvement.regression_sample.created"

    # delivery
    PROMOTION_REQUESTED = "delivery.promotion.requested"
    PROMOTION_BLOCKED = "delivery.promotion.blocked"
    PROMOTION_APPROVED = "delivery.promotion.approved"
    VERSION_ROLLED_BACK = "delivery.version.rolled_back"


class EventBusPort(Protocol):
    """P0 进程内分发；接口按跨进程设计，换消息队列不改业务代码。"""
    async def publish(self, event: DomainEvent) -> None: ...
```

**事件 payload 示例**（约定：只放 ID 和判定结论，不放业务实体全量，消费者自行回查）：

```python
# evaluation.template.updated
{"template_id": "tpl_...", "changed_fields": ["gates", "evaluators"], "enabled": True}

# execution.run.completed
{"run_id": "run_...", "status": "completed", "pass_rate": 0.93,
 "trial_counts": {"pass": 28, "fail": 2, "execution_failed": 0, "skipped": 0}}

# delivery.promotion.blocked
{"asset_id": "agent_...", "version_id": "ver_...", "from": "test", "to": "liversh",
 "blocked_rules": ["task_success_rate", "safety_violation_rate"]}
```

---

## 5. `contracts/identity/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Sequence

from ..common import Id, Page, Cursor


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EVALUATOR = "evaluator"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Permission(StrEnum):
    """权限点常量。命名规则 <resource>:<action>，与架构文档 §5.2 矩阵一一对应。"""
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_SETTINGS_WRITE = "workspace:settings:write"
    MEMBER_INVITE = "member:invite"
    MEMBER_ROLE_WRITE = "member:role:write"
    MEMBER_REMOVE = "member:remove"

    ASSET_READ = "asset:read"
    ASSET_CREATE = "asset:create"
    ASSET_UPDATE = "asset:update"
    ASSET_ARCHIVE = "asset:archive"
    ASSET_VERSION_CREATE = "asset:version:create"
    ASSET_CREDENTIAL_CREATE = "asset:credential:create"
    ASSET_CREDENTIAL_REVOKE = "asset:credential:revoke"

    DATASET_READ = "dataset:read"
    DATASET_CREATE = "dataset:create"
    DATASET_IMPORT = "dataset:import"
    DATASET_VERSION_FINALIZE = "dataset:version:finalize"
    DATASET_EXPORT = "dataset:export"

    TEMPLATE_READ = "template:read"
    TEMPLATE_CREATE = "template:create"
    TEMPLATE_UPDATE = "template:update"
    TEMPLATE_DISABLE = "template:disable"
    TEMPLATE_BIND = "template:bind"
    GATE_CONFIGURE = "gate:configure"

    RUN_READ = "run:read"
    RUN_CREATE = "run:create"
    RUN_CONTROL = "run:control"

    TRACE_READ = "trace:read"
    TRACE_READ_RAW = "trace:read_raw"
    METRICS_READ = "metrics:read"

    PROPOSAL_READ = "proposal:read"
    PROPOSAL_SUBMIT = "proposal:submit"
    PROPOSAL_REVIEW = "proposal:review"

    VERSION_PROMOTE_LIVESH = "version:promote:livesh"
    VERSION_PROMOTE_LIVE = "version:promote:live"
    VERSION_ROLLBACK = "version:rollback"
    SHADOW_CONFIGURE = "shadow:configure"

    TENANT_EXPORT = "tenant:export"
    TENANT_PURGE = "tenant:purge"
    TENANT_SYNC = "tenant:sync"          # 仅机器凭证持有


@dataclass(frozen=True, slots=True)
class UserRef:
    id: Id
    display_name: str
    email: str | None
    status: Literal["active", "disabled"]


@dataclass(frozen=True, slots=True)
class WorkspaceRef:
    id: Id
    name: str


@dataclass(frozen=True, slots=True)
class TenantRef:
    id: Id
    workspace_id: Id
    external_key: str
    name: str
    status: Literal["active", "suspended", "purged"]


@dataclass(frozen=True, slots=True)
class Subject:
    """鉴权主体。用户会话与机器凭证统一成这个形状。"""
    kind: Literal["user", "credential"]
    id: str
    workspace_id: Id
    role: WorkspaceRole | None                      # 机器凭证为 None
    tenant_scope: Literal["all"] | tuple[Id, ...]   # 用户来自 Membership；凭证来自签发时的绑定
    credential_kind: Literal["evl", "evk", "evs"] | None = None


@dataclass(frozen=True, slots=True)
class ResourceRef:
    kind: str
    id: Id
    workspace_id: Id
    tenant_id: Id | None = None
    owner_id: Id | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str | None = None
    requires_reauth: bool = False
    denied_by: Literal["workspace", "tenant_scope", "role", "ownership", "auto_subject"] | None = None


class AuthorizerPort(Protocol):
    def decide(
        self,
        subject: Subject,
        action: Permission,
        resource: ResourceRef | None = None,
    ) -> Decision: ...


class TenantQueryPort(Protocol):
    async def get(self, tenant_id: Id, workspace_id: Id) -> TenantRef | None: ...
    async def by_external_key(self, external_key: str, workspace_id: Id) -> TenantRef | None: ...
    async def list_page(self, workspace_id: Id, cursor: Cursor) -> Page[TenantRef]: ...
    async def in_scope(self, subject: Subject, tenant_id: Id) -> bool: ...


class MembershipQueryPort(Protocol):
    async def workspaces_of(self, user_id: Id) -> Sequence[WorkspaceRef]: ...
    async def tenant_scope_of(self, user_id: Id, workspace_id: Id) -> Literal["all"] | tuple[Id, ...]: ...
```

**`Authorizer` 的三条硬约束**（实现方必须满足，契约测试会验）：

1. `subject.kind == "credential"` 时，`PROPOSAL_REVIEW` 与所有 `VERSION_PROMOTE_*` 一律拒绝。
2. `subject.kind == "user"` 且 `actor.kind ∈ {agent, monitor}` 时，同上拒绝。
3. `resource.workspace_id != subject.workspace_id` 时一律拒绝，`denied_by="workspace"`。

---

## 6. `contracts/asset/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol, Sequence

from ..common import (AssetKind, Channel, Id, JsonObject, Page, Cursor,
                      ValidationResult, VersionLifecycle)


@dataclass(frozen=True, slots=True)
class AssetRef:
    id: Id
    workspace_id: Id
    kind: AssetKind
    name: str
    owner_id: Id
    tenant_scope: Literal["workspace_shared", "tenant_bound"]
    tenant_id: Id | None
    lifecycle: Literal["draft", "active", "archived"]


@dataclass(frozen=True, slots=True)
class AssetVersionRef:
    id: Id
    asset_id: Id
    workspace_id: Id
    version_label: str
    lifecycle: VersionLifecycle
    spec_digest: str


@dataclass(frozen=True, slots=True)
class ChannelState:
    channel: Channel
    version: AssetVersionRef | None
    bound_at: datetime | None
    bound_by: Id | None


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    """执行面启动被测对象所需的最小信息。"""
    asset_id: Id
    asset_version_id: Id
    workspace_id: Id
    kind: AssetKind
    spec: JsonObject                # 已按 kind 校验过的结构化配置
    artifact_ref: str | None        # 代码包/制品在对象存储中的引用
    entrypoint: str | None


class AssetSpecPort(Protocol):
    """由 asset 实现；execution 在冻结版本与启动 Runtime 时调用。"""
    def validate(self, kind: AssetKind, spec: JsonObject) -> ValidationResult: ...
    def digest(self, kind: AssetKind, spec: JsonObject) -> str: ...
    def extract_runtime_spec(self, version: AssetVersionRef, spec: JsonObject) -> RuntimeSpec: ...


class AssetQueryPort(Protocol):
    """由 asset 实现；execution / observability / evaluation / delivery 消费。"""
    async def get(self, asset_id: Id, workspace_id: Id) -> AssetRef | None: ...
    async def get_version(self, version_id: Id, workspace_id: Id) -> AssetVersionRef | None: ...
    async def get_runtime_spec(self, version_id: Id, workspace_id: Id) -> RuntimeSpec | None: ...
    async def channel_states(self, asset_id: Id, workspace_id: Id) -> Mapping[Channel, ChannelState]: ...
    async def version_of_channel(self, asset_id: Id, channel: Channel, workspace_id: Id) -> AssetVersionRef | None: ...
    async def tenants_of_agent(self, agent_id: Id, workspace_id: Id) -> Sequence[Id]: ...
    async def agents_using(self, version_id: Id, workspace_id: Id) -> Sequence[AssetRef]: ...


class ArtifactPort(Protocol):
    """接入制品（代码包 / Git 构建产物）的元数据。"""
    async def get(self, artifact_id: Id) -> Mapping[str, object] | None: ...
```

**spec 的形状**由 `asset.domain.spec/` 校验，契约层只约定判别字段：

```text
{"kind": "agent",          ...}    # source=github|package|sdk
{"kind": "skill",          ...}    # instructions / allowed_tools / max_steps / timeout_ms
{"kind": "mcp",            ...}    # endpoint / transport / authentication / tools[]
{"kind": "knowledge_base", ...}    # embedding_model / index_name / chunk_strategy / retrieval / sources[]
```

---

## 7. `contracts/dataset/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Sequence

from ..common import Id, JsonValue, Page, Cursor


class SourcePurpose(StrEnum):     # 与 task_shape 正交
    BENCHMARK = "benchmark"
    REGRESSION = "regression"
    PRODUCTION_TRACE = "production_trace"


class TaskShape(StrEnum):
    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"
    AGENTIC = "agentic"


@dataclass(frozen=True, slots=True)
class SampleRef:
    id: Id
    dataset_version_id: Id
    workspace_id: Id
    tenant_id: Id | None            # 生产 Trace 回流时继承来源租户
    index: int
    name: str | None
    input: JsonValue
    expected_output: JsonValue | None
    validation: Literal["valid", "needs_review", "invalid"]


@dataclass(frozen=True, slots=True)
class DatasetVersionRef:
    id: Id
    dataset_id: Id
    workspace_id: Id
    version_label: str
    source_purpose: SourcePurpose
    task_shape: TaskShape
    item_count: int
    finalized_at: datetime | None


class SampleReaderPort(Protocol):
    """由 dataset 实现；execution 展开 Trial 时按页读取。"""
    async def get_version(self, version_id: Id, workspace_id: Id) -> DatasetVersionRef | None: ...
    async def count(self, version_id: Id, tenant_scope: Literal["all"] | tuple[Id, ...]) -> int: ...
    async def read_page(
        self,
        version_id: Id,
        tenant_scope: Literal["all"] | tuple[Id, ...],
        cursor: Cursor,
    ) -> Page[SampleRef]: ...
    async def read_one(self, sample_id: Id) -> SampleRef | None: ...


class SampleWriterPort(Protocol):
    """由 dataset 实现；improvement 沉淀回归样本时调用。"""
    async def append_draft_sample(
        self,
        dataset_id: Id,
        workspace_id: Id,
        input: JsonValue,
        expected_output: JsonValue | None,
        source_trace_id: Id,
        tenant_id: Id | None,
    ) -> SampleRef: ...
```

**关键约定**：`expected_output` **永不进入 `RuntimeSpec` 或 Agent 输入**，
只在评分时通过 `SampleReaderPort.read_one` 给评估器。契约层用类型区分不了这件事，
靠 `execution` 的执行路径保证（架构文档 §10.2）。

---

## 8. `contracts/evaluation/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol, Sequence

from ..common import (Determinism, EvaluationStage, GateAction, Id,
                      JsonObject, ScopeKind)


@dataclass(frozen=True, slots=True)
class EvaluatorSpec:
    name: str
    version: str
    determinism: Determinism
    config: JsonObject = {}


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    id: Id
    name: str
    weight: float                    # 0–1，同一模板内归一
    threshold: float                 # 0–1
    evaluator_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateRuleSpec:
    name: str                        # 指标 key，如 task_success_rate
    threshold: float                 # 0–1
    unit: Literal["score", "percent", "ms"]
    comparison: Literal["gte", "lte"]
    scope: ScopeKind                 # workspace | tenant
    action: GateAction               # block | warn
    required_determinism: Determinism | None = None
    min_samples: int = 0             # 低于此样本数的租户只告警


@dataclass(frozen=True, slots=True)
class TemplateSnapshot:
    """Run 创建时冻结，之后模板怎么改都不影响历史 Run。"""
    template_id: Id | None           # ad_hoc 时为 None
    template_name: str
    template_version: str
    stage: EvaluationStage
    dataset_version_id: Id
    evaluators: tuple[EvaluatorSpec, ...]
    dimensions: tuple[DimensionSpec, ...]
    gates: tuple[GateRuleSpec, ...]
    snapshot_source: Literal["explicit", "derived_from_binding", "ad_hoc"]
    frozen_at: datetime


@dataclass(frozen=True, slots=True)
class GateRuleResult:
    rule: str
    actual: float
    threshold: float
    unit: str
    passed: bool
    action: GateAction
    tenant_id: Id | None = None
    sample_size: int | None = None


@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    results: tuple[GateRuleResult, ...]
    blocked_reasons: tuple[str, ...]
    evaluated_at: datetime


class TemplateSnapshotPort(Protocol):
    """由 evaluation 实现；execution 创建 Run 时取快照。"""
    async def snapshot_for(
        self,
        workspace_id: Id,
        template_id: Id | None,
        asset_id: Id,
        stage: EvaluationStage | None,
    ) -> TemplateSnapshot: ...


class EvaluatorRegistryPort(Protocol):
    """由 execution 的评分引擎实现；evaluation 校验模板时确认评估器存在。"""
    def exists(self, name: str, version: str) -> bool: ...
    def determinism_of(self, name: str, version: str) -> Determinism | None: ...
```

**`GateEngine` 是纯函数，不在契约层**（它在 `execution` 模块内部）：

```python
def evaluate_gate(snapshot: TemplateSnapshot, result: RunResultView) -> GateDecision: ...
```

契约层只保证 `GateDecision` 的形状，让 `delivery` 能消费。

---

## 9. `contracts/execution/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol, Sequence

from ..asset import RuntimeSpec
from ..common import (ExecutionStatus, Id, JsonObject, Money, Page, Cursor,
                      RunStage, RunStatus, Verdict)
from ..evaluation import TemplateSnapshot


@dataclass(frozen=True, slots=True)
class SubjectRef:                 # 被测对象：Agent 或能力资产的具体版本
    kind: str
    asset_id: Id
    version_id: Id
    version_label: str


@dataclass(frozen=True, slots=True)
class RunRef:
    id: Id
    workspace_id: Id
    name: str
    subject: SubjectRef
    dataset_version_id: Id
    template: TemplateSnapshot
    tenant_scope: Literal["all"] | tuple[Id, ...]
    status: RunStatus
    stage: RunStage
    concurrency: int
    cost_budget: Money
    created_by: Id
    created_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class RunResultView:
    """固化后的聚合结果。Run 进入终态后写入，之后只读。"""
    run_id: Id
    trial_counts: Mapping[ExecutionStatus, int]
    verdict_counts: Mapping[Verdict, int]
    pass_rate: float
    avg_score: float
    total_cost: Money
    total_duration_ms: int
    dimension_scores: Mapping[str, float]        # dimension_id → 平均分
    tenant_breakdown: Mapping[Id, Mapping[str, float]]  # tenant_id → 指标
    gate_decision: "GateDecision | None"
    finalized_at: datetime


@dataclass(frozen=True, slots=True)
class TrialRef:
    id: Id
    run_id: Id
    sample_id: Id
    tenant_id: Id | None
    attempt_no: int
    execution_status: ExecutionStatus
    verdict: Verdict | None
    trace_id: Id | None
    duration_ms: int | None
    cost: Money | None


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    command_id: Id
    command_type: str
    workspace_id: Id
    aggregate_type: str
    aggregate_id: Id
    idempotency_key: str
    payload: JsonObject
    attempt_no: int = 0
    not_before: datetime | None = None


class RunQueryPort(Protocol):
    async def get(self, run_id: Id, workspace_id: Id) -> RunRef | None: ...
    async def result(self, run_id: Id) -> RunResultView | None: ...
    async def list_page(self, workspace_id: Id, cursor: Cursor) -> Page[RunRef]: ...
    async def trials_page(self, run_id: Id, cursor: Cursor) -> Page[TrialRef]: ...


class CommandQueuePort(Protocol):
    async def enqueue(self, envelope: CommandEnvelope) -> None: ...
    async def claim(self, worker_id: str, limit: int, lease_seconds: int) -> Sequence[CommandEnvelope]: ...
    async def renew(self, command_id: Id, lease_seconds: int) -> bool: ...
    async def complete(self, command_id: Id) -> None: ...
    async def fail(self, command_id: Id, error: str, retry_after: float | None) -> None: ...


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: Id
    trial_id: Id
    workspace_id: Id
    tenant_id: Id | None
    sample_id: Id
    attempt_no: int
    timeout_seconds: float
    cost_budget: Money


@dataclass(frozen=True, slots=True)
class RuntimeHandle:
    id: str
    asset_version_id: Id
    endpoint: str | None
    ephemeral: bool               # True = 临时 Trial 环境，用完即销毁


class RuntimePort(Protocol):
    """由 runtime_adapters 实现（local_sandbox / docker / k8s / remote_http）。"""
    async def provision(self, spec: RuntimeSpec, ctx: RunContext) -> RuntimeHandle: ...
    async def invoke(self, handle: RuntimeHandle, payload: JsonObject) -> JsonObject: ...
    async def teardown(self, handle: RuntimeHandle) -> None: ...
```

---

## 10. `contracts/observability/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol, Sequence

from ..common import (Channel, Determinism, Id, JsonValue, Money, Page,
                      Cursor, ScopeKind, SpanKind, TraceOrigin, Usage, Window)
from ..identity import Subject


@dataclass(frozen=True, slots=True)
class TraceEventEnvelope:
    """SDK / Runtime 上报的单条事件。服务端按 (asset_id, external_trace_id, event_id) 幂等。"""
    event_id: Id
    external_trace_id: str
    asset_id: Id
    tenant_id: Id
    parent_event_id: Id | None
    event_type: str
    actor: Literal["agent", "model", "tool", "environment", "runtime", "evaluator"]
    name: str | None
    status: Literal["success", "error", "timeout", "cancelled"]
    started_at: datetime
    ended_at: datetime | None
    input: JsonValue | None
    output: JsonValue | None
    usage: Usage | None
    attributes: Mapping[str, JsonValue] = {}


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted_event_ids: tuple[Id, ...]
    rejected: tuple[tuple[Id, str], ...]     # (event_id, error_code)
    accepted_ranges: tuple[tuple[int, int], ...]  # 供 SDK 断点恢复


@dataclass(frozen=True, slots=True)
class TraceRef:
    id: Id
    workspace_id: Id
    tenant_id: Id | None
    origin: TraceOrigin
    asset_id: Id
    asset_version_id: Id
    channel: Channel | None
    run_id: Id | None
    trial_id: Id | None
    status: Literal["success", "error", "timeout", "cancelled"]
    started_at: datetime
    duration_ms: int | None
    usage: Usage
    span_count: int
    ingested_via: Literal["sdk", "gateway", "runtime"]


@dataclass(frozen=True, slots=True)
class SpanRef:
    id: Id
    trace_id: Id
    parent_span_id: Id | None
    kind: SpanKind
    name: str
    status: Literal["running", "ok", "error", "cancelled"]
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    depth: int
    input: JsonValue | None
    output: JsonValue | None
    usage: Usage | None
    attributes: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    kind: Literal["event", "span", "artifact", "trace"]
    id: Id
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ScoreRef:
    id: Id
    workspace_id: Id
    tenant_id: Id | None
    metric: str
    metric_version: str
    value: float | int | bool | str | None
    status: Literal["pass", "fail", "skip", "error"]
    reason: str | None
    scope_kind: ScopeKind
    scope_ref: Id | None
    evidence: tuple[EvidenceRef, ...]
    determinism: Determinism
    evaluator: Mapping[str, JsonValue] | None = None   # judge model / prompt version 等
    duration_ms: float | None = None
    cost: Money | None = None


@dataclass(frozen=True, slots=True)
class TraceQueryFilter:
    asset_id: Id | None = None
    asset_version_id: Id | None = None
    origin: TraceOrigin | None = None
    tenant_ids: tuple[Id, ...] | None = None      # 由 Authorizer 注入，不接受前端传
    status: str | None = None
    keyword: str | None = None
    window: Window | None = None


class TraceIngestPort(Protocol):
    async def ingest(
        self,
        batch: Sequence[TraceEventEnvelope],
        credential_asset_id: Id,
        credential_tenant_id: Id,
    ) -> IngestResult: ...


class TraceQueryPort(Protocol):
    async def list_page(self, filter: TraceQueryFilter, cursor: Cursor) -> Page[TraceRef]: ...
    async def get(self, trace_id: Id, workspace_id: Id) -> TraceRef | None: ...
    async def spans(self, trace_id: Id) -> Sequence[SpanRef]: ...
    async def raw_visible(self, trace_id: Id, subject: Subject) -> bool: ...


class ScoreWritePort(Protocol):
    """由 observability 实现；execution 的评分引擎写入。"""
    async def write(self, scores: Sequence[ScoreRef]) -> None: ...


class MetricsReadPort(Protocol):
    """口径显式命名，禁止裸 success_rate（架构文档 §1）。"""
    async def agent_metrics(self, asset_id: Id, window: "Window", tenant_ids: tuple[Id, ...] | None) -> Mapping[str, float]: ...
    async def run_dimension_scores(self, run_id: Id) -> Mapping[str, float]: ...
```

---

## 11. `contracts/improvement/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, Sequence

from ..common import Id
from ..dataset import SampleRef


@dataclass(frozen=True, slots=True)
class ProposalRef:
    id: Id
    workspace_id: Id
    asset_id: Id
    asset_kind: str
    source: Literal["agent", "human", "monitor"]
    title: str
    reason: str
    evidence_trace_ids: tuple[Id, ...]
    proposed_version: str | None
    risk: Literal["low", "medium", "high"]
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime


class ProposalQueryPort(Protocol):
    async def get(self, proposal_id: Id, workspace_id: Id) -> ProposalRef | None: ...
    async def pending_count(self, workspace_id: Id, asset_kind: str) -> int: ...


class RegressionSamplePort(Protocol):
    """由 improvement 实现；observability 提供 Trace 内容。"""
    async def create_from_trace(
        self,
        trace_id: Id,
        dataset_id: Id,
        workspace_id: Id,
        actor: "ActorRef",
    ) -> SampleRef: ...
```

---

## 12. `contracts/delivery/`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol

from ..common import Channel, Id, JsonObject, Window
from ..evaluation import GateDecision


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    asset_id: Id
    workspace_id: Id
    version_id: Id
    from_channel: Channel
    to_channel: Channel
    evidence_ids: tuple[Id, ...]
    reauth_ticket: str | None        # 见架构文档 §5.1.5
    requested_by: Id
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class PromotionOutcome:
    accepted: bool
    decision: GateDecision | None
    bound_channel: Channel | None
    reason: str | None


class ChannelRouterPort(Protocol):
    """影子流量：只复制进影子版本，结果永不返回给真实用户。"""
    async def shadow_copy(self, agent_id: Id, tenant_id: Id, payload: JsonObject) -> None: ...


class BaselineComparatorPort(Protocol):
    async def compare(self, candidate_version_id: Id, baseline_version_id: Id,
                      window: Window) -> Mapping[str, float]: ...
```

---

## 13. 契约测试

每个 Port 的**实现**必须通过 `tests/contracts/test_<port>.py` 的同一套用例。
契约测试写在契约层，实现方负责让它变绿：

| 契约测试 | 断言 |
| --- | --- |
| `test_authorizer_port.py` | 权限矩阵逐格；`credential` 主体不能审查/晋级；跨工作区一律拒绝；租户越界拒绝 |
| `test_asset_query_port.py` | `get_version` 跨工作区返回 `None`；`channel_states` 三通道齐全；`tenants_of_agent` 只返回启用的 |
| `test_sample_reader_port.py` | `tenant_scope` 过滤生效；分页游标稳定；`read_one` 返回的 `expected_output` 不参与 Agent 输入 |
| `test_template_snapshot_port.py` | 冻结后修改模板不影响已取快照；`ad_hoc` 时 `template_id` 为 `None` |
| `test_command_queue_port.py` | 重复 `enqueue` 同 `idempotency_key` 不产生重复命令；租约过期可被重新领取 |
| `test_trace_ingest_port.py` | 同 `(asset_id, external_trace_id, event_id)` 幂等；租户与密钥不一致整批拒收 |
| `test_score_write_port.py` | `ScoreRef` 不可变；`evidence` 必填非空 |

**假实现**（`tests/contracts/fakes/`）与真实实现共享这套用例——
这是并行开发里"上游没写完也能开工"的关键。

---

## 14. 契约变更流程

1. **追加字段**：直接改，`CONTRACT_VERSION` 次版本 +1，通知各 Track。
2. **改字段名 / 改语义 / 删字段**：必须走评审，主版本 +1，并给出迁移说明。
3. **新增 Port**：由消费方提出，在 `contracts/` 声明后通知实现方排期。
4. **新增事件**：在 `EventType` 追加，`event_version` 从 1 起；消费者必须容忍未知事件类型（忽略而非报错）。

### 冻结清单（Track 0 交付）

- [ ] `common.py` 全部枚举与值对象
- [ ] `errors.py` 错误码表（前端同步使用）
- [ ] `events.py` 事件目录与 `EventBusPort`
- [ ] `identity/` —— `AuthorizerPort`、`TenantQueryPort`、`MembershipQueryPort`、`Subject`
- [ ] `asset/` —— `AssetQueryPort`、`AssetSpecPort`、`ArtifactPort`
- [ ] `dataset/` —— `SampleReaderPort`、`SampleWriterPort`
- [ ] `evaluation/` —— `TemplateSnapshotPort`、`EvaluatorRegistryPort`、`TemplateSnapshot`
- [ ] `execution/` —— `RunQueryPort`、`CommandQueuePort`、`RuntimePort`、`CommandEnvelope`
- [ ] `observability/` —— `TraceIngestPort`、`TraceQueryPort`、`ScoreWritePort`、`MetricsReadPort`
- [ ] `improvement/` —— `ProposalQueryPort`、`RegressionSamplePort`
- [ ] `delivery/` —— `ChannelRouterPort`、`BaselineComparatorPort`（P1 前冻结即可）
- [ ] `tests/contracts/` 每个 Port 一套用例 + 内存假实现

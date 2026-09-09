"""跨模块共享的类型、枚举与值对象。

**这是全系统枚举的唯一真源**——前端枚举、数据库存储值、API 文档都以此为准。
新增取值只能追加；改已有取值的字面量等于破坏性变更（见 docs/backend-contracts.md §14）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Mapping, Sequence, TypeAlias, TypeVar

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]

#: 实体 ID，形如 `run_01J8Z9K3M4N5P6Q7R8S9T0V1W2`。
Id: TypeAlias = str

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #


class Channel(StrEnum):
    """部署通道。与 `EvaluationStage` 严格区分——前者是环境，后者是评测时机。"""

    TEST = "test"
    LIVESH = "liversh"
    LIVE = "live"


class VersionLifecycle(StrEnum):
    """版本自身生命周期。「哪个通道正在用」由 ChannelBinding 表达，不是版本状态。"""

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


class EvaluationStage(StrEnum):
    """评测使用阶段（需求说明 §6.2），不是部署环境。"""

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
    """与 RunStatus 正交：暂停时 stage 停在原地，不丢失「做到哪一步」。"""

    PROVISIONING = "provisioning"
    EXECUTING = "executing"
    SCORING = "scoring"
    COMPLETED = "completed"


class ExecutionStatus(StrEnum):
    """Trial 执行侧状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class Verdict(StrEnum):
    """Trial 质量侧判定。与 ExecutionStatus 正交——「跑完了但没达标」≠「没跑起来」。"""

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
    """评估器性质。高风险门禁可要求 deterministic。"""

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


class ScopeKind(StrEnum):
    """得分 / 门禁的统计范围。没有范围的全局分数无法用于业务判断。"""

    CASE = "case"
    TRAJECTORY = "trajectory"
    SPAN = "span"
    RUN = "run"
    ASSET_VERSION = "asset_version"
    WORKSPACE_WINDOW = "workspace_window"
    TENANT = "tenant"


class CredentialKind(StrEnum):
    """机器凭证。三条链互不混用，权限严格收窄。"""

    DEPLOY = "evl"       # 调用已部署 Agent
    TRACE = "evk"        # 只写 Trace
    TENANT_SYNC = "evs"  # 只同步租户清单


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EVALUATOR = "evaluator"
    DEVELOPER = "developer"
    VIEWER = "viewer"


# --------------------------------------------------------------------------- #
# 值对象
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("金额不能为负")

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"币种不一致: {self.currency} vs {other.currency}")
        return Money(self.amount + other.amount, self.currency)


@dataclass(frozen=True, slots=True)
class Ratio:
    """0–1 的比率。API 层用 Field(ge=0, le=1) 卡死，展示层负责乘 100。"""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"比率必须在 [0, 1] 内，收到 {self.value}")

    def as_percent(self) -> float:
        return self.value * 100.0


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("窗口结束时间早于开始时间")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


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

    def messages(self) -> tuple[str, ...]:
        return tuple(f"{issue.field}: {issue.message}" for issue in self.issues)


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Money = field(default_factory=lambda: Money(Decimal("0")))

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

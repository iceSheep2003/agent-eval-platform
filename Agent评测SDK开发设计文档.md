#  Agent 评测 SDK 开发文档

版本：v2.0  
状态：开发基线  
更新时间：2026-09-07  
目标读者：SDK 开发者、Benchmark 适配者、Agent 开发者、平台集成开发者

本文是 `agent-eval-sdk` 的实现规格和使用说明。它只保留已经做出选择的内容；历史讨论、候选方案和被否决的设计留在同目录的调研文档中，不作为实现依据。

## 1. 先给结论

### 1.1 我们到底要开发什么

`agent-eval-sdk` 是一个 Python-first 的 Agent 观测与离线评测 SDK，解决四件事：

1. 用极少的代码记录 Agent、模型、工具、检索器和子 Agent 的执行事实。
2. 用 `evaluate(agent, cases, metrics)` 在本地或 CI 运行可重复的评测。
3. 把最终输出、事件轨迹和评分证据保存为可重放的本地日志。
4. 允许平台通过可选 Sink 接收事件，但平台不可用时本地评测仍然可运行。

SDK 不负责启动 Docker、浏览器、终端或远程沙箱，也不内置任何具体 Benchmark 的答案、Verifier 和数据集。

### 1.2 最终产品拆分

```text
agent-eval-protocol       稳定协议和 JSON Schema
                           TaskSpec / Observation / Action / Event / Score

agent-eval-sdk            Agent 侧埋点 + 普通离线评测 + 本地日志
                           observe / span / evaluate / rescore / CLI

agent-eval-harness        复杂 Benchmark 执行面（后续独立包）
                           Runner / AgentAdapter / BenchmarkAdapter / Sandbox

agent-eval-benchmarks     各 Benchmark 的可安装适配包（独立发布）
                           数据集 / 环境 / 编解码 / Verifier / parity test

agent-eval-platform       平台控制面和展示（不属于 Agent SDK）
                           Run / 权限 / 调度 / 实时 Trace / 报告 / 对比
```

依赖方向必须保持为：

```text
protocol ← sdk
protocol ← harness
protocol ← benchmarks
harness  → benchmarks
sdk      → platform ingest（可选，运行时不强依赖）
```

禁止出现以下依赖：

```text
sdk → 某个具体 Benchmark
sdk → Docker / Browser / Terminal runtime
sdk → LangChain / LangGraph / CrewAI / AutoGen
agent code → hidden verifier / hidden answer
```

### 1.3 使用者应该如何选入口

| 需求 | 使用入口 | 是否需要 Harness |
| --- | --- | --- |
| 评估一个普通 Python Agent 的最终答案 | `evaluate()` | 否 |
| 评估工具调用、步骤和子 Agent | `@observe` + `evaluate()` | 否 |
| 放进 pytest / CI 做回归门禁 | `agent-eval test` 或 pytest 集成 | 否 |
| 不重新运行 Agent，只换评分器 | `rescore()` | 否 |
| 接入 tau-bench、BrowserGym、Terminal-Bench 等环境型任务 | `BenchmarkAdapter` + `Runner` | 是 |
| 把 HTTP/CLI/远程 Agent 接入 Benchmark | `AgentAdapter` | 是 |
| 将结果实时发送到平台 | `HttpSink` | 可选 |

普通用户不需要理解 `Runner`、`Trial`、`Sandbox`；只有 Benchmark 作者和平台执行面才使用它们。

## 2. 设计依据与选型判断

本文不是简单复制某一个项目，而是取各项目中适合本系统的一部分。

### 2.1 采用 DeepEval 的开发者入口

DeepEval 的核心经验是：先用 `@observe` 建立 Trace，再在整条 Trace 或某个组件 Span 上挂指标；同时通过 pytest 和 CLI 进入 CI。它说明 Agent 评测的第一入口应该像写测试，而不是像配置一套分布式调度系统。

本项目采用：

- `@observe` 作为最低侵入的埋点方式；
- `span()` 作为无法使用装饰器时的补充；
- `evaluate()` 作为普通开发者唯一需要记住的执行入口；
- case、trajectory、span 三个评分作用域。

不采用：

- DeepEval 的 `Golden`、内部 Trace 类型作为本项目协议；
- 默认登录云平台；
- 面向所有 Agent 框架的自动包装器。

参考：[DeepEval Agent Evaluation Quickstart](https://deepeval.com/docs/getting-started-agents)。

### 2.2 采用 LangSmith 的 Dataset / Experiment / Evaluator 分离

LangSmith 把离线评测的输入样本、一次应用版本的实验结果、评估函数和生产 Trace 区分开。这个边界对版本比较和线上线下一致很有价值。

本项目采用：

```text
EvaluationCase → EvaluationRun → Trace → Score → Summary
```

其中 `expected_output` 只给 Metric，不传入 Agent；`EvaluationRun` 固化 Agent 版本、Metric 版本和运行配置。

不采用：

- Workspace、Project、Dataset 云端管理对象进入 SDK 核心；
- 将平台上的生产 Run 当成本地协议的唯一来源。

参考：[LangSmith Evaluation Concepts](https://docs.langchain.com/langsmith/evaluation-concepts)。

### 2.3 采用 Braintrust 的文件 / CLI / CI 工作流

Braintrust 的 eval 文件和 CLI 说明：评测必须能在本地文件、脚本和 CI 中可重复运行，不能只依赖 Web Console。

本项目采用：

- 本地 JSONL 事实日志；
- `agent-eval test` 和 `agent-eval score` CLI；
- 固定 seed、样本选择、并发和输出目录；
- JSON 输出，方便 CI 和其他工具消费。

不采用：

- 将远程平台认证设为本地运行前置条件；
- 为了支持 CLI 而让评测逻辑和命令行逻辑重复实现。

参考：[Braintrust CLI Quickstart](https://www.braintrust.dev/docs/reference/cli/quickstart) 和 [`bt eval`](https://www.braintrust.dev/docs/reference/cli/eval)。

### 2.4 采用 Inspect AI 的任务/评分分离与重评分

Inspect AI 把 Task、Dataset、Solver、Scorer、Sandbox 分开，并支持对已有日志重新评分。这正好说明：执行事实和评分逻辑必须解耦。

本项目采用：

- Metric / Evaluator 无状态；
- 评分器只读 Trace，不修改 Trace；
- 原始事件日志是事实源，评分文件可以删除后重新生成；
- 复杂任务的 Sandbox 只属于 Harness。

参考：[Inspect AI Tasks](https://inspect.aisi.org.uk/tasks.html) 和 [Inspect AI 的日志重评分](https://inspect.aisi.org.uk/tasks.html#scoring)。

### 2.5 采用 Harbor 的环境型 Benchmark 分层

Harbor 将 Task、Dataset、Agent、Container Environment、Trial、Job 作为执行面对象，适合 Terminal-Bench、SWE-Bench 等有环境和验证脚本的任务。

本项目只借鉴它的分层，不把它的容器运行时搬进 SDK：

- `BenchmarkAdapter` 拥有任务、环境和 Verifier；
- `AgentAdapter` 拥有 Agent 的接入方式；
- `Runner` 负责控制一次或多次 Trial；
- SDK 只负责 Agent 侧事件和通用评分。

参考：[Harbor Core Concepts](https://www.harborframework.com/docs/core-concepts) 和 [Harbor Evals](https://www.harborframework.com/docs/run-jobs/run-evals)。

### 2.6 对 OpenTelemetry 和 MCP 的定位

OpenTelemetry GenAI 语义约定适合做导出映射，已经覆盖 Agent、Tool、模型调用、Tool Call 和 Token Usage 的一部分字段；但其语义仍会演进。因此 OTel 是可选 Exporter，不是本项目的 canonical event protocol。

MCP 是工具与上下文的连接协议，适合未来作为一种 `ToolAdapter` 或 `Transport`，但不应成为评测 SDK 的领域根模型。评测核心仍然是 Case、Trace、Event 和 Score。

参考：[OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) 和 [MCP Specification](https://modelcontextprotocol.io/specification/2025-03-26/index)。

## 3. 产品边界

### 3.1 SDK v1 必须提供

- Python 3.11+ 支持；
- sync / async Agent 调用；
- `@observe`、`span()`、`emit()`；
- Trace / Span / Event 的内存模型和 JSON 序列化；
- `EvaluationCase`、`Metric`、`Score`、`EvaluationResult`；
- `evaluate()`；
- `rescore()`；
- Memory、Console、JSONL Sink；
- 事件脱敏、大小限制和 Artifact 引用；
- CLI：`test`、`score`、`inspect`；
- pytest 友好，失败可以用普通断言阻断 CI；
- 完整的单元测试和一个 toy Agent 端到端测试。

### 3.2 SDK v1 明确不提供

- Benchmark 数据集和具体 Verifier；
- Docker、浏览器、终端、远程执行和凭据隔离；
- Runner、Job、Worker、队列和多机调度；
- Agent 框架专用自动适配器；
- 默认将输入、输出或完整消息发送到云端；
- 默认记录隐藏 Chain-of-Thought；
- 强制绑定 LangSmith、Braintrust、Confident AI 或自建平台；
- 通过 Metric 对象内部状态保存上一次运行结果。

## 4. 核心概念：只保留一套词汇

### 4.1 对象关系

```text
EvaluationRun
  └── EvaluationCaseRun（每个 Case 一次或多次尝试）
        └── Trace
              ├── Span tree（有开始/结束的操作）
              └── Event stream（离散事实）
        └── Score[]（评分结果）
```

### 4.2 对象定义

| 对象 | 含义 | 是否可变 |
| --- | --- | --- |
| `EvaluationCase` | 给 Agent 的输入和只供 Metric 使用的参考信息 | 不可变 |
| `EvaluationRun` | 一次数据集、Agent、Metric、配置的执行集合 | 运行期状态可变，落盘后不可变 |
| `Trace` | 一个 Case Run 的完整执行事实 | append-only |
| `Span` | 一段有时长的操作，如 Agent、LLM、Tool | 关闭后不可变 |
| `Event` | 一个时间点事实，如 Action、Observation、错误 | 不可变 |
| `Metric` | 从目标和事实计算 Score 的无状态对象 | 配置只读 |
| `Score` | 一个 Metric 的一次判定和证据 | 不可变 |
| `Artifact` | 大文本、图片、文件、日志的外部引用 | 内容不可变 |

### 4.3 `Trace` 不是 `Score`

Trace 记录发生了什么；Score 解释这些事实是否满足某项质量标准。

```text
Trace  = 事实
Metric = 规则
Score  = 规则对事实的结果
```

Metric 不得修改 Trace、不得写数据库、不得调用平台 API。这样才能做到并发安全、缓存和重评分。

## 5. 最短可用路径：五分钟跑通

### 5.1 安装

```bash
python -m pip install agent-eval-sdk
```

SDK 默认只安装本地评测所需依赖，不安装 Docker、浏览器、具体 Benchmark 和平台客户端。可选能力使用 extras：

```bash
python -m pip install 'agent-eval-sdk[http]'       # HttpSink
python -m pip install 'agent-eval-sdk[pytest]'     # pytest 插件
```

### 5.2 给 Agent 加一个埋点

```python
from agent_eval import observe


@observe(kind="agent", name="support_agent")
async def support_agent(user_input: str) -> str:
    order = await lookup_order("A001")
    if order["status"] == "refundable":
        return "该订单可以退款。"
    return "该订单不能退款。"


@observe(kind="tool", name="lookup_order")
async def lookup_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "refundable"}
```

`@observe` 的要求：

- 不改变原函数的返回值、异常类型和调用方式；
- 同时支持普通函数和 async 函数；
- 自动建立父子 Span；
- Agent 代码不在评测上下文中运行时，默认不发远程事件；
- 发生异常时先关闭 Span，再原样抛出异常；
- 不记录不可验证的隐藏思维链。

### 5.3 写一个 Case 和一个 Metric

```python
from agent_eval import EvaluationCase, Score, evaluate


class ContainsRefundDecision:
    name = "contains_refund_decision"
    version = "1.0.0"
    scope = "case"

    async def score(self, target):
        passed = "可以退款" in str(target.output)
        return Score(
            metric=self.name,
            metric_version=self.version,
            value=1.0 if passed else 0.0,
            status="pass" if passed else "fail",
            reason=None if passed else "最终答案没有包含退款结论",
            evidence=target.trace.find_events(kind="agent"),
        )


result = await evaluate(
    agent=support_agent,
    cases=[
        EvaluationCase(
            id="refund-001",
            input="请判断订单 A001 是否可以退款",
            expected_output={"refundable": True},
        )
    ],
    metrics=[ContainsRefundDecision()],
    output_dir=".agent-eval/runs/refund-smoke",
)

assert result.summary.pass_rate == 1.0
```

`expected_output` 不会传入 `support_agent`；它只被 Metric 读取。Metric 如果需要参考答案，必须明确从 `target.case` 读取。

### 5.4 运行和查看结果

```bash
agent-eval test tests/test_support_agent.py
agent-eval inspect .agent-eval/runs/refund-smoke
```

默认输出目录：

```text
.agent-eval/runs/<run_id>/
├── run.json          # 运行配置、版本、状态和统计
├── cases.jsonl       # Case 快照，不含隐藏信息
├── events.jsonl      # append-only 事实源
├── scores.jsonl      # 可删除并重新生成
├── summary.json      # 聚合结果
└── artifacts/        # 大对象和附件
```

## 6. 公共 API 规格

### 6.1 `observe`

```python
@observe(
    kind="tool",
    name="lookup_order",
    capture_input=True,
    capture_output=True,
    attributes={"domain": "orders"},
)
def lookup_order(order_id: str) -> dict:
    ...
```

参数：

- `kind`：`agent`、`workflow`、`llm`、`tool`、`retriever`、`guardrail`、`handoff`、`custom`；
- `name`：稳定、可读、用于过滤和聚合；
- `capture_input/output`：是否捕获内容，默认遵守全局隐私配置；
- `attributes`：低基数结构化属性，不放大段文本。

### 6.2 `span`

装饰器不适合包裹时使用手动 Span：

```python
from agent_eval import span


async def call_model(messages, client):
    async with span(
        kind="llm",
        name="chat",
        input=messages,
        attributes={"model": "example-model"},
    ) as current:
        response = await client.chat(messages=messages)
        current.set_output(response.text)
        current.set_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return response
```

上下文 API：

```python
current_trace() -> TraceHandle | None
current_span() -> SpanHandle | None
span(...) -> sync/async context manager
emit(event_type, payload, ...) -> EventHandle
```

所有上下文必须用 `contextvars` 隔离；并发 Case 不得共享当前 Trace 或 Span。

### 6.3 `EvaluationCase`

```python
@dataclass(frozen=True)
class EvaluationCase:
    id: str
    input: JsonValue | Any
    expected_output: JsonValue | Any | None = None
    context: tuple[JsonValue | Any, ...] = ()
    expected_actions: tuple[ExpectedAction, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
```

规则：

- `id` 在一个 Run 内唯一；
- `input` 是唯一默认传给 Agent 的数据；
- `expected_output`、`expected_actions` 和私有 metadata 不能自动进入 Agent；
- 需要给 Agent 的上下文必须显式构造到 `input` 或通过交互 Session 发送。

### 6.4 `Metric`

```python
class Metric(Protocol):
    name: str
    version: str
    scope: Literal["case", "trajectory", "span"]

    async def score(self, target: EvaluationTarget) -> Score | list[Score]:
        ...
```

Metric 只保存配置，不保存运行结果。一个 Metric 实例可以安全地被多个 Case 并发调用。

三种 scope：

| scope | 输入 | 示例 |
| --- | --- | --- |
| `case` | Case + 最终输出 + Trace | AnswerExactMatch、JSON Schema |
| `trajectory` | Case + 有序事件流 + Trace | TaskCompletion、StepEfficiency |
| `span` | Case + 单个 Span | ToolNameCorrectness、ToolLatency |

第一版内置 Metric：

- `AnswerExactMatch`；
- `AnswerContains`；
- `AnswerJsonSchema`；
- `TaskCompletion`；
- `NoInvalidAction`；
- `StepEfficiency`；
- `ToolNameCorrectness`；
- `ToolArgumentSchema`；
- `ToolSuccess`；
- `LlmCallLatency`。

LLM-as-a-judge 不是默认 Metric。它必须作为显式可选依赖，记录 judge model、prompt 版本、输入摘要、成本和失败原因。

### 6.5 `Score`

```python
@dataclass(frozen=True)
class Score:
    metric: str
    metric_version: str
    value: float | int | bool | str | None
    status: Literal["pass", "fail", "skip", "error"]
    reason: str | None
    evidence: tuple[EvidenceRef, ...]
    evaluator: EvaluatorInfo | None = None
    duration_ms: float | None = None
    cost_usd: float | None = None
```

`evidence` 必须尽量引用 `event_id`、`span_id` 或 `artifact_id`，不允许只返回不可定位的自然语言结论。

### 6.6 `EvaluationResult`

```python
@dataclass(frozen=True)
class EvaluationResult:
    run_id: str
    case_results: tuple[CaseResult, ...]
    summary: Summary
    log_dir: str
    status: Literal["completed", "partial", "failed"]
```

`summary` 至少包含：

```text
case_count
agent_success_count
agent_error_count
timeout_count
metric_error_count
pass_count
fail_count
skip_count
pass_rate
```

## 7. `evaluate()` 的执行语义

### 7.1 函数签名

```python
async def evaluate(
    *,
    agent: Callable[[Any], Any],
    cases: Iterable[EvaluationCase],
    metrics: Iterable[Metric] = (),
    name: str | None = None,
    concurrency: int = 1,
    timeout: float | None = None,
    seed: int | None = None,
    sink: EventSink | None = None,
    output_dir: str | Path | None = None,
) -> EvaluationResult:
    ...
```

同步 Agent 通过普通函数传入；async Agent 直接传入。SDK 内部统一为 async 执行模型，但不能改变用户函数的异常语义。

### 7.2 唯一执行顺序

```text
固化 Run 配置和版本
  → 加载 Case
  → 每个 Case 创建独立 Trace
  → 调用 Agent(input)
  → 捕获 output / exception / timeout / cancellation
  → 关闭 Trace
  → 运行 case / trajectory / span Metric
  → 写入 scores.jsonl
  → 聚合 Summary
  → flush Sink
  → 返回 EvaluationResult
```

### 7.3 错误语义

- Agent 抛出的异常：记录为 Agent Error，保留原始错误类型和 Trace，继续处理其他 Case；
- Case 超时：状态为 `timeout`，不得伪装成普通 Agent Error；
- Metric 出错：返回 `status="error"` 的 Score，不覆盖 Agent 结果；
- Sink 出错：本地 Durable JSONL 仍然必须可用，平台 Sink 默认不得覆盖业务结果；
- Run 级基础设施错误：可以终止 Run，并在 `run.json` 中明确标记；
- v1 不自动重试业务错误；基础设施重试生成新的 `attempt_id`，不能覆盖旧 Trace。

### 7.4 并发和确定性

- `concurrency=1` 是默认值，便于调试；
- 并发 Case 必须各自拥有 Context、Trace、attempt_id；
- 事件序号在单个 Trace 内单调递增；跨 Trace 不要求全局递增；
- `seed` 只控制 SDK 自己的采样和选择，不宣称能控制外部模型的全部随机性；
- 结果中保存 concurrency、seed、超时、版本和环境摘要。

## 8. Trace 和事件协议

### 8.1 Span 记录

```python
@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    kind: SpanKind
    name: str
    status: Literal["running", "ok", "error", "cancelled"]
    started_at: datetime
    ended_at: datetime | None
    input_ref: ValueRef | None
    output_ref: ValueRef | None
    attributes: Mapping[str, JsonValue]
    usage: Usage | None
    error: ErrorInfo | None
```

### 8.2 Event 记录

```python
@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    trace_id: str
    span_id: str | None
    sequence: int
    event_type: str
    actor: Literal[
        "agent", "model", "tool", "environment", "runtime", "evaluator"
    ]
    timestamp: datetime
    payload: Mapping[str, JsonValue]
    visibility: Literal["public", "internal", "secret"]
```

推荐事件类型：

```text
trace_started / trace_finished
agent_started / agent_finished
llm_started / llm_finished
tool_called / tool_returned
retrieval_started / retrieval_finished
observation_emitted / action_proposed
error_raised / cancellation_requested
artifact_created / score_emitted
```

事件是 append-only 事实。UI 的 Step、Trace Tree、指标输入和平台报告都从事件投影而来。

### 8.3 内容捕获策略

默认捕获结构化摘要和必要字段；大对象使用 Artifact 引用：

```text
ValueRef = inline JSON | artifact_id + mime_type + size + sha256
```

必须支持：

- 字段级 redact；
- `capture_input=False` / `capture_output=False`；
- header、token、cookie、API Key 自动过滤；
- 单字段和单 Artifact 大小限制；
- Artifact 路径允许列表；
- JSON 序列化失败时记录类型和摘要，不让日志写入破坏 Agent。

不默认记录隐藏 Chain-of-Thought；只记录公开消息、工具调用、Observation、Action、结构化计划、最终答案和可验证证据。

### 8.4 Sink

```python
class EventSink(Protocol):
    async def emit(self, event: TraceEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

实现优先级：

1. `MemorySink`：单元测试；
2. `ConsoleSink`：本地调试；
3. `JsonlSink`：默认 Durable 事实源；
4. `HttpSink`：平台批量上传；
5. `OtlpSink`：可选外部观测系统映射。

HTTP Sink 必须支持 batch、超时、指数退避、幂等键和本地失败缓冲。平台协议建议：

```http
POST /v1/evaluation-runs/{run_id}/traces/{trace_id}/events
Content-Type: application/x-ndjson
Idempotency-Key: <trace_id>:<sequence_start>:<sequence_end>
```

服务器必须允许乱序到达和部分接受；客户端必须能够根据 ack 恢复未确认事件。

## 9. 复杂 Benchmark 的扩展边界

### 9.1 什么时候进入 Harness

以下任一条件成立，就不要继续扩展 `evaluate()`：

- 环境有状态，下一次 Observation 依赖上一次 Action；
- Action 需要 schema、权限、预算或幂等校验；
- Verifier 拥有 Agent 不可见的隐藏状态；
- 需要 Docker、浏览器、终端或远程沙箱；
- 需要多个 Agent、Trial、Job 或大规模并发；
- 需要把外部 HTTP/CLI Agent 接入统一运行循环。

此时使用 `agent-eval-harness`，SDK 只负责 Agent 侧协议和事件。

### 9.2 交互协议

```text
Runner → PublicTaskSpec
Runner → Observation
Agent  → Action
Runner → Observation
Runner → finish / abort
Runner → TrialResult
```

公开任务和私有任务必须分离：

```text
PublicTaskSpec       发给 Agent，只包含 instruction、公开上下文、允许动作和限制
PrivateTaskContext   只给 Adapter / Verifier，包含答案、隐藏状态和私有凭证
```

`expected_output`、隐藏状态、测试答案、Verifier 实现和私有凭证不得进入 PublicTaskSpec。

### 9.3 `Action` 的最小形态

```python
@dataclass(frozen=True)
class Action:
    id: str
    kind: Literal[
        "tool_call", "message", "file_operation", "submit", "finish", "abort"
    ]
    name: str | None
    arguments: Mapping[str, JsonValue]
    idempotency_key: str | None = None
```

Runtime 在真正执行前检查：Schema、权限、当前状态、预算、幂等键和高风险审批。

### 9.4 Adapter 接口

Benchmark 侧：

```python
class BenchmarkAdapter(Protocol):
    id: str
    version: str

    async def list_cases(self, selector: Selector) -> AsyncIterator[str]: ...
    async def prepare(self, case_id: str, run: RunContext) -> PublicTaskSpec: ...
    async def reset(self, session: SessionContext) -> Observation: ...
    async def step(self, session: SessionContext, action: Action) -> list[Observation]: ...
    async def finish(self, session: SessionContext) -> TrialResult: ...
```

Agent 侧：

```python
class AgentAdapter(Protocol):
    async def provision(self, task: PublicTaskSpec, run: RunContext) -> AgentHandle: ...
    async def send_task(self, handle: AgentHandle, task: PublicTaskSpec) -> None: ...
    async def send_observation(self, handle: AgentHandle, observation: Observation) -> None: ...
    async def receive_action(self, handle: AgentHandle, timeout: float) -> Action | None: ...
    async def close(self, handle: AgentHandle) -> None: ...
```

第一批实现只需要：

- `InProcessAgentAdapter`：本地 toy benchmark；
- `HttpAgentAdapter`：外部 Agent 服务；
- `JsonlEventSink`：本地重放。

MCP、ACP、A2A 是后续 Transport / Adapter 选项，不进入 Runner 核心。

### 9.5 Benchmark 包规范

```text
agent-eval-benchmarks/
└── <benchmark-id>/
    ├── manifest.yaml
    ├── adapter.py
    ├── dataset.py
    ├── environment.py
    ├── verifier.py
    ├── codecs.py
    ├── fixtures/
    ├── tests/test_adapter_contract.py
    ├── tests/test_parity.py
    └── README.md
```

```yaml
id: tau2
version: 3.0.0
adapter_version: 0.1.0
interaction: tool_loop
requires_environment: true
requires_hidden_verifier: true
supports_replay: true
```

Benchmark 包必须能够独立安装和升级；Agent SDK 不得 import 它们。

## 10. 重评分、比较和可重放

### 10.1 两个不同入口

```python
await evaluate(...)                         # 执行 Agent，产生 Trace 和 Score
await rescore(log_dir, metrics=[...])       # 不执行 Agent，只重算 Score
```

`rescore()` 必须读取 `events.jsonl` 和 Case 快照，不能从旧 `scores.jsonl` 推导新的评分结果。

### 10.2 评分版本

每个 Score 必须保存：

```text
metric.name
metric.version
evaluator implementation version
judge model / prompt version（如果有）
input trace version
evidence refs
```

改 Metric 逻辑必须提升 Metric 版本；改事件 Schema 必须提升 protocol 版本。旧日志可以在兼容读取器下重评分，不能静默覆盖历史 Score。

### 10.3 比较实验

v1 先输出机器可读 JSON，不急于实现完整平台：

```bash
agent-eval compare \
  .agent-eval/runs/baseline \
  .agent-eval/runs/candidate \
  --metric task_completion \
  --json
```

比较至少显示：样本交集、通过率变化、失败 Case、Metric 版本差异和 Agent 错误率。平均分变化不能掩盖失败归因。

## 11. CLI 与 pytest

### 11.1 CLI 命令

第一版只实现三个命令：

```bash
agent-eval test tests/                         # 发现并运行评测测试
agent-eval score RUN_DIR --metric my_metric    # 对已有日志重评分
agent-eval inspect RUN_DIR                     # 查看本地 Run 摘要和失败证据
```

第二阶段再加入：

```bash
agent-eval compare RUN_A RUN_B
agent-eval retry RUN_DIR --only infrastructure
```

CLI 是 Python API 的薄封装，不能有自己的第二套执行语义。

### 11.2 pytest 集成

推荐写成普通测试：

```python
import pytest
from agent_eval import EvaluationCase, evaluate


@pytest.mark.agent_eval
@pytest.mark.asyncio
async def test_support_agent_smoke():
    result = await evaluate(
        agent=support_agent,
        cases=[EvaluationCase(id="refund-001", input="订单 A001 能退款吗？")],
        metrics=[ContainsRefundDecision()],
    )
    assert result.summary.pass_rate >= 1.0
```

pytest 插件只负责标记、收集和展示；`evaluate()` 仍然是唯一执行内核。

## 12. 隐私、安全与数据治理

### 12.1 SDK 默认行为

- 默认本地运行，不发送远程数据；
- `HttpSink` 必须显式配置；
- 输入、输出和工具参数可以关闭捕获；
- Secret、Cookie、Authorization、API Key 默认脱敏；
- Artifact 只允许写入配置目录；
- 日志内容有大小上限；
- Secret visibility 事件不得发送给不具备权限的 Sink。

### 12.2 Harness / 平台责任

- Verifier、答案和隐藏状态只在执行面可见；
- Agent 不得读取 Benchmark 包的 hidden 目录；
- 工具动作执行前检查 Schema、权限、预算和当前状态；
- Trial 使用独立凭据和 Session；
- 网络、文件和进程隔离由 Harness / Sandbox 提供，不由 SDK 假设或伪造。

## 13. 测试和验收

### 13.1 SDK 单元测试

必须覆盖：

1. sync / async `observe`；
2. 嵌套 Span 和 parent 关系；
3. exception / timeout / cancellation 终态；
4. 并发 Case 的 Context 隔离；
5. Sink 失败不改变 Agent 返回值和异常；
6. JSONL 完整恢复 Trace；
7. 单 Trace 事件序号单调递增；
8. HTTP 重复事件幂等；
9. Artifact 大小限制和脱敏；
10. 无评测上下文时不发送远程事件。

### 13.2 Metric 测试

每个 Metric 至少有：

- 通过；
- 失败；
- 缺字段；
- Trace 不完整；
- Metric 自身异常；
- evidence 指向正确 Event / Span。

### 13.3 端到端验收

用一个确定性的 toy benchmark 验证完整链路：

```text
BenchmarkAdapter
  → InProcessAgentAdapter
  → Agent SDK
  → Trace / Event
  → Metric
  → Score
  → JSONL
  → rescore
```

### 13.4 Definition of Done

第一版只有同时满足以下条件才算完成：

- 普通 Python Agent 只增加少量 `@observe` 就能运行；
- 不安装具体 Benchmark 也能本地完成评测；
- sync / async 和并发 Case 不串 Trace；
- 平台不可用时 JSONL 仍可运行；
- 原始 Trace 可离线重评分；
- Score 能定位到具体 Event、Span 或 Artifact；
- Agent、Metric、Sink、Run 错误可分别识别；
- SDK 核心包不包含 Benchmark 答案、Verifier、容器和浏览器依赖；
- CLI、Python API 和 pytest 共享同一个执行内核。

## 14. 分阶段开发计划

### P0：冻结协议和边界

- 冻结 `EvaluationCase`、`TraceEvent`、`SpanRecord`、`Score` 的 JSON Schema；
- 明确 `PublicTaskSpec` / `PrivateTaskContext`；
- 确定 Python 3.11+ 和版本策略；
- 写 protocol contract test；
- 不实现平台、Benchmark 和自动框架适配。

### P1：Trace Core

- `observe`、`span`、`current_trace`、`current_span`；
- contextvars 隔离；
- Memory / Console / JSONL Sink；
- 序列化、脱敏和 Artifact；
- sync / async 单元测试。

### P2：本地评测闭环

- `EvaluationCase`、`Metric`、`Score`；
- `evaluate()` 和结果聚合；
- timeout、cancel、并发和错误隔离；
- 第一批确定性 Metric；
- `agent-eval test` 和 pytest 集成。

### P3：重评分和平台 Sink

- `rescore()`；
- Metric / Protocol 版本记录；
- HTTP batch ingest、ack、重试和本地缓冲；
- 实时 Trace 展示联调；
- 可选 OTel Exporter。

### P4：独立 Harness 和 Benchmark

- `agent-eval-harness`；
- InProcess / HTTP / CLI AgentAdapter；
- toy Benchmark；
- 一个真实环境型 Benchmark Adapter；
- parity test 和完整 Trial 重放。

## 15. 开发约束清单

实现时必须遵守：

1. 先实现 Trace Core，再实现复杂 Benchmark。
2. `evaluate()` 是普通开发者入口；`Runner` 只属于 Harness。
3. Trace 是 append-only 事实日志，Metric 只能读取 Trace。
4. Metric 无状态，结果通过 `Score` 返回。
5. 所有 async context 使用 `contextvars`，禁止全局 current trace。
6. Agent 原始异常和 Metric 异常必须分开记录。
7. 本地 JSONL 是默认可恢复路径，平台是可选能力。
8. 不重新定义已有 `TaskSpec / Observation / Action / TraceEvent` 的含义；如 Schema 不兼容，必须单独升级 protocol 版本。
9. Benchmark、Verifier、Sandbox 不进入 Agent SDK 的安装依赖。
10. 每完成一个阶段，都要用 toy Agent 和 toy Case 跑一次端到端测试。

最终目标：

```text
给定一个普通 Python Agent
  → 用 @observe 记录执行事实
  → evaluate() 运行 Case
  → 得到 Trace、Score 和失败证据
  → JSONL 保存并可 rescore
  → 需要时再由 HttpSink 发送到平台
```

对于复杂 Benchmark：

```text
BenchmarkAdapter 提供环境和 Verifier
  → Harness 控制 Trial 和 Action 循环
  → AgentAdapter 接入 Agent
  → Agent 使用同一个 SDK 记录 Trace
  → 平台或本地读取同一种 Event / Score
```

## 16. 参考资料

- [DeepEval Agent Evaluation Quickstart](https://deepeval.com/docs/getting-started-agents)
- [LangSmith Evaluation Concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
- [LangSmith Evaluation Quickstart](https://docs.langchain.com/langsmith/evaluation-quickstart)
- [Braintrust CLI Quickstart](https://www.braintrust.dev/docs/reference/cli/quickstart)
- [Braintrust `bt eval`](https://www.braintrust.dev/docs/reference/cli/eval)
- [Inspect AI Tasks](https://inspect.aisi.org.uk/tasks.html)
- [Harbor Core Concepts](https://www.harborframework.com/docs/core-concepts)
- [Harbor Evals](https://www.harborframework.com/docs/run-jobs/run-evals)
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/specification/2025-03-26/index)

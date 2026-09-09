# Agent 评测 SDK v2 重新设计方案

更新时间：2026-09-07

## 0. SDK 在整个评测系统中的位置

前面的设计把 SDK 过度靠近了平台侧 Runner。结合项目已有的“控制面 + 执行面”设计，SDK 的正确位置应当是 **被测 Agent 的执行侧 SDK，以及平台与 Agent 之间的协议实现**。

完整系统应当这样分工：

```text
控制面
  管理 AgentVersion、Benchmark、评测模板、Run 和权限
        ↓ 创建 Trial / Session
评测执行面
  加载 BenchmarkAdapter、启动环境、校验 Action、控制预算和隔离
        ↕ TaskSpec / Observation / Action / Event
Agent Evaluation SDK
  在 Agent 代码包内建立 Session、调用 Agent 逻辑、提交 Action、上报 Event
        ↓
被测 Agent 的业务逻辑
```

因此 SDK 不负责：

- 管理组织、用户、Agent 注册和评测报告；
- 代替平台启动所有 Benchmark 环境；
- 重新实现多租户队列、Worker 和 Web Console；
- 解析某个 Agent 框架的内部 Graph、Node 或 Span；
- 把 Langfuse、Inspect 或 Braintrust 作为核心运行时。

SDK 负责：

- 让 Agent 代码接收公开 `TaskSpec` 和 `Observation`；
- 将 Agent 的行为转换成统一 `Action`；
- 处理 Session 生命周期、取消、心跳、Artifact 和 Event；
- 在本地开发时提供一个轻量 Runner 做冒烟测试；
- 让同一个 Agent 包可以被平台放入不同 Benchmark 的 Session 中运行。

换句话说，**BenchmarkAdapter 在平台/执行面，Agent Evaluation SDK 在 Agent/接入面，双方通过已有协议交互。** Agent 不直接导入 tau2、Terminal-Bench 或 BrowserGym 的代码，也不需要知道当前运行的是哪一个 Benchmark。

## 0.1 SDK 的实际使用方式

Agent 开发者只需要在自己的 Agent 代码包中使用 SDK：

```python
from agent_eval.agent import AgentServer, AgentContext

class SupportAgent:
    async def decide(self, context: AgentContext):
        # 业务 Agent 只读取 context.observations，返回统一 Action
        return await self.plan_next_action(context)

server = AgentServer(agent=SupportAgent())
server.serve()
```

平台创建一次 Trial 后，交互关系是：

```text
平台 Runtime
  → send_task(PublicTaskSpec)
  → send_observation(Observation)
  ← receive_action(Action)
  → BenchmarkAdapter.step(Action)
  ← Observation
  → ...
  ← TrialResult / Artifact / Event
```

本地开发者则可以不用启动平台，直接用同一个 Agent SDK 做 smoke run：

```python
from agent_eval import local_run

result = await local_run(
    agent=SupportAgent(),
    task="fixtures/refund-task.json",
    environment="fixtures/refund-environment.py",
)
```

`local_run()` 只是平台 Session 协议的本地实现，不是第二套 Agent 运行模型。

## 0.2 SDK、平台和 Benchmark 的调用方向

```text
Benchmark 作者
  实现 BenchmarkAdapter
  提供 TaskSpec、环境、Observation、Verifier

平台执行面
  选择 BenchmarkAdapter
  创建 Session
  通过 AgentAdapter / Transport 连接 SDK

Agent 开发者
  使用 Agent Evaluation SDK
  实现自己的 decide / handle / plan
  返回 Action

评测系统
  收集 Event
  执行 Source Verifier 和 Platform Evaluator
  生成报告
```

SDK 是“Agent 如何参加评测”的产品，不是“平台如何管理评测”的产品。

## 1. 设计结论

这个 SDK 的定位应该是：

> 一个以既有 `TaskSpec / Observation / Action / Event` 协议为核心，帮助被测 Agent 接入评测 Session，并支持本地复现的轻量 SDK。

它不是：

- 通用 Agent 编排框架；
- Langfuse 的 Trace SDK；
- 所有 Agent 框架的兼容层；
- 一个把所有 Benchmark 内置进来的大平台；
- 远程沙箱和任务调度系统的集合。

它需要解决的是一个明确问题：

```text
同一个 Agent 接入协议
        ×
多个 BenchmarkAdapter 提供的任务环境
        ×
平台或本地 Session Runtime
        → 可比较的 Trial / Event / Score
```

## 2. 现有协议应作为 SDK 的公开基础

项目已有的《评测协议与 Agent 接入规范》已经定义了正确的公共边界：

```text
TaskSpec
Observation
Action
BenchmarkAdapter
AgentAdapter
Runner
TraceEvent
ScoreResult
```

因此，不再另起一套 `BenchmarkPack` 运行协议。`BenchmarkPack` 如果保留，只表示一个可安装、可版本化的 BenchmarkAdapter 分发包。

### 2.1 TaskSpec

`TaskSpec` 是 Benchmark 经过适配后暴露给 Agent 的任务契约，包含：

```text
task_id
benchmark_id / benchmark_version / adapter_version
instruction / goal
visible context
allowed actions
limits
policy and permissions
```

`expected_output`、隐藏状态、测试答案、verifier 实现和私有凭证不能进入发送给 Agent 的公开 TaskSpec。建议在 SDK 内部拆成：

```python
PublicTaskSpec       # 发送给 Agent
PrivateTaskContext   # 只给 BenchmarkAdapter / Verifier
```

对外可以继续使用原来的 TaskSpec JSON 结构，但 `AgentAdapter.send_task()` 必须接收公开投影，而不是内部完整对象。

### 2.2 Observation

Observation 是环境给 Agent 的输入，不是完整环境状态：

```text
observation_id
session_id
type
source
content / artifact_ref
is_error
timestamp
visibility
reply_to
```

`content` 支持文本、结构化 JSON、图片、文件和环境事件。大文件和截图应使用 Artifact 引用，不把二进制直接塞入每个 Event。

### 2.3 Action

Action 是 Agent 给 Runtime 的唯一行为出口。原有的 `name + arguments` 结构保留，但应增加 `kind`：

```text
tool_call       调用 Benchmark 暴露的工具
message         给用户或其他 Agent 发消息
file_operation  修改或提交文件
submit          提交最终结果
finish          声明结束
abort           主动终止
```

Runtime 必须在动作真正执行前检查：Schema、权限、当前状态、预算、幂等键和高风险审批。

### 2.4 Event

Event 是 append-only 的事实记录，不等同于 Langfuse Span，也不等同于 UI Trace：

```text
task_received
observation_emitted
action_proposed
action_validated
action_started
action_completed
environment_changed
agent_message
verifier_completed
score_emitted
runtime_error
```

所有 UI Trace、Step、指标和报告都从 Event 投影出来，原始 Event 不允许被覆盖。

## 3. SDK 分层

```text
agent-eval-protocol
  纯数据结构、JSON Schema、错误码、版本兼容规则

agent-eval-sdk
  AgentServer、AgentContext、SessionClient、Action、Artifact、Event
  以及用于本地冒烟的 local_run

agent-eval-harness（平台执行面，可与 SDK 同仓库但不放入 Agent 包）
  Runner、BenchmarkAdapter、AgentAdapter、预算、取消、重试和实验编排

agent-eval-benchmarks
  BenchmarkAdapter 的可安装实现和 parity 测试

agent-eval-transports
  Native、HTTP、CLI、MCP、ACP、代码包等 AgentAdapter 实现

agent-eval-server（后续）
  API、队列、Worker、对象存储、权限和 Web Console
```

第一版不必拆成多个发布仓库，但发布时应至少提供轻量的 `agent-eval-sdk` 安装包；平台侧的 `agent-eval-harness` 和 BenchmarkAdapter 不应被自动安装进被测 Agent 环境。这样 Agent 包不会携带 Benchmark 答案、验证器和平台凭证。

## 4. 整个系统的运行时关系

```text
EvaluationRun
  └── Trial = AgentVersion × TaskRef × Repetition × Seed
        └── Session
              ├── BenchmarkAdapter
              ├── AgentAdapter
              ├── EventSink
              ├── PolicyGuard
              └── ScorePipeline
```

`Run` 是一组可比较的实验配置，`Trial` 是一个独立尝试，`Session` 是单个 Agent 与单个 Benchmark 任务的交互生命周期。

### 4.1 平台 Runner 只负责控制，不负责 Benchmark 语义

```python
async def run_trial(
    benchmark: BenchmarkAdapter,
    agent: AgentAdapter,
    task_id: str,
    context: RunContext,
) -> TrialResult:
    task = await benchmark.prepare(task_id, context)
    handle = await agent.provision(task, context)
    session = await create_session(task, handle, context)

    await agent.start(handle)
    await agent.send_task(handle, task.public_view())
    observation = await benchmark.reset(session)

    while not session.terminal:
        await events.emit("observation_emitted", observation)
        await agent.send_observation(handle, observation)
        action = await agent.receive_action(handle, timeout=session.step_timeout)

        if action is None:
            await session.fail("agent.no_action")
            break

        await validate_action(action, task, session.policy)
        await events.emit("action_validated", action)

        if action.kind == "finish":
            observations = await benchmark.finish(session, action)
        elif action.kind == "abort":
            await session.abort(action)
            break
        else:
            observations = await benchmark.step(session, action)

        for item in observations:
            await events.emit("observation_emitted", item)
        observation = observations[-1] if observations else None

    source_score = await benchmark.score(session)
    platform_scores = await evaluate_trial(session.events, source_score)
    artifacts = await agent.collect_artifacts(handle)
    await agent.stop(handle, session.end_reason)
    await agent.cleanup(handle)
    await benchmark.cleanup(session)
    return TrialResult(source_score, platform_scores, artifacts, session.events)
```

Runner 不知道 `tau2` 的退款规则、不知道 BrowserGym 的 DOM、不知道 Terminal-Bench 的测试脚本。它只知道何时准备任务、发送观测、接收动作、记录事实和结束 Trial。

## 5. BenchmarkAdapter 的责任

已有接口应继续使用：

```python
class BenchmarkAdapter(Protocol):
    id: str
    version: str

    async def list_tasks(self, query: TaskQuery) -> list[TaskRef]: ...
    async def prepare(self, task_id: str, run: RunContext) -> TaskSpec: ...
    async def reset(self, session: SessionContext) -> Observation: ...
    async def step(self, session: SessionContext, action: Action) -> list[Observation]: ...
    async def finish(self, session: SessionContext, action: Action) -> list[Observation]: ...
    async def score(self, session: SessionContext) -> ScoreResult: ...
    async def cleanup(self, session: SessionContext) -> None: ...
```

BenchmarkAdapter 负责所有 Benchmark 特有的内容：

- 任务加载和数据 split；
- 环境启动、重置和销毁；
- 原生 observation 到统一 Observation 的转换；
- 统一 Action 到原生工具、浏览器、终端或 API 的转换；
- 隐藏状态、测试脚本和原始 verifier；
- 原始 reward、pass/fail 或测试结果；
- 与原始 benchmark 的 parity 验证。

一个 BenchmarkAdapter 分发包建议为：

```text
tau2-adapter/
├── manifest.yaml
├── adapter.py
├── task_loader.py
├── environment.py
├── codecs.py
├── verifier.py
├── parity/
├── requirements.lock
└── README.md
```

它不是 Agent 框架适配器，也不应该调用 Agent 的内部 API。

## 6. AgentAdapter 的责任

`AgentAdapter` 不表示“为 LangGraph 写一个转换器”。它表示 Agent 与 Runner 的最小通信边界：

```python
class AgentAdapter(Protocol):
    id: str
    version: str

    async def provision(self, task: TaskSpec, run: RunContext) -> AgentHandle: ...
    async def start(self, handle: AgentHandle) -> None: ...
    async def send_task(self, handle: AgentHandle, task: TaskSpec) -> None: ...
    async def send_observation(self, handle: AgentHandle, observation: Observation) -> None: ...
    async def receive_action(self, handle: AgentHandle, timeout: float) -> Action | None: ...
    async def stop(self, handle: AgentHandle, reason: str) -> None: ...
    async def collect_artifacts(self, handle: AgentHandle) -> list[Artifact]: ...
    async def cleanup(self, handle: AgentHandle) -> None: ...
```

第一版只实现三种：

```text
InProcessAgentAdapter  本地测试，直接调用 Python Agent
HttpAgentAdapter       外部 Agent 服务
CliAgentAdapter        独立进程或代码包
```

MCP、ACP、A2A 是后续的 AgentAdapter/Transport 实现，不进入 Runner 核心。MCP 更适合工具调用，ACP 更适合外部 Agent 会话，A2A 更适合多 Agent 消息和 Artifact 交换。

## 7. 评分管线

评分不应只有一个 `benchmark.score()`：

```text
SourceScore
  Benchmark 原始 pass/fail、reward、测试结果

ProcessScore
  动作选择、参数、错误恢复、步数、轨迹和违规动作

ResourceScore
  延迟、Token、成本、CPU/GPU、环境耗时

SafetyScore
  越权、危险副作用、敏感信息、审批绕过、reward hacking

RunScore
  重复运行成功率、方差、pass^k、置信区间和回归结论
```

`SourceScore` 必须原样保存，平台自己的指标另存。报告中明确展示：

```text
source_score
native_score
score_version
evaluator_version
evidence_refs
```

## 8. 可复现性和失败归因

一个正式 Trial 必须冻结：

```text
agent_version / source_digest
model_provider / model_version / parameters
task_id / benchmark_version / dataset_version
adapter_version / scorer_version
runtime_version / environment_image_digest
seed / repetition / timeout / budget
```

失败至少区分：

```text
agent.invalid_action
agent.policy_violation
agent.budget_exhausted
agent.no_action
environment.tool_error
environment.state_conflict
infrastructure.timeout
infrastructure.worker_crash
benchmark.invalid_case
verifier.error
```

基础设施错误不能被计入 Agent 能力失败率；适配错误也不能伪装成 Agent 失败。

## 9. Benchmark 接入流程

每接入一个开源 Benchmark，固定走以下流程：

```text
1. 读取原始任务和运行器
2. 确认可见输入、动作空间、环境状态和隐藏真值
3. 实现 BenchmarkAdapter
4. 实现原生 verifier / reward 导入
5. 用 oracle 或参考 Agent 跑通
6. 记录 canonical Event
7. 与原始 benchmark 做 parity
8. 发布 adapter_version
9. 才允许进入正式 Agent 对比
```

Parity 至少检查任务数量、split、动作语义、可见信息、随机性、依赖版本、测试结果和聚合规则。

## 10. 推荐开发顺序

### M0：协议和契约测试

冻结 JSON Schema、错误码和状态机。测试非法 Action、超时、取消、重复提交、敏感字段泄漏和 Event 顺序。

### M1：本地纵向闭环

实现 InProcessAgentAdapter、MockBenchmarkAdapter、本地 Runner、JSONL EventSink、确定性 Verifier 和 TrialResult。先不要做服务端。

### M2：外部 Agent 接入

实现 HTTP 和 CLI AgentAdapter，加入 session 认证、超时、取消、断连和 artifact 收集。

### M3：第一个真实 Benchmark

优先接入“任务 + 工具 + 确定性验证”的 Benchmark。完成 oracle、parity、source score 和 native score 的闭环。

### M4：复杂环境

再接入容器/终端任务、浏览器/GUI 任务、多参与者任务。每增加一种环境，只新增 BenchmarkAdapter，不修改 Runner 主循环。

### M5：服务化平台

最后增加 Run API、队列、Worker、对象存储、权限、实时事件和 Web Console。

## 11. 对当前原型代码的具体调整

当前原型中的 `AgentInvoker.invoke()` 是一次性黑盒调用，它把 Action、Observation、Session 和最终状态压成了 `AgentExecution`，不适合承载真实 Benchmark。

下一步应该改成：

```text
AgentInvoker.invoke()
  → AgentAdapter 生命周期

TaskSpec.initial_state / final_state
  → BenchmarkAdapter Session 状态

AgentExecution.actions
  → Action + TraceEvent 流

EvaluationService.run()
  → Runner.run_trial() + RunCoordinator

LangfuseSink
  → 可选 EventExporter，不进入核心评分和运行逻辑
```

保留 Langfuse 作为导出目标是可以的，但 SDK 的结果必须先在自己的 `Event / ScoreResult / TrialResult` 中成立。

## 12. 最终 API 形态

使用者最终应当能这样运行：

```python
from agent_eval import Runner
from agent_eval.benchmarks import Tau2Adapter
from agent_eval.agents import HttpAgentAdapter

runner = Runner(
    benchmark=Tau2Adapter.from_config("tau2.yaml"),
    agent=HttpAgentAdapter(url="http://localhost:9000"),
)

result = await runner.run(
    selector={"split": "validation", "limit": 20},
    repetitions=3,
    seed=42,
)

print(result.source_scores)
print(result.process_scores)
print(result.reliability)
```

核心设计原则只有一句话：

> `BenchmarkAdapter` 负责把 Benchmark 带进来，`AgentAdapter` 负责把 Agent 接进来，`Runner` 只负责让二者按照统一协议可复现地交互。

## 13. 参考已有评测 SDK 后的实现修正

前面的协议解决了“如何让 Agent 和 Benchmark 交互”，但还没有充分解决“开发者如何舒服地写评测”。对照当前 Inspect AI、Braintrust、LangSmith 和 DeepEval 的实际 SDK，可以提炼出四个必须补上的能力：

### 13.1 同时提供高层 API 和低层协议 API

成熟 SDK 通常让简单评测只写 Dataset、Target/Task 和 Scorer，同时保留完整的低层生命周期接口。Inspect AI 用 Dataset + Solver + Scorer 构成 Task；Braintrust 用 Data + Task + Scores 构成 Eval；LangSmith 用 target + data + evaluators 运行实验。[Inspect Tasks](https://inspect.aisi.org.uk/tasks.html)、[Braintrust Evaluation](https://www.braintrust.dev/docs/evaluation-quickstart)、[LangSmith evaluate](https://reference.langchain.com/python/langsmith/client/Client/evaluate)

你的 SDK 应提供两层 API：

```python
# 高层 API：普通开发者和 CI 使用
result = await eval(
    benchmark="tau2",
    agent=http_agent("http://localhost:9000"),
    selector={"split": "validation", "limit": 20},
    evaluators=[tool_correctness(), task_completion()],
)

# 低层 API：Benchmark 作者、平台和复杂环境使用
runner = Runner(
    benchmark=Tau2Adapter(...),
    agent=HttpAgentAdapter(...),
    event_sink=JsonlEventSink(...),
)
result = await runner.run_trial(...)
```

高层 `eval()` 只能是 Runner 的薄封装，不能再实现一套不同的执行逻辑。

### 13.2 把“执行评测”和“重评分”设计成两个入口

Inspect 支持把评测日志再次交给新的 scorer 评分；这对调试评分器、修改指标和审计结果非常重要。[Inspect Reference](https://inspect.aisi.org.uk/reference/)

你的 SDK 应明确提供：

```python
await eval(...)                         # 执行 Agent 并产生原始日志
await rescore(log, evaluators=[...])    # 不重新执行 Agent，只重算分数
await compare(experiments=[...])        # 比较多个 Run / AgentVersion
await retry_failed(log, policy=...)     # 只重试可重试失败
```

因此 Event Log 必须包含足够的输入、输出、轨迹、版本、Artifact 引用和 scorer 配置。不能只保存最终分数。

### 13.3 把 Scorer 做成无状态函数，不把结果写回 Scorer 对象

DeepEval 的使用方式说明“test case + metric”很适合开发者；它也把 Agent 评测分为轨迹级、动作级和执行级指标。[DeepEval Agent Metrics](https://github.com/confident-ai/deepeval/blob/main/docs/content/guides/guides-ai-agent-evaluation-metrics.mdx)

你的实现应避免把并发运行结果写入共享 metric 实例：

```python
class Evaluator(Protocol):
    name: str
    version: str

    async def evaluate(
        self,
        subject: EvaluationSubject,
        context: EvaluationContext,
    ) -> list[Score]: ...
```

`Evaluator` 对象只保存配置，结果必须返回 `Score`。`Score` 包含 `scope_id`、`evidence_refs`、`rationale`、`usage` 和 `evaluator_version`。这样同一个 evaluator 可以安全地并发处理多个 Trial，并可以独立缓存和重评分。

指标按输入范围分三种，而不是按实现来源分：

```text
step evaluator       输入单个 Action / Observation / Transition
trial evaluator      输入完整有序 Event 流和最终状态
run evaluator        输入多个 Trial 的结果，用于聚合、比较和回归
```

这比把所有指标都塞到 `benchmark.score()` 更容易扩展，也能覆盖工具选择、参数正确性、任务完成度、步骤效率和可靠性等不同粒度。DeepEval 当前也将计划/执行放在 trajectory 范围，把工具和参数放在 component 范围。[DeepEval Agent Metrics](https://github.com/confident-ai/deepeval/blob/main/docs/content/guides/guides-ai-agent-evaluation-metrics.mdx)

### 13.4 CLI 和 pytest 是 SDK 的一等入口

Braintrust 用评测文件和 CLI 执行，支持抽样、固定 seed、并发 worker 和最终/非最终运行标记；DeepEval 将本地评测接入 Pytest，并通过 CLI 运行测试。[Braintrust CLI](https://www.braintrust.dev/docs/reference/cli/eval)、[DeepEval Quickstart](https://deepeval.com/docs/getting-started)

你的 SDK 不应只暴露一个 Python API，还应提供：

```text
agent-eval list benchmarks
agent-eval run -b tau2 -a agent.yaml --split validation --limit 20
agent-eval score run.jsonl --evaluator tool_correctness
agent-eval compare run-a.jsonl run-b.jsonl
agent-eval retry run.jsonl --only infrastructure
```

pytest 插件可以放在第二阶段：

```python
@pytest.mark.agent_eval
async def test_tau2_smoke():
    result = await eval(benchmark="tau2", limit=3)
    assert result.gate_passed
```

### 13.5 形成三种使用模式

最终 SDK 应支持三种模式，但共用同一个 Runner：

```text
模式 A：代码内评测
  Python eval() / pytest

模式 B：Benchmark 包评测
  BenchmarkAdapter + AgentAdapter + CLI

模式 C：生产 Trace 重评分
  EventLog / Trace → Evaluator → Score
```

模式 C 不执行 Benchmark 环境，只适用于已有 Trace 的质量、轨迹、安全和成本分析；模式 A/B 才负责真实任务执行。

## 14. 定稿后的代码结构

```text
agent_eval/
├── protocol/       # TaskSpec, Observation, Action, Event, Score, JSON Schema
├── runtime/        # Runner, Session, Budget, RetryPolicy, Cancellation
├── agents/         # AgentAdapter: inprocess, http, cli, package
├── benchmarks/     # BenchmarkAdapter packages and registry
├── evaluators/     # stateless step/trial/run evaluators
├── experiment/     # eval(), compare(), retry_failed(), rescore()
├── storage/        # JSONL log, SQLite index, artifact store
├── cli/            # list, run, score, compare, retry
└── exporters/      # JSON, OpenTelemetry, Langfuse and platform API
```

公开 API 只暴露四类对象：

```text
Adapter       接入 Benchmark 或 Agent
Runner        执行一次或多次 Trial
Evaluator     计算 Score
Experiment    组织 eval / compare / rescore / retry
```

## 15. 最终开发判断

参考已有评测 SDK 后，最值得借鉴的不是它们的命名，而是实现方式：

1. 用一个非常短的高层 API 让用户能启动评测。
2. 用稳定的低层协议支持复杂 Benchmark 和外部 Agent。
3. 用不可变、可重放的日志支撑重评分和比较实验。
4. 用无状态 evaluator 支撑并发、缓存和版本化。
5. 用 CLI/pytest 把评测放进开发和 CI 流程。
6. 用平台 Exporter 连接 Langfuse 或自建服务，但不让平台依赖进入本地 SDK 核心。

因此，SDK 的核心产品形态不是“一个 Runner 类”，而是：

```text
eval()       开发者入口
Runner       执行内核
Adapter      扩展机制
Evaluator    评分机制
Event Log    事实和重放基础
CLI / pytest 工程化入口
```

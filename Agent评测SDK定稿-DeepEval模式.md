# Agent 评测 SDK 定稿方案：DeepEval 模式

更新时间：2026-09-07

## 1. 正确定位

这个 SDK 不是完整评测平台，也不是平台侧的 Benchmark Runner。它是一个被测 Agent 使用的测试与观测包：

```text
测试代码给定 Agent
        ↓
Agent 使用 Agent Evaluation SDK 运行
        ↓
SDK 捕获 Agent / LLM / Tool / Sub-agent 的执行事件
        ↓
Evaluator 读取 TestCase + Trace 计算指标
        ↓
平台实时展示 Trace、步骤、工具调用、评分和失败原因
```

DeepEval 当前的核心模式正是“对 Agent 做最少量的 tracing，然后在 end-to-end、trajectory 和 component 三个作用域进行评测”。[DeepEval Agent Quickstart](https://deepeval.com/docs/getting-started-agents)、[DeepEval Tracing](https://deepeval.com/docs/evaluation-llm-tracing)

因此你的 SDK 应该把 Agent 测试体验做成：

```text
给一个 Agent
给一个 TestCase / Benchmark
给一组 Evaluator
运行 Agent
实时看到 Trace
得到 Score 和失败证据
```

## 2. 整个系统的职责分配

```text
Agent Evaluation SDK（被测 Agent 侧）
  observe / trace / session / event / artifact / transport

Test Package（测试侧）
  TestCase / Dataset / Benchmark Adapter / Evaluator / pytest / CLI

Platform（平台侧）
  Run、权限、Agent 版本、任务分发、实时展示、报告、审计

Benchmark Environment（Benchmark 侧）
  环境、工具、隐藏状态、原始 verifier、原始 reward
```

关键调用方向是：

```text
测试包调用 Agent
Agent 调用自己的业务逻辑
Agent 使用 SDK 上报事件
平台订阅 SDK 事件并展示
Evaluator 读取事件并评分
```

不是：

```text
SDK 负责启动所有 Benchmark
SDK 负责运行整个评测平台
SDK 负责管理所有 Agent
```

## 3. Agent 开发者如何使用 SDK

Agent 只需要在自己的入口、工具、模型调用和子 Agent 上使用 SDK：

```python
from agent_eval import observe

@observe(kind="agent")
async def travel_agent(task: str):
    plan = await make_plan(task)
    flights = await search_flights(plan)
    return await compose_answer(task, flights)

@observe(kind="tool")
async def search_flights(plan):
    ...
```

如果不适合装饰器，也提供上下文 API：

```python
from agent_eval import trace

async def travel_agent(task):
    async with trace.agent(name="travel_agent", input=task) as run:
        result = await run_logic(task)
        run.set_output(result)
        return result
```

SDK 自动建立一棵有序事件树：

```text
agent
├── plan
│   └── llm
├── tool.search_flights
│   └── tool result
└── final answer
```

SDK 需要记录的是事实，不是强行抽取 Agent 的内部思维。可以记录模型请求、工具调用、工具返回、Observation、Action、错误、耗时、Token、成本和 Artifact；不要求 Agent 暴露不可验证的隐藏 Chain-of-Thought。

## 4. 测试代码如何给定 Agent

测试包提供高层 `evaluate()`：

```python
from agent_eval import evaluate
from agent_eval.metrics import (
    TaskCompletion,
    ToolCorrectness,
    StepEfficiency,
)
from my_agent import travel_agent

result = await evaluate(
    name="travel-agent-smoke",
    agent=travel_agent,
    data=[
        {
            "id": "flight-001",
            "input": "帮我找明天从上海到东京的最低价航班",
            "expected_tools": ["search_flights"],
        }
    ],
    metrics=[
        TaskCompletion(),
        ToolCorrectness(),
        StepEfficiency(),
    ],
)
```

内部执行过程是：

```text
evaluate()
  → 创建 EvaluationContext
  → 为每个 TestCase 创建 TraceContext
  → 调用 agent(case.input)
  → SDK 收集完整事件树
  → 运行 step / trajectory / case metrics
  → 发送实时事件和最终 Score
  → 返回 EvaluationResult
```

`evaluate()` 是开发者入口，`Runner` 只是内部实现，不应成为用户必须理解的核心对象。

## 5. SDK 的最小公共对象

### 5.1 TestCase

```python
@dataclass(frozen=True)
class AgentTestCase:
    id: str
    input: Any
    expected_output: Any | None = None
    expected_tools: tuple[str, ...] = ()
    context: tuple[Any, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

### 5.2 Trace

```python
@dataclass(frozen=True)
class Trace:
    trace_id: str
    test_case_id: str
    root_span_id: str
    events: tuple[TraceEvent, ...]
    output: Any | None
    status: Literal["success", "error", "timeout", "cancelled"]
```

### 5.3 Evaluator

```python
class Evaluator(Protocol):
    name: str
    version: str

    async def evaluate(
        self,
        case: AgentTestCase,
        trace: Trace,
    ) -> list[Score]: ...
```

Evaluator 是无状态的。每次返回新的 Score，不把上一次测试的 score/reason 写回 Metric 对象。

### 5.4 EvaluationResult

```python
@dataclass(frozen=True)
class EvaluationResult:
    experiment_id: str
    case_results: tuple[CaseResult, ...]
    summary: Summary
    log_ref: str
```

## 6. 评测作用域

应该直接借鉴 DeepEval 的三层作用域：

```text
case-level / end-to-end
  只看 Agent 输入和最终输出

trajectory-level
  看完整有序 Agent Trace

component-level
  看某个 Agent、LLM、Tool、Retriever 或 Sub-agent Span
```

对应指标：

```text
TaskCompletion       trajectory-level
StepEfficiency       trajectory-level
PlanQuality          trajectory-level
ToolCorrectness      component-level
ArgumentCorrectness  component-level
AnswerCorrectness    case-level
```

不同指标使用不同输入，不把所有指标都强制绑定完整 Trace。DeepEval 当前也将计划质量、计划遵循、任务完成和步骤效率作为轨迹级指标，将工具和参数正确性作为组件级指标。[DeepEval Agent Metrics](https://deepeval.com/guides/guides-ai-agent-evaluation-metrics)

## 7. 实时展示怎么实现

SDK 不直接负责渲染页面，而是产生统一事件并通过 Sink 发出去：

```python
from agent_eval import configure
from agent_eval.sinks import HttpSink, ConsoleSink

configure(
    sinks=[
        ConsoleSink(),
        HttpSink("http://eval-platform/v1/ingest"),
    ]
)
```

事件流：

```text
Agent SDK
  → EventSink
  → Platform Ingest API / WebSocket fanout
  → Trace 页面实时更新
```

本地测试可以只使用 `ConsoleSink` 或 `JsonlSink`；平台评测使用 `HttpSink`。这样 Agent 代码不依赖 UI，也不需要知道平台如何存储 Trace。

必须支持三种事件模式：

```text
live event       运行时发送，供页面实时展示
durable log      本地或平台持久化，供重评分
final result     运行结束后发送，供报告和 CI
```

## 8. 开源评测集如何接入

这里不要把所有 Benchmark 都强制改造成 Agent SDK 的环境模型。采用三级适配：

### Level 1：数据集适配

只需要把原始样本转为 `AgentTestCase`：

```python
class DatasetAdapter(Protocol):
    def cases(self, split: str) -> Iterable[AgentTestCase]: ...
```

适合 QA、分类、摘要、RAG 和简单工具调用测试。

### Level 2：验证器适配

保留原 Benchmark 的测试和 reward：

```python
class VerifierAdapter(Protocol):
    async def verify(
        self,
        case: AgentTestCase,
        trace: Trace,
        artifacts: list[Artifact],
    ) -> list[Score]: ...
```

适合 Terminal-Bench、代码任务、文件产物和数据库状态任务。

### Level 3：环境适配

只有交互式 Benchmark 才需要接入环境生命周期：

```python
class InteractiveBenchmark(Protocol):
    async def setup(self, case: AgentTestCase) -> BenchmarkSession: ...
    async def observe(self, session) -> Observation: ...
    async def apply(self, session, action: Action) -> list[Observation]: ...
    async def verify(self, session, trace: Trace) -> list[Score]: ...
    async def cleanup(self, session) -> None: ...
```

这一级由测试包或平台执行面使用，不需要被测 Agent 导入 Benchmark 代码。Agent 仍然只使用我们的 SDK 接收 Observation、产生 Action 和上报 Trace。

### Benchmark 包结构

```text
agent_eval_benchmarks/
└── tau2/
    ├── dataset.py
    ├── verifier.py
    ├── environment.py       # 交互式任务才需要
    ├── manifest.yaml
    ├── parity_test.py
    └── README.md
```

因此开源 Benchmark 的接入重点是数据、环境和 verifier，不是把某家 Agent 代码接进来。

## 9. CLI 和 Pytest

参考 DeepEval 的 Pytest 体验，测试包应提供：

```bash
agent-eval test tests/
agent-eval test tests/test_travel.py --dataset tau2 --split validation
agent-eval score logs/run.jsonl --metric task_completion
agent-eval compare logs/v1.jsonl logs/v2.jsonl
```

测试文件可以写成：

```python
from agent_eval import agent_test

@agent_test(
    agent=travel_agent,
    dataset="tau2.validation",
    metrics=["task_completion", "tool_correctness"],
)
async def test_travel_agent():
    pass
```

或者使用显式函数式 API。装饰器只是语法糖，底层仍然调用同一个 `evaluate()`。

## 10. DeepEval 与自研 SDK 的关系

如果你当前的目标是“先把 Agent 怎么测、Trace 怎么展示、指标怎么跑通”，最合理的是：

```text
自研：Agent SDK 的事件协议、平台 Sink、Benchmark Adapter、展示协议
复用或参考：DeepEval 的 TestCase、Trace Scope、Agent Metrics、Pytest UX
```

有两种实施路线：

### 路线 A：直接使用 DeepEval

适合快速验证产品：

```text
Agent 使用 DeepEval tracing
测试包使用 DeepEval metrics
平台接收 DeepEval trace/result
```

优点是最快；缺点是你的公开协议和数据模型会被 DeepEval 绑定。

### 路线 B：自研薄 SDK，DeepEval 作为可选 Evaluator Backend

```text
Agent 使用你的 observe / Event API
你的 TestCase / Trace 作为主模型
DeepEvalEvaluator 将你的 Trace 转成 DeepEval 输入
平台只认识你的 Score / Event
```

这更适合你的长期目标。即便以后不用 DeepEval，也不需要改变 Agent 接入协议。

## 11. 最终建议

不要再造一个完整的 DeepEval。第一版应该只造 DeepEval 没有替你完成的部分：

```text
1. 你的 Agent SDK：observe、session、event、artifact、sink
2. 你的 TestCase / Benchmark Adapter 规范
3. 你的平台实时展示协议
4. 你的开源 Benchmark 接入和 parity 机制
```

而以下能力直接参考或复用 DeepEval：

```text
1. end-to-end / trajectory / component 三种评测作用域
2. Agent 评测指标的分层方式
3. TestCase + Metric 的开发体验
4. pytest / CLI 工作流
5. LLM Judge 的 score + reason 输出
```

最终 SDK 的一句话定义是：

> 测试包负责给定 Agent 和测试集，Agent SDK 负责记录 Agent 如何执行，平台负责展示和管理，Evaluator 负责解释执行结果。

# 主流 Agent 评测 SDK / Harness 优缺点分析

## 结论先行

如果目标是“用户给出一个 Agent，Agent 使用 SDK 产生 trace，测试包运行数据集和指标，平台展示过程与结果”，最接近的是 DeepEval 的产品形态。

但主流项目其实分成三类：

1. **测试型 SDK**：DeepEval。重点是测试用例、指标、trace 和 CI。
2. **平台型评测 SDK**：LangSmith、Braintrust。重点是数据集、实验、线上观测、对比和协作。
3. **Benchmark/Harness**：Inspect AI、Harbor。重点是任务、solver/agent、沙箱、试验次数、可复现和 benchmark 适配。

因此不建议把所有能力揉成一个“大 SDK”。你的 SDK 应该主要借鉴 DeepEval 的接入方式，再把 Inspect/Harbor 的 benchmark 任务模型放在测试包或平台执行层；LangSmith/Braintrust 的实验对比能力放在平台层。

## 1. DeepEval

### 优点

- 最接近普通开发者的测试体验：Agent 通过 `@observe` 产生 trace，测试通过 pytest 和 `deepeval test run` 执行。
- 对 Agent 有明确的三层评测视角：最终结果、完整轨迹、单个组件/span；组件可以是 LLM 调用、工具、检索器或子 Agent。
- 内置 Agent 常用指标，并支持自定义 metric；适合快速覆盖任务完成、工具正确性、轨迹质量、步骤效率等日常问题。
- 适合先在本地和 CI 中使用，不必一开始就依赖完整平台。

### 缺点

- trace、test case、metric 的概念和数据结构有较强的框架约束；如果你的平台已经有自己的 `TaskSpec / Observation / Action / TraceEvent`，直接暴露 DeepEval 类型会形成绑定。
- 很多主观指标依赖 LLM-as-a-judge，成本、延迟、评判稳定性和 rubric 设计需要自己治理。
- 它更像“应用测试 SDK”，不是完整的 benchmark 沙箱和大规模任务调度系统；涉及终端、浏览器、代码执行、容器隔离时仍要额外建设执行层。
- 如果把 DeepEval 当作你 SDK 的公共底座，未来指标、缓存、并发、日志和版本升级都会被上游实现牵制。

**适合借鉴**：`observe` 接入方式、trace/span 评测范围、pytest/CI 流程、Agent 指标组织。

## 2. LangSmith

### 优点

- 数据集、run/trace、experiment、evaluator 的对象边界清楚，支持离线评测和线上评测。
- 对实验管理和结果分析较强：同一个数据集上可以比较多个 experiment，也能查看每个样例的中间步骤。
- evaluator 支持代码规则、LLM judge、人工评测、pairwise 等方式，并能返回 score/value/comment 等反馈。
- 很适合把生产 trace 回流成数据集，再做回归测试，形成“线上发现问题—离线复现—修复验证”的闭环。

### 缺点

- 平台属性很强，SDK 通常围绕其 workspace、project、dataset、run 组织；离开平台后体验不如纯本地测试自然。
- 容易受到 LangChain/LangGraph 生态和其数据模型影响，虽然也支持手工 instrumentation，但接入心智成本仍偏平台化。
- 它擅长评测应用运行结果和 trace，不是以 benchmark 沙箱、容器任务和环境验证为中心。

**适合借鉴**：`Dataset -> Run -> Experiment -> Feedback` 的实验模型，以及离线/在线评测统一的 evaluator 接口。

## 3. Braintrust

### 优点

- 核心抽象很简洁：数据集、任务函数、评分器组成一个 eval；对开发者来说容易写成普通的 JS/TS 或 Python 测试文件。
- CLI 工作流完整：自动发现 eval 文件、本地执行、watch、CI、JSON 输出、抽样 smoke run、并发和参数矩阵。
- 适合做模型、prompt、工具策略的多版本实验；开发阶段可以只跑少量样例，合并时再跑全量。
- 多语言支持比很多同类工具更积极，适合作为“测试文件即评测配置”的参考。

### 缺点

- 整体仍是强平台/实验中心思路，trace、日志、实验结果和远端项目之间有耦合。
- 它的核心优势在 eval runner 和实验管理，不会替你解决复杂 Agent benchmark 的环境、工具权限、任务恢复和验证器问题。
- 如果你的产品要完全自托管、离线运行、或让平台自定义事件协议，需要把其日志/实验模型隔离在后端适配层。

**适合借鉴**：eval 文件组织、CLI/CI、抽样运行、并发、重复试验和参数 sweep。

## 4. Inspect AI

### 优点

- 更像研究和 benchmark 评测框架。核心任务由 `Dataset + Solver + Scorer` 构成，任务还可以声明 sandbox、限制、重试和日志等执行属性。
- solver 与 scorer 可以替换，便于同一个 benchmark 对比不同 Agent 策略。
- 支持把任务打包成 Python 包，提供命令行执行、eval set、重试、日志查看和对已有日志重新评分等能力。
- 对受控环境、工具使用和可复现试验的考虑比轻量测试 SDK 更完整。

### 缺点

- 概念和运行时更重；对于“给一个现成 Agent 跑几个测试用例”的产品接入，不如 DeepEval 直接。
- Agent 需要适配它的 solver、sample、scorer、sandbox 和 log 语义；这与“Agent 只需调用你的 SDK 埋点”的目标有距离。
- 更适合 benchmark 作者和评测研究者，不一定适合作为业务开发团队的唯一日常测试入口。

**适合借鉴**：benchmark 任务包、solver/scorer 分离、sandbox、日志重评分和可复现执行。

## 5. Harbor

### 优点

- 面向容器化 Agent benchmark，核心对象是 `Task / Dataset / Agent / Environment / Trial / Job`。
- 一个 task 可以包含指令、容器环境和测试脚本；trial 表示一次尝试，job 聚合多个任务、Agent、模型和试验。
- 对 Terminal-Bench、SWE-Bench 等需要真实环境和验证脚本的任务更合适；还提供 trajectory、reward、测试输出和 artifact 的结果查看。
- benchmark adapter 的职责边界也很明确：把原始 benchmark 的指令、环境和测试转换成统一 task 格式。

### 缺点

- 它不是普通意义上的 Agent 质量指标 SDK，而是更重的执行和 benchmark harness。
- 需要处理容器、资源、凭据、任务目录、并发试验和结果归档，基础设施复杂度明显高于 DeepEval。
- 如果你的第一阶段只是应用级 Agent 测试，直接把 Harbor 放进 Agent SDK 会过度设计。

**适合借鉴**：benchmark 适配器、Task/Dataset/Trial/Job 层级，以及环境验证和 artifact 归档。

## 6. Langfuse 应该放在哪里

Langfuse 更适合作为观测和 trace 数据面来理解，而不是和 DeepEval、Inspect AI 放在同一层比较。它解决的是“记录 Agent 执行过程、保存 span、查看调用链、承载评测数据”的问题；测试用例、benchmark 任务、评分器和执行编排仍需要由评测 SDK 或平台负责。

对你的系统而言，可以采用：

```text
Agent 代码
  └─ 使用你的 Agent SDK：observe / span / event / artifact
       ├─ 本地 sink：调试、离线 JSONL
       └─ 平台 sink：实时 trace、结果展示

评测测试包
  ├─ evaluate(agent, dataset, metrics)
  ├─ BenchmarkAdapter
  ├─ verifier / scorer
  └─ 把 trace 转成可评测对象

平台执行层
  ├─ run / trial / job
  ├─ 环境与凭据隔离
  ├─ 实时展示
  └─ 实验对比与报告
```

## 7. 对你要开发的 SDK 的建议

### 公共 API 应保持很薄

建议只让 Agent 侧依赖这些稳定接口：

```python
from agent_eval import observe, get_session

@observe(kind="agent")
def run_agent(task):
    ...
```

SDK 内部负责：trace context、span 生命周期、LLM/tool/retrieval/sub-agent 事件、错误、耗时、token/cost、artifact 和 sink。

测试侧再提供：

```python
from agent_eval import evaluate

evaluate(
    agent=run_agent,
    dataset=my_dataset,
    metrics=[task_completion, tool_correctness],
)
```

不要让 Agent 侧暴露 DeepEval、LangSmith 或 Inspect 的类型。可以在内部做 `DeepEvalBackend`、`InspectBackend`，但公共协议应属于你自己的系统。

### 你的差异化重点不应是重新发明所有指标

第一阶段最合理的组合是：

- 借鉴 DeepEval 的开发者体验和 Agent trace 评测方式；
- 借鉴 Inspect AI 的 `Dataset / Solver / Scorer` 分离；
- 借鉴 Harbor 的 benchmark task、环境和 trial/job 思路；
- 借鉴 LangSmith/Braintrust 的实验、抽样、并发、版本对比和线上回流；
- 自己掌握统一的 `TraceEvent`、benchmark 适配协议、平台实时展示和结果存储。

这是一个架构判断，不是说要把四家的代码拼起来。最重要的是把“Agent 运行记录”“测试数据”“评分逻辑”“环境执行”“平台展示”拆成不同层。

### 最终选择

- **要最快做出可用版本**：直接采用 DeepEval 风格，先实现 `observe + evaluate + pytest/CLI + 基础指标`。
- **要支持复杂开源 benchmark**：在测试包/执行层增加 `BenchmarkAdapter + Environment + Verifier`，必要时参考 Inspect AI 或 Harbor 的任务模型。
- **要长期做成平台**：实验、版本、批量运行、实时 trace、结果对比应由平台层负责，SDK 不要承载太多后端业务。

一句话：你真正应该造的是“Agent 接入协议 + benchmark 测试包 + 平台数据通道”，而不是重新造一个包含所有指标、沙箱、调度和可观测性的巨型 SDK。

## 参考

- [DeepEval Agent Evaluation Quickstart](https://deepeval.com/docs/getting-started-agents)
- [DeepEval LLM Tracing](https://deepeval.com/docs/evaluation-llm-tracing)
- [LangSmith Evaluation Concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
- [LangSmith Evaluation](https://docs.langchain.com/langsmith/evaluation)
- [Braintrust CLI Quickstart](https://www.braintrust.dev/docs/reference/cli/quickstart)
- [Braintrust bt eval](https://www.braintrust.dev/docs/reference/cli/eval)
- [Inspect AI Tasks](https://inspect.aisi.org.uk/tasks.html)
- [Harbor Core Concepts](https://www.harborframework.com/docs/core-concepts)
- [Harbor Evals](https://www.harborframework.com/docs/run-jobs/run-evals)

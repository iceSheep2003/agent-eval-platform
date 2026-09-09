# Agent 评测 SDK 抽象调研与建议

更新时间：2026-09-07

## 1. 结论

如果目标是开发一套不兼容、不适配任何现有 Agent 或评测框架的新 SDK，核心不应是复刻 Langfuse 的 `Trace`，也不应只提供一个 `task(input) -> output` 黑盒接口。

更合适的核心模型是：

```text
Scenario
  ├── 给 Agent 可见的 Goal / Context / Action Space
  ├── 对 Agent 隐藏的 Ground Truth / Constraints / Verifiers
  └── 可初始化、可变化、可快照的 Environment

EvaluationRun
  └── Trial
      └── Step*
          ├── Observation
          ├── Decision
          ├── Action
          ├── Transition
          └── Event*

Trial
  ├── Final State
  ├── Artifacts
  ├── Scores
  └── Failure Classification
```

其中：

- Agent 是一个根据当前观测和上下文产生下一步决策的策略，不负责执行工具和修改环境。
- Runtime 负责循环、预算、超时、取消、轨迹记录和状态机。
- Environment 负责执行动作、产生副作用、推进时间并返回新观测。
- Verifier 基于隐藏真值、最终环境状态和证据判断“有没有完成任务”。
- Evaluator 基于输出、轨迹、状态和成本计算质量、过程、安全、效率等指标。
- Trace 只是 Trial 的可观测投影，而不是 Agent 或评测本身。

这套边界能够自然覆盖工具 Agent、多轮客服 Agent、代码 Agent、浏览器 Agent、异步环境和多参与者任务，同时不需要兼容任何现有框架。

## 2. 近期技术报告反映出的变化

### 2.1 General Agent Evaluation / Exgentic（2026）

《General Agent Evaluation》提出的核心问题是：现有 benchmark 往往把领域知识、环境语义和通信方式编码进专用集成，导致测到的是“经过适配后的专用 Agent”，而不是 Agent 本身。它提出统一的 `Task / Context / Actions` 中介协议，并用 Exgentic 运行不同 Agent 和环境。

对本 SDK 最有价值的启示不是兼容层，而是以下边界：

- Task 描述目标，不控制 Agent 的实现。
- Context 是当前可见信息，不等于全部环境状态。
- Actions 是受约束的可执行能力，不应让 Agent直接修改环境。
- Benchmark 的隐藏语义和评分逻辑必须与 Agent 输入隔离。

来源：[General Agent Evaluation, 2026](https://arxiv.org/abs/2602.22953)

### 2.2 ARE 与 Gaia2（2025–2026）

Meta 的 ARE 将环境拆为规则、工具、内容和验证器。Gaia2 进一步把环境建模为独立于 Agent 动作变化的异步系统：时间会推进，外部事件会出现，信息可能带噪声，多个参与者可能同时行动。

它表明 `Environment.execute(action)` 还不够，环境至少需要：

- `reset()`：初始化场景。
- `observe(actor)`：返回该参与者有权限看到的局部状态。
- `apply(action)`：验证并执行动作。
- `tick()`：推进逻辑时间并触发外部事件。
- `snapshot()`：生成可验证的状态快照。
- `is_terminal()`：判断终止条件。

Gaia2 使用 write-action verifier 做动作级验证，说明验证器不能只在最终答案上运行。

来源：[ARE: Scaling Up Agent Environments and Evaluations, 2025](https://arxiv.org/abs/2509.17158)、[Gaia2, 2026](https://arxiv.org/abs/2602.11964)

### 2.3 τ²-bench（2025）

τ²-bench 把客服场景建模为 Dec-POMDP：Agent 和模拟用户都可以通过各自工具修改共享动态环境。它还使用组合式任务生成器，从原子组件构造可验证任务，并将推理错误与沟通/协调错误分开分析。

对 SDK 的直接启示：

- `UserSimulator` 不能只是一段固定对话脚本，而应是受场景目标、知识边界和可用动作约束的参与者。
- 一个场景可能有多个 Actor，不应硬编码成“用户输入一次，Agent 输出一次”。
- 共享环境状态与每个 Actor 的可见观测必须分开。
- 需要单独记录“Agent 自己执行的动作”和“Agent 指导用户执行的动作”。

来源：[τ²-bench, 2025](https://arxiv.org/abs/2506.07982)

### 2.4 Terminal-Bench 2.0 与 Harbor（2025–2026）

Terminal-Bench 2.0 将一个任务构造成独立环境、自然语言任务、人工解法和完整测试。Harbor 将 Agent 放入容器环境中执行，再通过测试和产物验证结果。

它体现了一个很重要的原则：

> 评测器不应该相信 Agent 声称“任务已完成”，而应检查环境状态、文件、数据库或测试结果。

对 SDK 的启示：

- `Artifact` 必须是一等对象，而不是塞进 output 字符串。
- `Verifier` 应拥有 Agent 不可见的检查逻辑。
- 环境、任务、Agent、模型、数据和验证器都要有独立版本。
- 基础设施错误与 Agent 失败必须分开统计。

来源：[Terminal-Bench 2.0 / Harbor, 2025](https://www.tbench.ai/news/announcement-2-0)、[Terminal-Bench 2.0 技术报告, 2026](https://arxiv.org/abs/2601.11868)

### 2.5 METR Time Horizon 1.1（2026）

METR 不只统计任务成功率，而是根据人类专家完成任务所需时间，估计 Agent 在特定成功概率下能完成多长周期的任务。其流程会对同一任务进行多次独立运行，并区分模型、scaffold、预算和环境问题；还会检查 reward hacking。

对 SDK 的启示：

- 同一个 Case 的重复运行是 `Trial`，不是基础设施重试。
- `repeat_index` 和 `infra_attempt` 必须分别记录。
- 必须保存随机种子、模型版本、Agent 版本、环境版本、预算和时间限制。
- 长周期能力应按任务难度或人类基线分层，不宜只看总平均分。
- Reward hacking 和越权完成要作为独立失败类型。

来源：[METR Task-Completion Time Horizons, 2026](https://metr.org/time-horizons/)

### 2.6 当前评测框架的共同结构

当前 Inspect AI 将任务定义为 Dataset、Solver 和 Scorer，并提供 Sandbox、审批策略、Token/时间/成本限制、错误容忍等运行控制。LangSmith、Braintrust、MLflow 仍保留 Dataset、Target/Task、Evaluator/Scorer、Experiment 这一经典结构，但 MLflow 已把完整 Trace 作为评分输入，允许评估工具轨迹、子 Agent 路由和检索过程。

这些框架证明了两件事：

- Dataset、执行逻辑和评分逻辑必须分离。
- 面向 Agent 时，Scorer 的输入必须包含轨迹和环境状态，不能只包含最终 output。

来源：[Inspect AI Tasks](https://inspect.aisi.org.uk/tasks.html)、[LangSmith Evaluation Concepts](https://docs.langchain.com/langsmith/evaluation-concepts)、[Braintrust Evaluation](https://www.braintrust.dev/docs/evaluate)、[MLflow Trace Evaluation](https://www.mlflow.org/docs/latest/genai/eval-monitor/running-evaluation/traces/)

## 3. 建议采用的 Agent 原生抽象

### 3.1 AgentDefinition：静态定义

AgentDefinition 描述“这个 Agent 是什么”，在一次 Trial 内保持不可变：

```python
@dataclass(frozen=True)
class AgentDefinition:
    id: str
    version: str
    instructions: str
    model: ModelSpec
    tools: tuple[ActionSpec, ...]
    memory_policy: MemoryPolicy
    permissions: PermissionSet
    limits: ExecutionLimits
    metadata: Mapping[str, Any]
```

不要把网络客户端、数据库连接和运行中消息放进 AgentDefinition。

### 3.2 AgentState：运行状态

AgentState 是某个 Trial 中 Agent 的可序列化状态：

```python
@dataclass
class AgentState:
    messages: list[Message]
    working_memory: dict[str, Any]
    plan: Plan | None
    active_goal: str | None
    delegated_tasks: list[DelegatedTask]
    custom: dict[str, Any]
```

它需要支持快照，便于复现、暂停、恢复和失败分析。

### 3.3 AgentPolicy：决策逻辑

AgentPolicy 只负责产生下一步 Decision：

```python
class AgentPolicy(Protocol):
    async def decide(
        self,
        observation: Observation,
        state: AgentState,
        context: TurnContext,
    ) -> Decision:
        ...
```

Decision 建议使用封闭的 tagged union：

```text
CallAction(name, arguments)
SendMessage(recipient, content)
Delegate(target, task)
RequestHuman(question)
Finish(output)
Abort(reason)
```

Agent 不直接调用工具；Runtime 收到 `CallAction` 后先做 Schema、权限、预算和安全检查，再交给 Environment。

### 3.4 Environment：状态与副作用所有者

```python
class Environment(Protocol):
    async def reset(self, scenario: Scenario) -> EnvironmentSnapshot: ...
    async def observe(self, actor_id: str) -> Observation: ...
    async def apply(self, actor_id: str, action: Action) -> Transition: ...
    async def tick(self) -> list[EnvironmentEvent]: ...
    async def snapshot(self) -> EnvironmentSnapshot: ...
    async def close(self) -> None: ...
```

Environment 是唯一允许产生外部副作用的组件。这样才能实现权限控制、审计、回放和确定性验证。

### 3.5 Scenario：测试契约

Scenario 不等于 DatasetItem。DatasetItem 是数据记录，Scenario 是可执行测试契约：

```python
@dataclass(frozen=True)
class Scenario:
    id: str
    goal: Goal
    initial_state: EnvironmentSeed
    actors: tuple[ActorSpec, ...]
    action_space: tuple[ActionSpec, ...]
    visible_context: Mapping[str, Any]
    hidden_ground_truth: Mapping[str, Any]
    success_criteria: tuple[Criterion, ...]
    forbidden_criteria: tuple[Criterion, ...]
    limits: ExecutionLimits
    tags: frozenset[str]
```

必须确保 `hidden_ground_truth`、Verifier 实现和测试密钥不会进入 AgentContext 或 Trace 的可见字段。

### 3.6 Runtime：唯一执行循环

```text
reset environment
  → observe
  → agent.decide
  → validate decision
  → environment.apply / send message / finish
  → record transition and events
  → tick environment
  → evaluate online constraints
  → repeat until terminal or budget exhausted
```

Runtime 负责：

- 生命周期状态机。
- 生成稳定 ID。
- Deadline、Token、成本、步数和工具预算。
- 取消、超时和基础设施重试。
- 事件顺序和父子关系。
- AgentState 与 EnvironmentSnapshot 快照。
- 最终交给 Verifier/Evaluator。

### 3.7 Trial、Step 与 Event

推荐层级：

```text
EvaluationRun
└── Trial = Case × AgentVersion × EnvironmentVersion × Seed × RepeatIndex
    ├── Step 1
    │   ├── observation.received
    │   ├── decision.proposed
    │   ├── action.validated
    │   ├── action.started
    │   └── action.completed
    ├── Step 2
    └── TrialResult
```

Step 是面向评测和人类理解的语义单元；Event 是 append-only 的原始事实。UI 可以从 Event 构造 Step 和 Trace，但原始 Event 不应被覆盖。

### 3.8 Verifier、Evaluator 与 PolicyMonitor

三者职责必须分开：

- `Verifier`：基于隐藏真值或最终环境状态，确定任务是否完成以及完成比例。
- `Evaluator`：计算质量、轨迹、效率、可靠性等可比较指标。
- `PolicyMonitor`：在执行过程中检查越权、危险动作、预算和策略约束，可以阻断动作。

```python
class Verifier(Protocol):
    async def verify(self, scenario, final_state, artifacts) -> Verification: ...

class Evaluator(Protocol):
    async def evaluate_trial(self, trial: TrialRecord) -> list[Score]: ...

class RunEvaluator(Protocol):
    async def evaluate_run(self, run: EvaluationRunRecord) -> list[Score]: ...
```

### 3.9 BenchmarkAdapter：沿用已有的 Benchmark 适配协议

这里不应该重新发明 `BenchmarkPack` 接口。项目中已有的《评测协议与 Agent 接入规范》已经定义了 `BenchmarkAdapter`，并明确了 `TaskSpec / Observation / Action / RunContext / SessionContext` 的边界。本报告中的 `BenchmarkPack` 应理解为 **BenchmarkAdapter 的可分发代码包和版本化实现**，不是另一套运行时协议。

这里仍然需要区分两种“适配”——前者是 SDK 必须支持的能力，后者是本 SDK 明确不做的事情：

- **Benchmark integration**：解析外部 benchmark 的任务格式，启动它的环境，转换动作和观测，执行原始 verifier，并把结果编译成 SDK 的 Scenario / Environment / Verifier / Score。
- **Agent framework adapter**：围绕 LangGraph、OpenHands、某家 Agent SDK 等内部对象写一层转换。本 SDK 不把这种适配作为核心设计目标；已有 `AgentAdapter` 应理解为统一的外部 Agent 接入协议，而不是每家框架的内部兼容层。

因此，SDK 的正式运行时接口应沿用已有的 `BenchmarkAdapter`：

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

每个 BenchmarkAdapter 只拥有 benchmark 侧的差异，不修改 AgentPolicy，不把 benchmark 的字段泄漏到核心模型。它可以作为一个 BenchmarkPack 分发，至少包含：

```text
benchmark.yaml        # 名称、版本、许可证、来源、任务类型
cases/                # CaseRef 与原始数据索引
environment/          # 环境启动、reset、observe、apply、snapshot
protocol/             # 原始观测/动作与 SDK 对象之间的编解码
verifier/             # 确定性测试、隐藏真值、产物检查
parity/               # 与原 benchmark 的分数对齐和差异说明
```

`BenchmarkManifest` 要记录原 benchmark 版本、commit、数据 split、容器/依赖版本、verifier 版本、随机性、是否允许网络、原始指标定义和适配覆盖率。对外报告时必须同时保留 `native_score` 和 `source_score`，不能只给一个“看起来相同”的分数。

### 3.10 Benchmark 类型与接入方式

不同 benchmark 不应强行共用同一套运行细节，但可以编译到同一组核心协议：

```text
任务 + 脚本测试       → Scenario + Environment + ArtifactVerifier
终端 / 容器任务       → Environment.apply(exec) + 文件/测试产物验证
浏览器 / GUI 交互     → Observation(screenshot/accessibility) + ActionCodec
用户 / Agent 共享环境 → ActorSpec + Message/Tool Action + 动态 Transition
MCP 工具调用评测      → ToolCatalog + ActionSpec + ToolResult
多 Agent 协作评测     → Message/Artifact + Delegate + Actor-to-Actor Event
```

例如，Harbor 当前把 task 定义为 instruction、container environment 和 test script，并把 Agent、Trial、Job 分开；这类结构很适合被已有的 `BenchmarkAdapter` 导入，但不应成为我们 SDK 的根模型。[Harbor Core Concepts](https://www.harborframework.com/docs/core-concepts) 也明确把 benchmark adapter 定义为把既有 benchmark 转换成 Harbor task format，因此我们可以借鉴其“任务目录 + 环境 + verifier + parity”做法，但输出应是自己的 canonical model。[Harbor Adapters](https://www.harborframework.com/docs/datasets/adapters)

BrowserGym 代表另一类：环境给 Agent 返回观测，Agent 在 action space 中选择动作，环境再返回下一次观测。因此接入重点是 `ObservationCodec` 和 `ActionCodec`，而不是解析某种 Agent 框架。[BrowserGym Core API](https://browsergym.readthedocs.io/latest/core/core.html)

MCP、ACP、A2A 应当作为可选的 protocol binding：

- MCP 适合把工具发现、工具调用、资源和取消映射到 `ActionSpec / Action / Transition / Event`，但 MCP 不应成为 SDK 的领域核心。[MCP Specification](https://modelcontextprotocol.io/specification/2025-03-26/index)
- ACP 适合把外部 Agent 当作独立进程，通过 session、prompt、update、cancel 与 Runtime 交互；这是 Agent transport，不是 AgentPolicy 的内部实现。[Agent Client Protocol](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/overview.mdx)
- A2A 适合多 Agent 场景中的消息、任务和 Artifact 交换，可映射到 `SendMessage / Delegate / Event / Artifact`；单 Agent benchmark 不应因此依赖 A2A。[A2A Specification](https://google-a2a.github.io/A2A/specification/)

### 3.11 Agent 如何使用 Benchmark

推荐的调用关系是：

```text
BenchmarkAdapter（以 BenchmarkPack 分发）
  → Canonical Scenario / Environment / Verifier
  → Runtime
      → Native AgentPolicy
      或 External AgentEndpoint（ACP / CLI / HTTP / MCP binding）
  → TrialRecord
  → Source Verifier + Native Evaluator
  → Parity Report
```

这里的关键是：**Benchmark 适配发生在环境和评测边界，Agent 只实现统一的决策协议。** Agent 可以是我们自己定义的 `AgentPolicy`，也可以作为一个独立进程暴露 `AgentEndpoint`；但 Runtime 不应理解某个 Agent 框架的 Node、Graph、Run、Span 等内部对象。

对于每个外部 benchmark，接入完成的验收标准应是：

1. 原始任务可以被完整列出、筛选、版本化和复现。
2. Agent 只能看到 benchmark 允许暴露的 observation，不能读到 hidden ground truth 或 verifier。
3. 原始动作、环境变化、产物和 verifier 结果都能映射到 Event / Transition。
4. Oracle 或参考解在我们的 Runtime 上可以通过。
5. 在约定样本上与原 benchmark 做 parity，记录成功率、指标定义、运行次数和差异原因。
6. 原始 benchmark 的失败、环境故障、适配错误和 Agent 失败可以分开统计。

## 4. 指标体系

近期文献的共识是：只报告平均任务成功率会掩盖过程错误、不稳定性、安全风险和成本。2025 年 Agent 评测综述也特别指出成本效率、安全、鲁棒性和细粒度评测仍是缺口。

来源：[Survey on Evaluation of LLM-based Agents, 2025/2026](https://arxiv.org/abs/2503.16416)

### 4.1 结果指标

第一优先级，应尽量由确定性 Verifier 计算：

- `task_success`：最终目标是否完整达成。
- `goal_completion`：已满足目标条件数 / 总目标条件数。
- `state_match`：最终环境状态与目标状态的匹配度。
- `artifact_validity`：产物能否解析、运行、编译或通过测试。
- `answer_correctness`：最终答案正确度。
- `constraint_satisfaction`：必需约束满足比例。

### 4.2 进度与轨迹指标

用于解释“为什么失败”和识别部分完成：

- `milestone_coverage`：完成的关键里程碑比例。
- `forbidden_action_rate`：禁止动作触发次数 / 动作数。
- `tool_selection_accuracy`：工具选择是否适合当前目标。
- `argument_validity`：工具参数 Schema 和业务约束正确率。
- `action_success_rate`：成功执行动作数 / 动作请求数。
- `trajectory_validity`：轨迹是否满足关键时序和依赖约束。
- `recovery_rate`：遇到工具、环境或模型错误后恢复成功比例。
- `redundant_action_rate`：重复、无贡献动作占比。
- `grounding_rate`：动作是否有当前观测或证据支撑。
- `delegation_accuracy`：是否委派给正确参与者并传递必要上下文。

### 4.3 可靠性指标

Agent 是随机系统，必须对同一 Case 重复运行：

- `pass@1`：单次运行成功率。
- `pass^k`：同一任务连续 k 次全部成功的可靠性指标。
- `score_variance`：同一 Case 多次运行的得分方差。
- `outcome_entropy`：结果类别的不确定程度。
- `worst_case_score`：重复运行中的最差得分。
- `failure_mode_frequency`：各失败模式出现频率。
- `confidence_interval`：成功率或平均分的置信区间。

不要把“自动重试后成功”算作第一次 Trial 成功；基础设施重试和独立重复实验必须分开。

### 4.4 效率与预算指标

- `wall_time_ms`：端到端耗时。
- `active_compute_ms`：Agent 实际计算时间。
- `model_latency_ms`、`tool_latency_ms`、`environment_latency_ms`。
- `turn_count`、`model_call_count`、`tool_call_count`。
- `input_tokens`、`output_tokens`、`cached_tokens`。
- `total_cost`。
- `cost_per_success`：总成本 / 成功 Trial 数。
- `steps_per_success`：成功任务的平均步骤数。
- `budget_violation_rate`。

### 4.5 鲁棒性指标

- `perturbation_success_rate`：输入改写、噪声或顺序变化后的成功率。
- `tool_failure_recovery`：工具超时、报错或返回脏数据后的恢复率。
- `dynamic_event_adaptation`：环境异步变化后的成功率。
- `state_consistency`：长轨迹中状态约束保持程度。
- `checkpoint_recovery_rate`：中断后从快照恢复成功比例。
- `performance_drop_under_noise`：干扰条件相对基线的性能下降。
- `time_horizon_p50/p80`：在 50%/80% 成功概率下可完成任务的人类基准时长。

### 4.6 安全与治理指标

- `unauthorized_action_rate`：越权动作率。
- `unsafe_side_effect_rate`：产生危险副作用的 Trial 比例。
- `policy_violation_rate`。
- `prompt_injection_attack_success_rate`。
- `sensitive_data_exposure_rate`。
- `approval_bypass_rate`。
- `reward_hacking_rate`。
- `audit_completeness`：关键动作是否都有主体、时间和证据记录。

安全分不能简单并入平均质量分。出现高危越权时，应支持硬门禁直接判失败。

### 4.7 用户协作指标

- `clarification_precision`：真正缺信息时发起澄清的比例。
- `unnecessary_clarification_rate`。
- `user_action_success`：Agent 指导用户完成必要动作的成功率。
- `human_intervention_rate`。
- `escalation_precision`：需要人工时是否正确升级。
- `conversation_turns_to_resolution`。

### 4.8 最终输出质量

- 正确性、完整性、相关性。
- 证据忠实度、引用正确性。
- 格式或 Schema 合规性。
- 可读性、简洁性和风格遵循。
- 对开放式任务使用 LLM Judge 或人工评分时，应保存 rubric、judge 模型、prompt 版本、证据、理由和置信度。

## 5. Score 数据契约

每个分数都应该可解释、可聚合、可追溯：

```python
@dataclass(frozen=True)
class MetricDefinition:
    name: str
    scope: Literal["step", "trial", "run"]
    value_type: Literal["bool", "number", "category", "text"]
    direction: Literal["higher", "lower", "target"]
    aggregation: str | None
    threshold: float | None
    version: str

@dataclass(frozen=True)
class Score:
    metric: str
    value: bool | float | str
    scope_id: str
    method: Literal["deterministic", "model", "human", "aggregate"]
    evaluator_version: str
    evidence_refs: tuple[str, ...]
    rationale: str | None
    confidence: float | None
```

不建议第一版就计算一个“Agent 总分”。首先保留各指标；若必须综合，应由独立、带版本的 `Scorecard` 定义权重和硬门禁。

## 6. 失败分类

Trial 结果不能只有 `success/failed`。建议至少使用：

```text
agent.reasoning
agent.communication
agent.invalid_action
agent.policy_violation
agent.reward_hacking
agent.budget_exhausted
environment.tool_error
environment.state_conflict
infrastructure.timeout
infrastructure.worker_crash
verifier.invalid_case
evaluator.error
```

其中 infrastructure 与 invalid_case 不应计入 Agent 能力失败率，但必须单独报告。

## 7. 推荐的 SDK 模块边界

```text
agent_eval/
├── agent/          # AgentDefinition, AgentState, AgentPolicy, Decision
├── scenario/       # Scenario, Goal, Criterion, ActorSpec
├── environment/    # Environment, Snapshot, Transition, ActionSpec
├── runtime/        # Runner, lifecycle, budgets, retry, cancellation
├── trace/          # append-only Event, Step projection, exporter
├── verify/         # deterministic verifier and evidence
├── evaluate/       # Evaluator, RunEvaluator, Score, Scorecard
├── dataset/        # dataset manifest, case version, split
├── artifact/       # file/output references and hashes
├── report/         # aggregation, confidence interval, regression gate
├── benchmarks/     # BenchmarkAdapter packages, manifest, codecs, parity checks
├── protocols/      # optional MCP / ACP / A2A / CLI bindings
└── storage/        # local JSONL/SQLite first; service client later
```

## 8. 推荐开发顺序

### M0：协议冻结

先定义并测试：Scenario、AgentPolicy、Decision、Environment、Transition、TrialRecord、Score。暂时不接模型、不做页面。

### M1：本地评测内核

实现单 Agent、同步环境、工具动作、事件日志、确定性 Verifier、Trial/Run Evaluator、JSONL 导出。

### M2：真实 Agent 能力

加入异步 Runtime、Token/成本预算、用户模拟器、环境 tick、随机种子、多次 Trial 和可靠性统计。

### M3：服务化

再开发数据集、Run、Trace、Score、Artifact 的 API 与持久化服务。服务端第一阶段只接收结果，不执行用户代码。

### M4：远程执行

最后增加队列、Worker、容器沙箱、审批和恢复。远程代码执行是安全边界，不应与 SDK MVP 同时启动。

## 9. 最终建议

这套 SDK 的独特性不应是“又一个 Dataset + function + scorer”，而应是以下四点：

1. 把 Agent 明确定义成 `Observation + State + Context -> Decision`。
2. 把 Environment 定义为状态、副作用、时间和可见性的唯一所有者。
3. 同时支持结果验证、轨迹评分、可靠性、效率和安全门禁。
4. 用 append-only Event 保存原始事实，并从中构造 Step、Trace、指标和报告。

因此第一版真正需要冻结的核心不是 Web API，而是 `Decision`、`Transition`、`Event` 和 `Score` 四份协议。只要这四份协议稳定，后续本地 SDK、远程 Runner、评测服务和 UI 都可以在其上演进。

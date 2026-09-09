# 评测协议与 Agent 接入规范

## 1. 设计目标

协议的目标不是规定 Agent 内部如何思考，而是统一 Agent 与评测环境之间的边界。

协议必须满足：

- Agent 不需要为每个 Benchmark 改写内部逻辑。
- Benchmark 不需要为每个 Agent 单独实现调用链路。
- 每一步动作和观测都可以被记录、重放和评分。
- 协议能够表达工具调用、消息发送、代码执行、文件修改和最终提交。
- 同一个任务可以通过 HTTP、MCP、CLI 和进程内插件接入。

## 2. 统一任务模型

```json
{
  "task_id": "tau2-retail-001",
  "benchmark": {
    "id": "tau2",
    "version": "3.0.0",
    "adapter_version": "0.1.0"
  },
  "task": {
    "instruction": "根据客服政策帮助用户完成请求",
    "goal": "完成订单取消并遵守退款规则"
  },
  "context": {
    "policy": "...",
    "user_profile": "..."
  },
  "actions": [
    {
      "name": "search_order",
      "description": "查询订单",
      "parameters": {
        "type": "object",
        "properties": {
          "order_id": {"type": "string"}
        },
        "required": ["order_id"]
      },
      "side_effect": "read"
    },
    {
      "name": "cancel_order",
      "description": "取消订单",
      "parameters": {
        "type": "object",
        "properties": {
          "order_id": {"type": "string"}
        },
        "required": ["order_id"]
      },
      "side_effect": "write"
    },
    {
      "name": "finish",
      "description": "提交最终结果",
      "parameters": {
        "type": "object",
        "properties": {
          "summary": {"type": "string"}
        },
        "required": ["summary"]
      },
      "side_effect": "terminal"
    }
  ],
  "limits": {
    "max_steps": 50,
    "timeout_seconds": 900,
    "max_cost_usd": 1.0
  }
}
```

## 3. Observation

环境返回的内容统一为 Observation：

```json
{
  "observation_id": "obs-003",
  "type": "tool_result",
  "source": "benchmark",
  "content": {
    "order_id": "A001",
    "status": "refundable"
  },
  "is_error": false,
  "timestamp": "2026-09-04T10:00:00Z"
}
```

支持的 `type`：

- `user_message`
- `tool_result`
- `text`
- `image`
- `file`
- `environment_state`
- `system_event`
- `error`

## 4. Action

Agent 输出统一 Action：

```json
{
  "action_id": "act-003",
  "name": "cancel_order",
  "arguments": {
    "order_id": "A001"
  },
  "source": "agent",
  "timestamp": "2026-09-04T10:00:02Z"
}
```

平台在执行前必须完成：

- Action 名称校验。
- 参数 JSON Schema 校验。
- 当前状态下是否允许调用校验。
- Agent 权限和工具权限校验。
- 预算和步数校验。
- 高风险动作审批或拦截。

## 5. Benchmark Adapter 接口

```python
class BenchmarkAdapter(Protocol):
    id: str
    version: str

    async def list_tasks(self, query: TaskQuery) -> list[TaskRef]: ...

    async def prepare(self, task_id: str, run: RunContext) -> TaskSpec: ...

    async def reset(self, session: SessionContext) -> Observation: ...

    async def step(
        self, session: SessionContext, action: Action
    ) -> list[Observation]: ...

    async def finish(
        self, session: SessionContext, action: Action
    ) -> list[Observation]: ...

    async def score(self, session: SessionContext) -> ScoreResult: ...

    async def cleanup(self, session: SessionContext) -> None: ...
```

Adapter 负责 Benchmark 特有的语义，平台 Runner 不允许写死：

- 原始任务如何加载。
- 环境如何准备。
- Actions 如何映射到原生工具或 API。
- Observation 如何转换回来。
- 何时结束。
- 原始测试如何执行。
- 原始分数如何解释。

## 6. Agent Adapter 接口

```python
class AgentAdapter(Protocol):
    id: str
    version: str

    async def provision(self, task: TaskSpec, run: RunContext) -> AgentHandle: ...

    async def start(self, handle: AgentHandle) -> None: ...

    async def send_task(self, handle: AgentHandle, task: TaskSpec) -> None: ...

    async def send_observation(
        self, handle: AgentHandle, observation: Observation
    ) -> None: ...

    async def receive_action(
        self, handle: AgentHandle, timeout: float
    ) -> Action | None: ...

    async def stop(self, handle: AgentHandle, reason: str) -> None: ...

    async def collect_artifacts(self, handle: AgentHandle) -> list[Artifact]: ...

    async def cleanup(self, handle: AgentHandle) -> None: ...
```

## 7. Runner 主循环

```python
task = await benchmark.prepare(task_id, run_context)
agent = await agent_adapter.provision(task, run_context)
await agent_adapter.start(agent)
await agent_adapter.send_task(agent, task)

observation = await benchmark.reset(session)
while not session.terminal:
    await trace.record_observation(observation)
    await agent_adapter.send_observation(agent, observation)
    action = await agent_adapter.receive_action(agent, timeout=step_timeout)

    if action is None:
        session.finish("agent_no_action")
        break

    await validate_action(action, task.actions, session.policy)
    await trace.record_action(action)
    observations = await benchmark.step(session, action)
    observation = observations

score = await benchmark.score(session)
artifacts = await agent_adapter.collect_artifacts(agent)
await persist_result(score, artifacts, trace)
```

## 8. 接入模式

### 8.1 HTTP

推荐作为平台对外的第一协议。外部 Agent 只需提供一个受认证的服务：

```text
POST /v1/sessions
POST /v1/sessions/{id}/input
GET  /v1/sessions/{id}/events
POST /v1/sessions/{id}/cancel
```

平台负责推送 Task、Context 和 Observation，Agent 返回 Action。

### 8.2 MCP

Benchmark Adapter 为每个 Session 启动临时 MCP Server，把 actions 注册为 tools；Agent 通过 MCP 进行工具调用。MCP Server 必须使用 Session 级凭证和网络范围。

### 8.3 CLI

平台把任务写入容器中的 `instruction.md` 或标准输入，Agent 通过 stdout 输出 JSONL Action，环境 Observation 写入 stdin 或事件文件。

### 8.4 代码包

代码包需要提供固定入口：

```text
agent.yaml
run.sh 或 run.py
requirements.lock / uv.lock / package-lock.json
```

入口通过环境变量获取：

```text
EVAL_SESSION_ID
EVAL_TASK_PATH
EVAL_ACTION_ENDPOINT
EVAL_EVENT_ENDPOINT
EVAL_ARTIFACT_DIR
```

任何代码包都在独立 Worker 中运行，不能在 API 服务进程加载。

代码包或 Git 仓库还必须满足以下导入门禁：

- 根目录（允许外层单一仓库目录）包含 `agent.yaml`。
- `agent.yaml` 声明的启动入口真实存在。
- 至少包含一个可复现依赖锁：`requirements.lock`、`uv.lock`、`poetry.lock`、`package-lock.json`、`pnpm-lock.yaml` 或 `yarn.lock`。
- 服务暴露 `GET /health` 和 `POST /invoke`；Agentic 任务使用 `agentic-bench/v1` 信封。
- Agent 编排、模型调用、工具和检索分别使用 DeepEval 的 `agent`、`llm`、`tool`、`retriever` span 类型埋点。
- 代码包不得包含明文 API Key；凭证由平台密钥库在实例启动时注入。
- 容器默认非 root、只读根文件系统并设置 CPU、内存和超时限制。

可直接复制的骨架位于 `examples/agent_package_template/`。DeepEval 目前推荐使用
`@observe` 记录组件 span，并通过 `update_current_trace` / `update_current_span`
补齐评测输入、输出和元数据。

### 8.5 SDK 接入已有 Agent

已有 Agent 使用平台 SDK 接入，不登记为 HTTP Endpoint。平台为每个 Agent 生成独立
`evk_` 密钥，SDK 将 NDJSON 事件批量发送到 `POST /v1/traces`。

- `evk_` SDK 密钥只拥有 Trace 写入权限。
- `evl_` 部署 Token 只用于调用平台部署的 Agent。
- OpenAI、Anthropic 等模型密钥由平台密钥库单独加密保存。
- DeepEval 的 `@observe` 与平台 `@observe` 可以嵌套使用：前者承载评测语义，后者负责将统一事件发送到本平台。
- 每个事件必须包含 `event_id`、`trace_id`、`event_type`；服务端按 Agent 与事件 ID 幂等写入。
- 单批最多 1000 个事件、5 MiB；SDK Key 可独立轮换和吊销。

## 9. Trace 事件模型

平台统一记录 Event，而不是只记录文本日志：

```json
{
  "event_id": "evt-001",
  "run_id": "run-001",
  "trial_id": "trial-001",
  "session_id": "session-001",
  "parent_event_id": null,
  "event_type": "tool_call",
  "actor": "agent",
  "name": "search_order",
  "input": {"order_id": "A001"},
  "output": {"status": "refundable"},
  "status": "success",
  "started_at": "2026-09-04T10:00:00Z",
  "ended_at": "2026-09-04T10:00:01Z",
  "usage": {
    "input_tokens": 500,
    "output_tokens": 120,
    "cost_usd": 0.003
  },
  "metadata": {
    "agent_version": "agent-a@1.2.0",
    "benchmark_adapter_version": "tau2@0.1.0"
  }
}
```

## 10. 评分协议

评分结果分为三层：

```text
原始评分：Benchmark 原有的 pass/fail、reward、patch test 等
过程评分：工具调用、步数、错误恢复、违规动作、轨迹质量
平台评分：能力维度加权、阈值判定、成本/质量效率、回归结论
```

示例：

```json
{
  "task_id": "tau2-retail-001",
  "scores": [
    {
      "dimension_id": "tool_selection",
      "value": 1.0,
      "status": "pass",
      "evidence": ["evt-002", "evt-003"]
    },
    {
      "dimension_id": "policy_compliance",
      "value": 0.0,
      "status": "fail",
      "evidence": ["evt-004"],
      "reason": "在未确认可退款前执行了取消动作"
    }
  ],
  "aggregate": {
    "value": 0.5,
    "status": "fail"
  }
}
```

LLM Judge 的结果必须保留：

- Judge 模型和版本。
- Judge prompt 版本。
- 输入证据引用。
- 原始输出。
- 解析后的结构化分数。
- 置信度和人工复核状态。

## 11. Benchmark 适配验收

每个 Benchmark Adapter 必须完成：

1. 能列出任务并生成稳定 Task ID。
2. 能完成环境初始化和清理。
3. Action/Observation 转换不丢失原有语义。
4. Oracle 或参考 Agent 能通过预期任务。
5. 原始运行器与适配运行器做 parity 对比。
6. 记录 adapter 版本、数据集版本和评分器版本。
7. 任务失败时保留轨迹和环境日志。

## 12. 版本与可复现性

一次 Run 必须冻结：

```text
agent_version
agent_source_digest
model_provider
model_version
model_parameters
system_prompt_version
tool_schema_version
benchmark_version
dataset_version
adapter_version
scorer_version
runtime_image_digest
policy_version
```

缺少这些信息的 Run 只能标记为 exploratory，不能进入正式报告或排行榜。

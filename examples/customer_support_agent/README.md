# 客服订单/退款 Agent（SDK 埋点接入）

一个「使用 SDK 接入」的客服订单退款 Agent：核心策略模型走真实的 OpenAI 兼容 LLM
（DashScope / vLLM / Qwen / OpenAI 通用），无 Key 或调用失败时自动回退到确定性规则。
它**不是一个 HTTP 服务**——Agent 作为普通 Python 可调用对象运行，通过 `agent_eval` SDK
把 agent / llm / tool / retriever 统一事件经 `PlatformSink` 批量上报到控制面的 `POST /v1/traces`。

调用链：

```text
support_agent (agent)
├── refund_policy (retriever)   —— 政策问答
├── lookup_order (tool)         —— 订单查询
├── policy_model (llm)          —— 退款决策
└── create_refund (tool)        —— 允许退款时的副作用
```

## 安装

在仓库根目录：

```bash
python -m pip install -e '.[deepeval]'   # 安装 agent_eval（本仓库 SDK）+ deepeval
python -m pip install httpx               # LLM 客户端与注册脚本依赖
```

## 本地离线运行（不需要平台）

```bash
python -m examples.customer_support_agent --local
```

事件写入 `.agent-eval/runs/customer-support/events.jsonl`，包含 `agent/llm/tool/retriever`
各 span。

## 上报到平台（SDK 接入）

1. 起后端控制面：

   ```bash
   python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
   ```

2. 一次性建账（等价于控制台「添加 Agent → 使用 SDK 接入」），拿到 `evk_` 密钥：

   ```bash
   python -m examples.customer_support_agent.register
   # 输出: export EVAL_LOOM_BASE_URL=...  /  export EVAL_LOOM_SDK_KEY=evk_...
   ```

3. 运行 Agent，逐条上报 Trace：

   ```bash
   EVAL_LOOM_BASE_URL=http://127.0.0.1:8787 \
   EVAL_LOOM_SDK_KEY=evk_... \
   python -m examples.customer_support_agent
   ```

4. 在控制台该 Agent 详情页查看 `sdk_trace_count` 递增；`/v1/traces` 返回 202。

## 接入真实模型

LLM 客户端支持两种后端，由环境变量自动切换（缺失即走确定性兜底）：

### Anthropic 兼容（Messages API，如 grok-4.5 代理）

```bash
export ANTHROPIC_BASE_URL=http://216.167.7.16:8080   # 基址，自动追加 /v1/messages
export ANTHROPIC_AUTH_TOKEN=sk-...                   # 或 ANTHROPIC_API_KEY
export ANTHROPIC_MODEL=grok-4.5
```

请求走 `POST {base}/v1/messages`，携带 `x-api-key` + `Authorization: Bearer` + `anthropic-version`；
响应会过滤 `thinking` 块、只取 `text` 块。

### OpenAI 兼容（chats/completions）

```bash
export LLM_API_KEY=...          # 或 OPENAI_API_KEY / DASHSCOPE_API_KEY
export LLM_BASE_URL=https://... # 可选，自动追加 /chat/completions
export LLM_MODEL=qwen-plus      # 可选，默认按 provider 推断
```

## 测试

```bash
python -m pytest tests/test_customer_support_agent.py -q      # 兜底与无 Key 单测
deepeval test run examples/test_customer_support_agent.py     # DeepEval 冒烟（可选）
```

## 平台能力：Memory / 知识库 / 公共 Skill / MCP

除了核心退款流程，这个 Agent 还具备三类可被平台扩展的能力：

1. **自带 Memory** —— 纯客户端、进程间持久的短期（对话轮次）+ 长期（抽取事实）记忆，
   通过 `--memory <file>` 落盘 JSON。平台不接管私有记忆，只负责下面三类公共资源。

2. **平台知识库** —— 控制台可补充/拓展 workspace 级（公共）或 agent 级知识条目；Agent 在
   政策问答时用知识库内容作答（本地退款政策为兜底）。

3. **公共 Skill + MCP** —— 平台登记 workspace 公共 / agent 级 skill（指令片段）与 MCP server
   （transport + url），Agent 通过 SDK key 拉取并注入决策模型的上下文。

对应后端新增接口（`backend/app/api/context.py`）：

```text
GET/POST /api/knowledge        DELETE /api/knowledge/{id}
GET/POST /api/skills           DELETE /api/skills/{id}
GET/POST /api/mcp-servers      DELETE /api/mcp-servers/{id}
GET /v1/agent-context          # 用 evk_ key 读取，返回 {knowledge, skills, mcp_servers}
```

Agent 启动时通过 `fetch_platform_context(base_url, sdk_key)` 拉取 `/v1/agent-context`，
`main.py` 会自动装载（无平台/无 Key 时静默降级为空上下文）。种子数据在 `eval-dev` 工作区
预置了 `退款政策`/`售后时效` 两条知识、`退款决策` skill 与 `crm` MCP server。
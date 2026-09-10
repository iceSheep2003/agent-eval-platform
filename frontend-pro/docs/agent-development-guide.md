# Agent 开发、上传与运行规范

本文既是开发者规范，也是可直接交给 AI 的实现契约。目标是产出一个“麻雀虽小、五脏俱全”的 Agent：代码可以很少，但必须**可运行、可配置、可观测、可评测、可升级、可回退**，而不是只包装一次模型调用。

> “平台强制”会在版本冻结或 conformance 接口中自动检查；“交付要求”暂不一定自动拦截，但仍是可发布 Agent 的验收标准。

## 1. 什么是完整 Agent

一个完整 Agent 包含六部分：

1. **代码**：标准入口、任务理解、规划/路由、执行、输出与异常处理；
2. **运行配置**：模型、密钥、超时、步骤数和成本边界；
3. **能力资产**：按需绑定 Skill、MCP Server、知识库，不内联其内容；
4. **状态管理**：明确无状态，或使用平台注入的 memory；
5. **可观测性**：能追踪 Agent、模型、检索、工具、错误和用量；
6. **版本治理**：不可变版本经过 TEST、LIVESH、LIVE，并支持回退。

最低验收标准：

| 方面 | 最低要求 | 类型 |
|---|---|---|
| 可调用 | 入口可导入，接受平台标准参数 | 平台强制 |
| 可完成任务 | 有职责、边界、处理步骤、输出契约 | 交付要求 |
| 可配置 | 密钥和能力通过平台注入/绑定 | 平台强制 |
| 可隔离 | 明确 memory scope，无跨会话全局状态 | 平台强制 |
| 可恢复 | 处理无知识、工具失败、超时和取消 | 交付要求 |
| 可治理 | 有测试、Trace、版本门禁和回退路径 | 交付要求 |

仅返回固定文本的函数可用于连通性测试，但不是可发布 Agent。

## 2. 先定义可验收的职责

开发前用一句话说明目标、能力和边界，例如：

> 根据平台知识库回答售后政策；需要订单事实时调用订单 MCP；高风险操作必须确认或转人工；回答必须说明依据；缺少可靠信息时不得编造。

至少明确：目标用户与任务、支持/不支持的输入、何时使用各类能力、哪些动作需确认或拒绝、输出格式与成功标准、最大步骤/超时/重试/成本。

信息不足时，AI 应采用保守默认值并在 README 的“待确认项”列出，不得虚构业务规则、工具名、知识内容或平台 API。

## 3. 标准交付物

推荐的小型 Python Agent 目录：

```text
my_agent/
├── agent.py              # 平台入口与单次运行编排
├── prompts.py            # 提示词模板，不含动态知识和密钥
├── policy.py             # 业务边界、确认、拒绝和降级规则
├── pyproject.toml        # 固定 Python 与依赖版本
├── README.md             # 职责、配置、能力、运行、测试、待确认项
└── tests/
    ├── test_agent.py     # 正常、多轮、结构化输出
    └── test_failures.py  # 无知识、工具失败、超时、取消、隔离
```

可以按复杂度合并文件，但交付内容不能缺失。不得上传 `.env`、私钥、Token、生产数据、缓存、虚拟环境或本地构建产物。

README 必须包含：职责与边界、入口地址、输入输出示例、所需 secrets、memory scope、能力依赖、失败/降级策略、本地运行与测试命令。

## 4. 平台入口协议

`entrypoint` 必须是可导入 callable，格式为 `module.path:callable`，例如 `my_agent.agent:run`。

| 参数 | 要求 | 含义 |
|---|---|---|
| `input` | 必须 | 当前公开输入，名称不能改 |
| `messages` | 必须，或接受 `**kwargs` | 完整多轮上下文 |
| `secrets` | 按需声明 | 平台注入的模型/MCP 密钥 |
| `memory` | 使用平台记忆时声明 | 已按作用域隔离的记忆句柄 |
| `capabilities` | 使用能力资产时声明 | 已解析的 Skill、MCP、知识库版本快照 |

平台只传入口实际声明的可选参数。推荐完整声明，以便后续扩展能力。

### 推荐入口骨架

```python
from collections.abc import AsyncIterator
from typing import Any


async def run(
    input: str,  # noqa: A002
    messages: list[dict[str, Any]] | None = None,
    secrets: dict[str, str] | None = None,
    memory: Any = None,
    capabilities: dict[str, dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    """一次调用对应一次隔离、有限、有清理过程的 Agent 运行。"""
    history = messages or []
    runtime_secrets = secrets or {}
    resolved_capabilities = capabilities or {}
    recalled = await memory.recall(input, top_k=5) if memory else []

    plan = build_plan(input, history, recalled, resolved_capabilities)
    completed = False
    try:
        async for chunk in execute_plan(plan, runtime_secrets):
            yield chunk
        completed = True
    finally:
        await close_run_resources()

    if completed and memory:
        await memory.remember("user", input)
        await memory.remember("assistant", plan.final_answer)
```

`build_plan`、`execute_plan`、`close_run_resources` 是职责占位符，不是平台 API。AI 必须按项目已有 SDK 实现；若没有可用 SDK，应通过 Protocol/adapter 隔离接入点并提供测试替身，不得编造已可用的平台函数。

普通函数/协程可返回字符串或 JSON。LIVE 版本必须使用异步生成器真流式输出，每次 `yield` 字符串增量。流式中途失败时不要伪装成功；平台会保留已产生内容并记录错误。

## 5. 单次运行生命周期

一次入口调用必须形成闭环：

1. **初始化**：读取本次注入配置，创建调用级客户端；
2. **理解输入**：结合 `input`、`messages` 判断任务与缺失信息；
3. **恢复状态**：仅从当前 memory 分区读取必要上下文；
4. **规划与路由**：选择 Skill，决定是否检索或调用 MCP；
5. **执行**：校验工具参数和结果，限制步骤、超时、成本与重试；
6. **生成结果**：返回答案/JSON，必要时包含依据和降级说明；
7. **持久化与观测**：成功后写必要记忆，记录模型、检索、工具、错误与用量；
8. **终止清理**：成功、失败、超时、取消都关闭连接和临时资源。

必须遵守：调用可并发且互不污染；所有循环有上限；只对幂等操作有限重试；不吞取消和超时；副作用工具需校验权限并对高风险动作确认；失败后不写“已完成”记忆；知识不足时不编造业务事实。

## 6. Skill、MCP、知识库装配

能力资产在平台**独立配置、版本化、评测**，再绑定给 Agent。标准流程：

1. 在对应管理页创建能力资产；
2. 完成配置、校验或健康检查；
3. 将能力绑定到 Agent；
4. Run 开始时平台按通道解析版本并冻结绑定快照；
5. 通过 `capabilities` 注入，Trace 按名称归因；
6. 对比评测时可只覆盖某一能力版本，不改 Agent 代码。

### Skill

Skill 是任务说明与行为边界，不是独立 entrypoint。至少配置 `instructions`、`input_schema`、`output_schema`、`allowed_tools`、`max_steps`、`timeout_ms`。Agent 必须遵守工具白名单、步骤和超时限制。

### MCP Server

至少配置 `endpoint`、`transport`（`stdio`/`sse`/`streamable-http`）、使用 `secret_ref` 的认证，以及工具名称、说明和输入 Schema。调用前校验参数、调用后校验业务结果；明确超时、幂等重试、失败降级与人工确认。工具名必须与平台注册表一致，也是 Trace 归因锚点。

### 知识库

至少配置数据源、`index_name`、embedding、切分大小/重叠、召回模式、`top_k`、可选 reranker 与租户隔离。Agent 应区分“无召回”与“证据不足”，并按要求返回来源。

### 禁止内联能力

若 Agent spec 出现以下字段，只能是资产引用列表：

```json
{
  "skills": [{"asset_id": "skill_xxx"}],
  "mcp_servers": [{"asset_id": "mcp_xxx"}],
  "knowledge_bases": [{"asset_id": "kb_xxx"}]
}
```

优先在平台界面绑定；上例只说明引用形态。不得内联 Skill 指令、MCP Token/完整服务配置或知识正文。

## 7. Memory 与并发隔离

平台托管的 `package` / `github` Agent 必须声明：

```json
{"memory": {"scope": "thread"}}
```

| scope | 场景 |
|---|---|
| `thread` | 会话隔离，默认推荐 |
| `tenant` | 同一租户确需共享的事实 |
| `agent_version` | 版本全局共享且经过审查的数据 |
| `stateless` | 明确不使用记忆 |

平台 memory 可提供 `recent`、`recall`、`remember`、`save_fact` 等能力，实际以运行环境接口为准。`sdk` 接入自行管理记忆，但仍须隔离租户和会话。

禁止用模块级可变状态保存会话：

```python
# 错误：并发调用会串数据
_session = {}

def run(input, messages=None):
    global _session
    _session["last"] = input
    return input
```

会话状态放 memory，调用状态放局部变量。模块级只允许真正只读的常量或资源。

## 8. Secrets 与运行配置

版本只声明名称，不保存值：

```json
{
  "secrets": [
    {"name": "llm_api_key", "required": true},
    {"name": "mcp_token", "required": false}
  ]
}
```

平台配置流程：

1. `POST /api/secrets` 加密存储，只返回指纹；
2. `POST /api/agents/{id}/versions/{vid}/secrets/{channel}/bind` 按通道绑定；
3. TEST 与 LIVE 可使用不同密钥；轮换只移动绑定，不改版本。

缺少 required secret 时立即失败。任何 `password`、`token`、`api_key`、`secret`、`access_key` 明文出现在版本中都会被拒绝；日志、Trace、异常和输出也不得泄密。

## 9. 接入与上传

| `connect_type` | 场景 | 必填 |
|---|---|---|
| `package` | ZIP / TAR.GZ，由平台托管 | `artifact_id`、`entrypoint` |
| `github` | 固定仓库引用构建 | `repository`、`ref`、`entrypoint` |
| `sdk` | Agent 外部运行，平台接收 Trace | 无托管入口字段 |

package/github 要求：入口从包根正常导入；依赖固定且安装无需交互；导入时不发业务请求；README 完整；Git 引用可追溯。`sdk` 不做同样的入口与 memory 检查，但仍须保证版本、Trace、隔离和归因。

## 10. 版本发布生命周期

Agent 身份长期存在；上传代码产生不可变版本；一次 Run 是版本的一次执行。

```text
开发与本地测试
  → 上传 / 创建不可变版本
  → 静态校验 + 入口验收
  → TEST：固定数据集离线评测
  → LIVESH：真实流量影子验证，结果不返回用户
  → LIVE：正式接收请求
  → 持续监控、Trace 回流、下一候选版本 / 异常回退
```

三个通道可同时指向不同版本。晋级移动通道指针，不修改版本。每次 Run 保存 Agent 和能力版本快照，因此历史结果不随 Skill、MCP 或知识库升级而漂移。

## 11. 平台强制检查

冻结版本时检查：`kind`/`connect_type`/必填字段、memory scope、明文密钥、能力引用列表。

运行时检查：entrypoint 可导入、接受 `input`、接受 `messages` 或 `**kwargs`、没有调用间修改的模块全局状态；LIVE 还要求异步生成器流式输出。

```text
POST /api/agents/{id}/versions
GET /api/agents/{id}/versions/{vid}/conformance
GET /api/agents/{id}/versions/{vid}/conformance?require_streaming=true
```

建议把 conformance 和核心数据集 Run 加入 CI。协议合规不等于任务质量达标。

## 12. 可直接交给 AI 的生成指令

复制下面整段，并填写任务说明：

```text
请严格按照《Agent 开发、上传与运行规范》生成一个可上传的完整 Agent 工程。

任务说明：
【填写目标用户、任务、边界、输出格式、Skill/MCP/知识库需求、风险动作】

交付要求：
1. 先复述职责、假设和待确认项；信息不足时用保守默认值，不虚构业务规则、
   平台 API、MCP 工具名、知识内容或凭证。
2. 输出可直接打包的完整目录，至少有入口、策略/提示词、固定依赖、README 和测试。
3. entrypoint 使用 module.path:callable；入口接受 input、messages、secrets、memory、
   capabilities，并提供异步生成器流式输出。
4. 实现初始化、任务理解、状态恢复、规划路由、执行、结果生成、成功后记忆、
   Trace 接入点和 finally 清理；循环、超时、重试、成本都有边界。
5. Skill、MCP、知识库只通过 capabilities 消费；另给“平台配置清单”，列出要创建
   和绑定的资产及字段，但不编造 asset_id。
6. 密钥只列入 secrets 声明；不得生成真实值、.env 或泄密日志。
7. 测试覆盖正常、多轮、无知识、工具失败、超时/取消、并发隔离和流式输出。
8. README 写明入口、输入输出、memory scope、secrets、能力依赖、降级、本地运行/
   测试、打包、上传字段和发布步骤。
9. 若项目没有真实平台 SDK，用 Protocol/adapter 隔离接入点并提供测试替身，
   不得假造 SDK 方法。
10. 生成后逐项对照规范自检。

最终顺序：假设与待确认项 → 文件树 → 全部文件内容 → 平台配置清单
→ 测试命令与结果 → 上传参数 → 自检结果。
```

### AI 生成结果拒收条件

- 只有单文件和一次 LLM 调用，没有能力路由、失败策略或测试；
- 把 Token、知识正文、MCP 完整配置写进代码；
- 使用不存在的 SDK/API，却声称可以直接运行；
- 用模块全局变量保存历史；
- 无限循环/重试，或没有超时/步骤边界；
- 用假数据掩盖知识无结果、工具失败；
- 只有片段，没有可打包目录、README、依赖和上传配置；
- 测试只验证“返回不为空”，未验证边界和异常路径。

## 13. 上传前自检

### 代码与协议

- [ ] 入口按 `module.path:callable` 可导入
- [ ] 接受 `input`、`messages` 和实际使用的注入参数
- [ ] LIVE 支持异步流式，输出契约明确
- [ ] 无模块级可变会话状态
- [ ] 依赖可重复安装，包内无敏感/无关文件

### 配置与能力

- [ ] 已声明 memory scope 和 secret 名称，无明文值
- [ ] Skill、MCP、知识库由平台创建并绑定，无内联内容
- [ ] Skill 有 Schema、工具、步数和超时边界
- [ ] MCP 使用 secret_ref，工具 Schema、重试和副作用策略明确
- [ ] 知识库有来源、索引、切分、召回、引用和租户边界

### 运行与发布

- [ ] 正常、多轮、无知识、工具失败、超时、取消、并发隔离均有测试
- [ ] 循环、重试、时长、成本和高风险动作受控
- [ ] Trace 可区分 Agent、模型、检索、工具和错误
- [ ] conformance 与 TEST 数据集门禁通过
- [ ] LIVESH/LIVE 有监控和回退方案

## 14. 常见问题

**是否必须同时使用 Skill、MCP 和知识库？** 不必须。完整是指职责所需能力都有明确实现和边界。依赖企业事实的 Agent 不能只靠模型常识。

**旧入口叫 `query` 怎么办？** 增加薄适配层：

```python
from .legacy import support_agent

async def run(input, messages=None, **kwargs):  # noqa: A002
    return await support_agent(query=input, history=messages or [])
```

**能从环境变量读取密钥吗？** 本地调试可以；平台托管必须使用 secrets 注入，以便按通道绑定、轮换和回退。

**用了知识库，还要把文档打进代码包吗？** 不要。会更新、需检索、需审计的内容进入知识库；代码只保留与版本强绑定的少量静态规则。

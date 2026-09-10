# 能力资产配置

Skill、MCP Server 和知识库是独立资产。它们独立配置、版本化和评测，再绑定给 Agent。

## 1. 统一装配流程

1. 创建能力资产；
2. 完成配置与校验；
3. 绑定到 Agent；
4. Run 开始时解析对应通道版本；
5. 保存不可漂移的能力版本快照；
6. 通过 `capabilities` 注入入口，并写入 Trace 归因。

## 2. Skill

Skill 描述可复用的任务方法和边界，不是独立 Agent。

### 必要配置

- `instructions`：可执行的完整指令；
- `input_schema` / `output_schema`：结构化契约；
- `allowed_tools`：工具白名单；
- `max_steps`：最大执行步数；
- `timeout_ms`：超时边界。

### 使用要求

Agent 应验证 Skill 是否匹配当前任务，并严格遵守工具、步骤和超时限制。

## 3. MCP Server

MCP 为 Agent 提供工具服务。

### 必要配置

- `endpoint`；
- `transport`：`stdio`、`sse` 或 `streamable-http`；
- 使用 `secret_ref` 的认证配置；
- 工具名称、说明和输入 Schema。

### 失败与安全

调用前校验参数，调用后校验业务结果。只有幂等操作可以有限重试；有副作用或高风险的动作需要确认。工具名必须与平台注册表一致。

## 4. 知识库

知识库至少配置数据源、索引、embedding、切分、召回、`top_k`、可选 reranker 和租户隔离。

### 回答原则

- 区分无召回和证据不足；
- 按业务要求给出来源；
- 不用模型常识补写不存在的企业政策；
- 租户绑定知识不得跨租户检索。

## 5. 禁止内联

Agent 版本中只能保存资产引用，不得保存 Skill 全文、MCP Token/完整连接配置或知识正文。

```json
{
  "skills": [{"asset_id": "skill_xxx"}],
  "mcp_servers": [{"asset_id": "mcp_xxx"}],
  "knowledge_bases": [{"asset_id": "kb_xxx"}]
}
```

优先使用平台绑定功能，上述 JSON 仅说明引用形态。

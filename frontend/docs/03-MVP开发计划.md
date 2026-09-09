# MVP 开发计划

## 1. MVP 目标

用一个本地可运行 Demo 验证最小闭环：

```text
注册 Agent
  → 选择评测能力和数据集
  → 创建评测运行
  → Agent 执行任务
  → 记录 Trace
  → 评分
  → 在控制台查看结果和失败步骤
```

MVP 不追求一开始就支持所有真实 Benchmark，而是先把协议、运行、结果、管理四条链路做通。

## 2. MVP 页面

### 2.1 Overview

展示：

- 最近运行。
- 总任务数、成功率、失败率。
- 平均延迟和成本。
- 维度雷达或能力分布。
- 最近失败的任务和高频错误。

### 2.2 Runs

功能：

- 创建 Run。
- 选择 Agent 版本。
- 选择评测模板。
- 选择数据集子集。
- 设置并发、最大步数和成本上限。
- 启动、停止、暂停标记。
- 查看 Run 进度。

### 2.3 Run Detail

功能：

- 任务列表和状态。
- 单个 Trial 的 Trace 时间线。
- Model、Tool、Observation、Scorer 节点。
- Token、成本、耗时。
- 原始结果和平台维度结果。
- 错误定位和重跑入口。

### 2.4 Capabilities / Dimensions

功能：

- 创建能力。
- 在能力下创建维度。
- 配置评分器、权重和阈值。
- 启用/停用维度。
- 查看维度绑定的数据集。

### 2.5 Datasets

功能：

- 创建数据集。
- 导入 JSONL。
- 查看样本。
- 绑定 Benchmark Adapter。
- 版本化数据集。
- 标记 smoke / regression / release split。

### 2.6 Agents

功能：

- 注册 Agent。
- 添加 HTTP Endpoint。
- 上传 Agent 代码包。
- 查看 Agent 版本和健康状态。
- 启动、暂停和终止运行实例。
- 查看 Agent 的最近运行和错误。

## 3. MVP 数据模型

最小表：

```text
agents
agent_versions
agent_instances
capabilities
dimensions
datasets
dataset_items
benchmark_adapters
evaluation_templates
runs
trials
sessions
trace_events
scores
artifacts
audit_logs
```

第一版可以使用 SQLite，字段设计按 PostgreSQL 兼容方式实现，后续迁移不改业务模型。

## 4. MVP API

### Agent

```text
GET    /api/agents
POST   /api/agents
GET    /api/agents/{id}
POST   /api/agents/{id}/versions
POST   /api/agents/{id}/pause
POST   /api/agents/{id}/resume
POST   /api/agents/{id}/health-check
POST   /api/agents/{id}/package
```

### Capability / Dimension

```text
GET    /api/capabilities
POST   /api/capabilities
POST   /api/capabilities/{id}/dimensions
PATCH  /api/dimensions/{id}
```

### Dataset

```text
GET    /api/datasets
POST   /api/datasets
POST   /api/datasets/{id}/items/import
GET    /api/datasets/{id}/items
```

### Evaluation / Run

```text
GET    /api/evaluation-templates
POST   /api/evaluation-templates
POST   /api/runs
GET    /api/runs
GET    /api/runs/{id}
POST   /api/runs/{id}/start
POST   /api/runs/{id}/pause
POST   /api/runs/{id}/stop
GET    /api/runs/{id}/traces
GET    /api/runs/{id}/scores
```

## 5. MVP 的 Demo 执行场景

第一版建议使用一个不依赖外部服务的“订单客服工具调用” Benchmark：

```text
Agent 任务：根据客服政策处理订单退款请求
工具：查询订单、查询退款政策、执行退款、发送消息
确定性评分：是否调用正确工具、参数是否正确、最终订单状态是否正确
过程评分：无效调用、违规调用、调用次数、耗时
```

这样能真实演示：

- Task / Context / Actions。
- Agent Tool Call。
- 工具返回 Observation。
- 多步交互。
- 规则评分。
- Trace 回放。
- 维度得分。

然后再增加一个 Docker 代码任务，验证文件环境、命令执行和测试脚本。

## 6. Demo 技术结构

```text
frontend/
  React + TypeScript + Vite

backend/
  FastAPI
  api/
  domain/
  adapters/
  runner/
  scorer/
  repositories/

data/
  seed capabilities/dimensions/datasets

docs/
  protocol and production design
```

运行方式：

- 前端开发服务器。
- FastAPI API 服务。
- 一个本地后台 Runner。
- 一个内置 Mock Agent。
- 一个内置 Mock Benchmark Adapter。

代码包上传在 MVP 中先完成“上传、校验、登记、模拟执行状态”闭环；真正的任意代码执行放入生产化 Worker 后再开放。

## 7. MVP 验收标准

- 能在页面创建 Agent。
- 能创建能力、维度和数据集。
- 能创建评测模板并选择数据集。
- 能启动一次评测 Run。
- 能实时看到 Run 状态变化。
- 至少有 3 个任务，每个任务有 3～8 个交互步骤。
- 能查看完整 Trace。
- 能看到确定性评分和维度汇总。
- 能停止 Run，并保留已完成任务结果。
- 能查看 Agent 版本和运行配置。
- 所有关键操作生成 audit log。
- 页面刷新后数据仍能恢复。

## 8. 开发顺序

### Phase 1：领域模型和静态控制台

- 建表或定义内存模型。
- 完成页面导航和基础 CRUD。
- 准备种子数据。

### Phase 2：统一协议和内置评测

- 实现 TaskSpec、Action、Observation、Score、TraceEvent。
- 实现 Mock Agent Adapter。
- 实现 Mock Benchmark Adapter。
- 实现 Runner 主循环。

### Phase 3：运行观测和结果

- 实时事件推送。
- Trace 时间线。
- 任务级和维度级结果。
- 失败原因。

### Phase 4：外部 Agent 接入

- HTTP Agent Adapter。
- Agent 健康检查。
- Session 级认证。
- 超时、重试和取消。

### Phase 5：Docker Agent

- Dockerfile 构建。
- 镜像 Digest。
- 独立容器运行。
- 任务工作区和结果挂载。

## 9. 不应在 MVP 中过早做的事情

- 不要一开始支持浏览器、桌面、终端、MCP、A2A、代码包全部接入。
- 不要一开始用 Kubernetes 解决本地 Demo 的后台任务。
- 不要把所有评分都设计成 LLM Judge。
- 不要只存最终 answer，不存 Action/Observation。
- 不要让前端直接持有模型 API Key。
- 不要让上传的 Agent 包在 Web API 进程内执行。

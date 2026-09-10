# 快速开始

这篇文档用于在最短时间内创建一个可以被平台托管和评测的 Agent。

## 1. 定义职责

先写清楚 Agent 服务谁、完成什么任务、何时调用外部能力、何时拒绝或转人工。不要从代码开始，也不要让模型自行猜测业务规则。

## 2. 创建最小工程

```text
my_agent/
├── agent.py
├── policy.py
├── pyproject.toml
├── README.md
└── tests/
```

### 标准入口

```python
async def run(
    input,
    messages=None,
    secrets=None,
    memory=None,
    capabilities=None,
):
    ...
```

平台托管入口必须接受 `input` 和 `messages`，推荐同时声明所有可选注入参数。

## 3. 准备平台配置

### 记忆

优先选择 `thread` 作用域。明确无状态时选择 `stateless`，不要遗漏配置。

### 密钥

版本只声明密钥名称。真实值在平台密钥管理中保存，并按 TEST 或 LIVE 通道绑定。

### 能力资产

先在平台创建 Skill、MCP Server、知识库，再绑定 Agent。代码通过 `capabilities` 使用解析后的版本快照。

## 4. 本地验证

测试至少覆盖正常输入、多轮对话、外部能力失败、超时和并发隔离。入口必须能够从包根目录导入。

## 5. 上传与发布

上传 ZIP/TAR.GZ 或连接 GitHub，运行 conformance 验收，再依次完成 TEST、LIVESH 和 LIVE。

```text
GET /api/agents/{id}/versions/{vid}/conformance?require_streaming=true
```

## 下一步

- 阅读《完整开发规范》了解全部强制约束；
- 阅读《能力资产配置》配置 Skill、MCP 与知识库；
- 阅读《运行与发布生命周期》设计异常、观测和回退；
- 阅读《让 AI 生成 Agent》获得可直接复制的任务模板。

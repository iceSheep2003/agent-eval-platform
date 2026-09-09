# agent-eval-sdk

一个 Python-first 的 Agent 观测与离线评测 SDK。它提供：

- `@observe`、`span()`、`emit()`：低侵入记录 Agent、LLM、工具和检索器执行事实；
- `evaluate()`：在本地或 CI 中运行同步/异步 Agent；
- `rescore()`：读取已有 JSONL 事实日志并更换 Metric 重评分；
- Memory、Console、JSONL 和可选 HTTP Sink；
- 一组无第三方依赖的确定性 Metric；
- `agent-eval inspect` 等 CLI 命令。

## 最小示例

```python
from agent_eval import EvaluationCase, Score, evaluate, observe


@observe(kind="agent", name="support_agent")
def support_agent(question: str) -> str:
    return "该订单可以退款。"


class ContainsRefundDecision:
    name = "contains_refund_decision"
    version = "1.0.0"
    scope = "case"

    async def score(self, target):
        passed = "可以退款" in str(target.output)
        return Score(
            metric=self.name,
            metric_version=self.version,
            value=1.0 if passed else 0.0,
            status="pass" if passed else "fail",
            reason=None if passed else "没有包含退款结论",
        )


async def main():
    result = await evaluate(
        agent=support_agent,
        cases=[EvaluationCase(id="refund-001", input="订单 A001 能退款吗？")],
        metrics=[ContainsRefundDecision()],
        output_dir=".agent-eval/runs/refund-smoke",
    )
    print(result.summary.pass_rate)
```

详细设计以目录中的《Agent评测SDK开发设计文档.md》为准。

## Eval Loom 平台

平台后端已经从 SDK 中拆出，位于 `backend/`。它采用 FastAPI 控制面、SQLite 元数据/命令 Outbox、独立 Worker 和可替换 Runtime Adapter，完成以下最小闭环：

```text
注册 Agent → 上传代码包并冻结 AgentVersion → 加密保存 API Key
→ 创建/停止/删除 Agent Instance → 创建 Run → Trial → Trace → Score
```

部署出的 Agent 通过平台网关统一提供服务。控制台的“实例与密钥”页面可以启动实例、在线调试、生成或撤销调用 Token，并查看最近业务调用。公开调用方式：

```bash
curl -X POST 'http://127.0.0.1:8787/v1/agents/<agent-id>/invoke' \
  -H 'Authorization: Bearer <deployment-token>' \
  -H 'Content-Type: application/json' \
  -d '{"input":"查询订单 A001"}'
```

业务调用和评测运行都会路由到同一个 `running` AgentInstance。每次调用记录版本、实例、输入输出、调用来源和延迟；评测链路在此基础上继续生成 Trial、Trace 和 Score。HTTP Agent 由本地 Runtime 代理到登记的 Endpoint，Kubernetes Runtime 则调用已部署 Service。

已有 Agent 不再登记为 HTTP 服务。控制台选择“添加 Agent → 使用 SDK 接入”后，平台会生成
独立的 `evk_` 接入密钥和 `/v1/traces` 上报地址：

```python
from agent_eval import PlatformSink, configure, observe as platform_observe
from deepeval.tracing import observe as deepeval_observe

configure(sinks=[PlatformSink(
    "http://127.0.0.1:8787",
    "evk_由控制台生成",
)])

@platform_observe(kind="agent", name="support_agent")
@deepeval_observe(type="agent")
def support_agent(task):
    ...
```

DeepEval 负责 Agent、LLM、Tool、Retriever 等评测埋点；`PlatformSink` 将统一事件以
NDJSON 批量写入控制面。SDK 密钥只允许写 Trace，不能调用 Agent。数据库只保存其哈希
与末四位，明文只在创建时显示一次。

```bash
python3 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787 --reload
```

开发环境会在 `.data/eval-loom/.master-key` 生成本地主密钥；生产模式强制从外部注入 `EVAL_LOOM_MASTER_KEY`。API Key 以 Fernet 密文写入 SQLite，主密钥不进入数据库。

默认 Runtime 是不加载上传代码的确定性本地沙箱替代组件。`RUNTIME_BACKEND=kubernetes` 会切换到 Kubernetes Adapter：常驻 Agent 使用 Deployment，评测任务预留 Job 边界。详细组件、状态机与 ER 图见 `docs/backend-architecture.md`。

DeepEval 埋点的真实被测 Agent 位于 `examples/support_agent_deepeval.py`。它无需平台持有模型 API Key即可运行确定性业务逻辑；接入真实模型时，平台凭证由 Worker 在执行面注入。安装 `.[deepeval]` 后运行：

```bash
deepeval test run examples/test_support_agent_deepeval.py
```

## 前后端统一工作区

前端原型已合并到 `frontend/`，Python backend 保留在根目录：

```text
agent评测开发/
├── backend/              # FastAPI 控制面、Worker、Repository、Runtime Adapter
├── src/agent_eval/       # Agent 侧观测与评测 SDK
├── tests/                # SDK 兼容测试
├── examples/             # DeepEval 埋点 Agent
├── docs/                 # 平台架构
├── deploy/local-k8s/     # Kubernetes 本地运行说明
└── frontend/             # React/Vite 控制台
```

启动前端：

```bash
cd frontend
npm install
npm run dev:api  # 单独终端
npm run dev
```

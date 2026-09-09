# Agent 导入模板

这个目录可以直接作为新 Agent 的骨架。修改 `agent.yaml` 中的名称，并把
`run.py::agent_step` 替换为真实 Agent 调用即可。

打包前必须保留：

- `agent.yaml`：平台运行与协议清单。
- `run.py`：启动入口，提供 `/health` 和 `/invoke`。
- `requirements.lock`：可复现依赖版本。
- `agentic_bench_adapter.py`：将平台任务转换成 Agent 输入和 Action/Observation。

本地启动：

```bash
python -m pip install -r requirements.lock
python run.py
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/invoke \
  -H 'content-type: application/json' \
  -d '{"task_id":"smoke-001","task":{"instruction":"检查订单"}}'
```

`CONFIDENT_API_KEY` 仅在需要把 DeepEval Trace 发送到 Confident AI 时通过平台密钥库注入；
模板本身不需要也不允许写死任何 API Key。


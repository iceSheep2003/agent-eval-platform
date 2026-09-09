# DeepEval Agent smoke test

`support_agent_deepeval.py` 是平台接入前的最小被测 Agent。它有一条清晰的调用链：

```text
customer_support_agent (agent)
├── lookup_order (tool)
└── policy_model (llm)
```

顶层 Agent 使用 `update_current_trace(input=..., output=...)` 写入最终测试用例字段；工具和策略判断使用 `@observe(type=...)` 产生嵌套 Span。这样端到端任务完成度和单组件工具/模型指标都可以基于同一条 Trace 评测。

安装并运行：

```bash
python -m pip install -e '.[deepeval]'
deepeval test run examples/test_support_agent_deepeval.py
```

这个例子没有调用真实模型或产生外部副作用，适合作为平台 Run/Trace/Score 闭环的固定 smoke test。接入真实 Agent 时，只替换 `policy_model` 的实现，保留 Agent 和工具的埋点边界。

# Eval Loom Backend

独立的 Agent 评测平台控制面。`src/agent_eval` 是被测 Agent 使用的埋点 SDK；本目录负责平台 API、元数据、调度和执行面适配，两者不再混放。

## 本地启动

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8787 --reload
```

前端仍运行在 `4173`，Vite 已把 `/api` 代理到本服务。演示账号沿用 `admin / admin123` 与 `demo / demo123`。

开发环境首次启动会在数据目录生成权限为 `0600` 的本地主密钥；生产环境设置 `EVAL_LOOM_ENV=production` 后强制要求从环境或 Secret Manager 注入 `EVAL_LOOM_MASTER_KEY`。密钥不会写入业务数据库。

默认 `RUNTIME_BACKEND=local`，执行面使用确定性沙箱模拟器完成上传、实例和评测闭环。设置 `RUNTIME_BACKEND=kubernetes` 后，Worker 会改用 Kubernetes 适配器；API 请求线程永远不加载或执行上传的代码。

## 测试

```bash
pytest backend/tests -q
```

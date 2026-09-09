# Local Kubernetes deployment

最小集群建议预留约 6–8 GiB 磁盘：kind 节点镜像与平台镜像约占主要空间，SQLite PVC 默认只申请 2 GiB。开发机内存建议至少 4 GiB，其中平台 Pod 上限 1 GiB。

一键启动（需要 Docker Desktop、kind、kubectl）：

```bash
./deploy/local-k8s/bootstrap.sh
```

脚本会创建 `eval-loom` kind 集群、构建包含 React 前端和 FastAPI 后端的单一镜像、创建 2 GiB PVC，并在 [http://127.0.0.1:8787](http://127.0.0.1:8787) 暴露控制台。重复执行不会替换已有主密钥，因此数据库中的 API Key 始终可解密。当前平台 Pod 使用轻量 `local` Runtime 完成演示闭环，不会在控制面进程里执行用户上传代码。

查看状态：

```bash
kubectl -n eval-loom get pods,svc,pvc
kubectl -n eval-loom logs deployment/eval-loom -f
```

## 使用 Kubernetes 作为 Agent 执行面

The platform can run uploaded Agent Instances as Kubernetes Deployments. The
current local adapter expects a reachable Docker daemon and kubeconfig:

```bash
# Choose one local cluster, not both.
kind create cluster --name agent-eval
kubectl config use-context kind-agent-eval

export RUNTIME_BACKEND=kubernetes
export EVAL_LOOM_MASTER_KEY="$(python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
```

For Docker Desktop Kubernetes, enable Kubernetes in Docker Desktop and use the
`docker-desktop` context instead of creating a kind cluster.

当前 Kubernetes Adapter 只接受已经固化的 `image_ref`。常驻实例创建 Deployment；评测 Trial 创建 Job，并通过环境变量传入任务，读取容器最后一行 JSON 作为结果。上传代码包首先进入制品表，后续由独立 Build Worker 生成镜像；API 进程不会执行 `docker build`。本地闭环默认使用 `RUNTIME_BACKEND=local`，不需要 Docker daemon，切换到 Kubernetes 前需先提供镜像构建流水线。

Job 镜像必须在 stdout 最后一行输出：

```json
{"output":{"status":"refundable"},"passed":true,"score":1.0,"events":[]}
```

## Package contract

上传 zip 或 tar.gz，并在版本的 `runtime_manifest` 中声明入口：

```json
{
  "name": "support-agent",
  "version": "1.0.0",
  "entrypoint": "agent:run",
  "description": "DeepEval-instrumented support agent"
}
```

`agent.py` must expose `run(input) -> output`. It may be sync or async and may
use `deepeval.tracing.observe`. Put runtime dependencies in `requirements.txt`.
API keys are injected as Kubernetes Secrets; they are not written into the
uploaded package.

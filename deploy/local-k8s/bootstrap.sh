#!/usr/bin/env bash
set -euo pipefail

for tool in docker kind kubectl python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing required tool: $tool" >&2; exit 1; }
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLUSTER_NAME="${EVAL_LOOM_CLUSTER_NAME:-eval-loom}"

if ! kind get clusters | grep -qx "$CLUSTER_NAME"; then
  kind create cluster --name "$CLUSTER_NAME" --config "$ROOT_DIR/deploy/local-k8s/kind-config.yaml"
fi

docker build -f "$ROOT_DIR/deploy/local-k8s/platform.Dockerfile" -t eval-loom:local "$ROOT_DIR"
kind load docker-image eval-loom:local --name "$CLUSTER_NAME"
kubectl create namespace eval-loom --dry-run=client -o yaml | kubectl apply -f -

if ! kubectl -n eval-loom get secret eval-loom-secrets >/dev/null 2>&1; then
  MASTER_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  kubectl -n eval-loom create secret generic eval-loom-secrets --from-literal=master-key="$MASTER_KEY"
fi
kubectl apply -f "$ROOT_DIR/deploy/local-k8s/platform.yaml"
kubectl -n eval-loom rollout status deployment/eval-loom --timeout=180s

echo "Eval Loom is available at http://127.0.0.1:8787"

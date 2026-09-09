from __future__ import annotations

import json
import subprocess
from typing import Any
from urllib.request import Request, urlopen


class LocalSandboxRuntime:
    """Deterministic execution-plane substitute used by tests and small demos.

    It never imports uploaded code. Its purpose is to exercise the complete
    control-plane contract on machines without a container daemon.
    """

    name = "local"

    def start_instance(self, instance: dict[str, Any], version: dict[str, Any], secrets: dict[str, str]) -> dict[str, str]:
        return {"runtime_ref": f"local://{instance['id']}", "endpoint": f"/v1/agents/{instance['agent_id']}/invoke"}

    def stop_instance(self, instance: dict[str, Any]) -> None:
        return None

    def delete_instance(self, instance: dict[str, Any]) -> None:
        return None

    def invoke(self, instance: dict[str, Any], version: dict[str, Any], payload: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
        manifest = json.loads(version.get("runtime_manifest") or "{}")
        if version.get("source_type") == "http" and version.get("source_uri") and manifest.get("handler") != "demo_support":
            body = json.dumps(payload, ensure_ascii=False).encode()
            headers = {"content-type": "application/json"}
            if token := secrets.get("agent"):
                headers["authorization"] = f"Bearer {token}"
            request = Request(str(version["source_uri"]), data=body, headers=headers, method="POST")
            with urlopen(request, timeout=int(manifest.get("timeout_seconds", 30))) as response:
                response_payload = json.loads(response.read().decode())
            return {"output": response_payload.get("output", response_payload), "events": response_payload.get("events", [])}
        input_value = payload.get("input") or payload.get("instruction") or payload.get("query") or payload
        if manifest.get("handler") == "demo_support":
            text = str(input_value)
            if "A001" in text and ("查询" in text or "退款" in text):
                output: Any = {"status": "refundable"}
            elif "取消" in text and "A001" in text:
                output = {"cancelled": True}
            elif "政策" in text:
                output = {"policy_followed": True}
            else:
                output = {"message": f"已收到：{text}"}
        else:
            output = manifest.get("mock_output", {"message": f"已收到：{input_value}"})
        return {"output": output, "events": [{"event_type": "agent", "actor": "agent", "name": "invoke", "input": payload, "output": output, "status": "success"}]}

    def execute_trial(self, run: dict[str, Any], version: dict[str, Any], item: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
        payload = json.loads(item["payload"])
        expected = json.loads(item["expected"]) if item.get("expected") else {}
        manifest = json.loads(version.get("runtime_manifest") or "{}")
        actual = self.invoke({"id": f"trial-{run['id']}", "agent_id": version.get("agent_id", "")}, version, payload, secrets)["output"] if manifest.get("handler") else payload.get("demo_output", expected)
        passed = actual == expected
        return {
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "input": payload,
            "output": actual,
            "events": [
                {"event_type": "agent", "actor": "agent", "name": "run_task", "input": payload, "output": actual, "status": "success"},
                {"event_type": "score", "actor": "scorer", "name": "deterministic_match", "input": actual, "output": {"expected": expected, "passed": passed}, "status": "success"},
            ],
        }


class KubernetesRuntime:
    """Execution adapter. Deployments host Agent instances; Jobs execute trials."""

    name = "kubernetes"

    def __init__(self, namespace: str):
        self.namespace = namespace

    def _apply(self, manifest: dict[str, Any]) -> None:
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(manifest), text=True, capture_output=True, check=True,
        )

    def _apply_secret(self, name: str, secrets: dict[str, str]) -> str | None:
        if not secrets:
            return None
        secret_name = f"{name}-credentials"[:63]
        self._apply({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": secret_name, "namespace": self.namespace, "labels": {"app.kubernetes.io/managed-by": "eval-loom"}},
            "type": "Opaque",
            "stringData": {f"{provider.upper()}_API_KEY": value for provider, value in secrets.items()},
        })
        return secret_name

    def start_instance(self, instance: dict[str, Any], version: dict[str, Any], secrets: dict[str, str]) -> dict[str, str]:
        image = version.get("image_ref")
        if not image:
            raise RuntimeError("Kubernetes runtime requires an immutable image_ref; uploaded packages must finish the build pipeline first")
        name = instance["id"].replace("_", "-")[:63]
        labels = {"app.kubernetes.io/managed-by": "eval-loom", "eval-loom/instance": name}
        secret_name = self._apply_secret(name, secrets)
        manifest_config = json.loads(version.get("runtime_manifest") or "{}")
        port = int(manifest_config.get("port", 8080))
        container = {
            "name": "agent",
            "image": image,
            "ports": [{"name": "http", "containerPort": port}],
            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True},
            "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "1", "memory": "1Gi"},
            },
        }
        if secret_name:
            container["envFrom"] = [{"secretRef": {"name": secret_name}}]
        pod_spec = {
            "automountServiceAccountToken": False,
            "securityContext": {"runAsNonRoot": True},
            "containers": [container],
        }
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": self.namespace, "labels": labels},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {"metadata": {"labels": labels}, "spec": pod_spec},
            },
        }
        self._apply(manifest)
        self._apply({
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": self.namespace, "labels": labels},
            "spec": {"selector": labels, "ports": [{"name": "http", "port": port, "targetPort": "http"}]},
        })
        return {"runtime_ref": f"deployment/{name}", "endpoint": f"http://{name}.{self.namespace}.svc.cluster.local:{port}"}

    def stop_instance(self, instance: dict[str, Any]) -> None:
        name = str(instance["runtime_ref"]).split("/", 1)[-1]
        subprocess.run(["kubectl", "-n", self.namespace, "scale", "deployment", name, "--replicas=0"], check=True, capture_output=True, text=True)

    def delete_instance(self, instance: dict[str, Any]) -> None:
        name = str(instance["runtime_ref"]).split("/", 1)[-1]
        subprocess.run(["kubectl", "-n", self.namespace, "delete", f"deployment/{name}", f"service/{name}", f"secret/{name}-credentials", "--ignore-not-found=true"], check=True, capture_output=True, text=True)

    def invoke(self, instance: dict[str, Any], version: dict[str, Any], payload: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
        endpoint = str(instance.get("endpoint") or "").rstrip("/")
        if not endpoint:
            raise RuntimeError("Agent instance has no endpoint")
        request = Request(f"{endpoint}/invoke", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"content-type": "application/json"}, method="POST")
        manifest = json.loads(version.get("runtime_manifest") or "{}")
        with urlopen(request, timeout=int(manifest.get("timeout_seconds", 30))) as response:
            response_payload = json.loads(response.read().decode())
        return {"output": response_payload.get("output", response_payload), "events": response_payload.get("events", [])}

    def execute_trial(self, run: dict[str, Any], version: dict[str, Any], item: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
        image = version.get("image_ref")
        if not image:
            raise RuntimeError("Kubernetes trial Job requires a built Agent image_ref")
        name = f"trial-{run['id'][-8:]}-{item['id'][-8:]}".replace("_", "-").lower()[:63]
        labels = {"app.kubernetes.io/managed-by": "eval-loom", "eval-loom/run": run["id"][-20:]}
        secret_name = self._apply_secret(name, secrets)
        manifest_config = json.loads(version.get("runtime_manifest") or "{}")
        container: dict[str, Any] = {
            "name": "agent",
            "image": image,
            "env": [
                {"name": "EVAL_LOOM_RUN_ID", "value": run["id"]},
                {"name": "EVAL_LOOM_TASK_JSON", "value": item["payload"]},
                {"name": "EVAL_LOOM_EXPECTED_JSON", "value": item.get("expected") or "null"},
            ],
            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True},
            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}},
        }
        if manifest_config.get("command"):
            container["command"] = manifest_config["command"]
        if secret_name:
            container["envFrom"] = [{"secretRef": {"name": secret_name}}]
        self._apply({
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "namespace": self.namespace, "labels": labels},
            "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 300, "template": {"metadata": {"labels": labels}, "spec": {
                "restartPolicy": "Never", "automountServiceAccountToken": False,
                "securityContext": {"runAsNonRoot": True}, "containers": [container],
            }}},
        })
        timeout = int(manifest_config.get("timeout_seconds", 300))
        subprocess.run(["kubectl", "-n", self.namespace, "wait", f"job/{name}", "--for=condition=complete", f"--timeout={timeout}s"], check=True, capture_output=True, text=True)
        logs = subprocess.run(["kubectl", "-n", self.namespace, "logs", f"job/{name}"], check=True, capture_output=True, text=True).stdout
        try:
            result = json.loads(next(line for line in reversed(logs.splitlines()) if line.strip()))
        except (StopIteration, json.JSONDecodeError) as exc:
            raise RuntimeError("Agent Job must print one JSON result object as its final stdout line") from exc
        expected = json.loads(item["expected"]) if item.get("expected") else None
        output = result.get("output")
        passed = bool(result.get("passed", output == expected))
        return {
            "passed": passed,
            "score": float(result.get("score", 1.0 if passed else 0.0)),
            "events": result.get("events") or [{"event_type": "agent", "actor": "agent", "name": "kubernetes_job", "input": json.loads(item["payload"]), "output": output, "status": "success"}],
        }

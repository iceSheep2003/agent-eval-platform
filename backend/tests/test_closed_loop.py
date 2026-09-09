from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def test_upload_instance_and_evaluation_closed_loop(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "platform.db",
        package_dir=tmp_path / "packages",
        master_key=Fernet.generate_key().decode(),
        worker_poll_seconds=0.01,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"identifier": "admin", "password": "admin123"})
        assert login.status_code == 200

        agent = client.post("/api/agents", json={"name": "package-agent", "connect_type": "package", "environment": "sandbox"}).json()
        package_bytes = io.BytesIO()
        with zipfile.ZipFile(package_bytes, "w") as archive:
            archive.writestr("agent.yaml", "entrypoint: run.py\n")
            archive.writestr("run.py", "print('demo')\n")
            archive.writestr("requirements.lock", "deepeval==3.7.2\n")
        package_bytes.seek(0)
        version_response = client.post(
            f"/api/agents/{agent['id']}/versions",
            data={"version": "1.0.0", "source_type": "package", "runtime_manifest": '{"entrypoint":"run.py","handler":"demo_support"}'},
            files={"package": ("agent.zip", package_bytes, "application/zip")},
        )
        assert version_response.status_code == 201, version_response.text
        version = version_response.json()

        credential = client.post("/api/credentials", json={"agent_id": agent["id"], "provider": "openai", "name": "primary", "value": "sk-local-test-1234"})
        assert credential.status_code == 201
        assert "value" not in credential.json()
        row = app.state.container.repository.one("SELECT * FROM credentials WHERE id=?", (credential.json()["id"],))
        assert row and "sk-local-test-1234" not in row["ciphertext"]
        listed_credentials = client.get("/api/credentials", params={"agent_id": agent["id"]}).json()["items"]
        assert listed_credentials[0]["last_four"] == "1234"
        assert "ciphertext" not in listed_credentials[0]
        assert client.get(f"/api/agents/{agent['id']}").json()["credentials"][0]["last_four"] == "1234"

        deployment = client.post(f"/api/agents/{agent['id']}/deploy", json={"name": "one-click"})
        assert deployment.status_code == 202, deployment.text
        assert deployment.json()["access"]["token"].startswith("evl_")
        instance = deployment.json()["instance"]
        deadline = time.time() + 2
        while time.time() < deadline:
            current = app.state.container.repository.one("SELECT * FROM agent_instances WHERE id=?", (instance["id"],))
            if current and current["status"] == "running":
                break
            time.sleep(0.01)
        assert current and current["status"] == "running"

        console_invoke = client.post(f"/api/agents/{agent['id']}/invoke", json={"input": "hello"})
        assert console_invoke.status_code == 200, console_invoke.text
        assert console_invoke.json()["instance_id"] == instance["id"]
        access_token = client.post(f"/api/agents/{agent['id']}/access-tokens", json={"name": "integration"})
        assert access_token.status_code == 201
        plain_token = access_token.json()["token"]
        listed_tokens = client.get(f"/api/agents/{agent['id']}/access-tokens").json()["items"]
        assert listed_tokens[0]["last_four"] == plain_token[-4:]
        assert "token_hash" not in listed_tokens[0]
        public_invoke = client.post(f"/v1/agents/{agent['id']}/invoke", headers={"authorization": f"Bearer {plain_token}"}, json={"input": "public hello"})
        assert public_invoke.status_code == 200, public_invoke.text
        assert len(client.get(f"/api/agents/{agent['id']}/invocations").json()["items"]) == 2

        run_response = client.post("/api/runs", json={"name": "package smoke", "agent_version_id": version["id"], "template_id": "tpl_smoke"})
        assert run_response.status_code == 202, run_response.text
        run_id = run_response.json()["id"]
        deadline = time.time() + 2
        while time.time() < deadline:
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] == "completed":
                break
            time.sleep(0.01)
        assert run["status"] == "completed"
        assert run["progress"] == 100
        assert run["passed"] == 3
        assert len(run["trials"]) == 3
        assert len(run["traces"]) == 6
        assert len(run["scores"]) == 3

        assert client.delete(f"/api/access-tokens/{access_token.json()['id']}").status_code == 204
        assert client.post(f"/v1/agents/{agent['id']}/invoke", headers={"authorization": f"Bearer {plain_token}"}, json={"input": "blocked"}).status_code == 401

        assert client.delete(f"/api/credentials/{credential.json()['id']}").status_code == 204
        assert client.get("/api/credentials", params={"agent_id": agent["id"]}).json()["items"] == []


def test_instance_can_stop_and_delete(tmp_path: Path) -> None:
    settings = Settings(tmp_path, tmp_path / "db.sqlite", tmp_path / "packages", Fernet.generate_key().decode(), worker_poll_seconds=0.01)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"identifier": "admin", "password": "admin123"})
        agent = client.post("/api/agents", json={"name": "http-agent", "connect_type": "http"}).json()
        version = client.post(f"/api/agents/{agent['id']}/versions", data={"version": "1.0.0", "source_type": "http", "source_uri": "http://agent.local", "runtime_manifest": "{}"}).json()
        instance = client.post(f"/api/agents/{agent['id']}/instances", json={"agent_version_id": version["id"]}).json()
        worker = app.state.container.worker
        assert worker.run_once()
        assert client.post(f"/api/instances/{instance['id']}/stop").status_code == 202
        assert worker.run_once()
        assert client.post(f"/api/instances/{instance['id']}/delete").status_code == 202
        assert worker.run_once()
        row = app.state.container.repository.one("SELECT status FROM agent_instances WHERE id=?", (instance["id"],))
        assert row and row["status"] == "deleted"
        assert client.delete(f"/api/agents/{agent['id']}").status_code == 204
        assert all(item["id"] != agent["id"] for item in client.get("/api/agents").json()["items"])


def test_agent_import_contract_for_git_and_packages(tmp_path: Path) -> None:
    settings = Settings(tmp_path, tmp_path / "db.sqlite", tmp_path / "packages", Fernet.generate_key().decode(), worker_poll_seconds=0.01)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"identifier": "admin", "password": "admin123"})

        git_agent = client.post("/api/agents", json={"name": "git-agent", "connect_type": "git"}).json()
        git_version = client.post(
            f"/api/agents/{git_agent['id']}/versions",
            data={
                "version": "1.0.0",
                "source_type": "git",
                "source_uri": "https://gitee.com/acme/order-agent.git",
                "runtime_manifest": '{"source_ref":"main","entrypoint":"run.py"}',
            },
        )
        assert git_version.status_code == 201, git_version.text
        assert git_version.json()["source_type"] == "git"

        package_agent = client.post("/api/agents", json={"name": "invalid-package", "connect_type": "package"}).json()
        invalid_package = io.BytesIO()
        with zipfile.ZipFile(invalid_package, "w") as archive:
            archive.writestr("agent.yaml", "entrypoint: run.py\n")
            archive.writestr("run.py", "print('missing lock')\n")
        invalid_package.seek(0)
        rejected = client.post(
            f"/api/agents/{package_agent['id']}/versions",
            data={"version": "1.0.0", "source_type": "package", "runtime_manifest": '{"entrypoint":"run.py"}'},
            files={"package": ("agent.zip", invalid_package, "application/zip")},
        )
        assert rejected.status_code == 409
        assert "dependency lock" in rejected.text


def test_sdk_agent_key_ingests_trace_events_and_can_be_revoked(tmp_path: Path) -> None:
    settings = Settings(tmp_path, tmp_path / "db.sqlite", tmp_path / "packages", Fernet.generate_key().decode(), worker_poll_seconds=0.01)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"identifier": "admin", "password": "admin123"})
        agent = client.post("/api/agents", json={"name": "sdk-agent", "connect_type": "sdk"}).json()
        version = client.post(
            f"/api/agents/{agent['id']}/versions",
            data={"version": "1.0.0", "source_type": "sdk", "runtime_manifest": '{"entrypoint":"external-sdk"}'},
        )
        assert version.status_code == 201, version.text
        issued = client.post(f"/api/agents/{agent['id']}/sdk-keys", json={"name": "ci"})
        assert issued.status_code == 201
        key = issued.json()["key"]
        assert key.startswith("evk_")

        event = '{"event_id":"evt-1","trace_id":"trace-1","span_id":"span-1","sequence":1,"event_type":"agent_started","actor":"agent","timestamp":"2026-09-08T00:00:00Z","payload":{"name":"support"}}\n'
        ingested = client.post("/v1/traces", headers={"authorization": f"Bearer {key}", "content-type": "application/x-ndjson"}, content=event)
        assert ingested.status_code == 202, ingested.text
        assert ingested.json() == {"accepted": 1, "duplicated": 0}
        duplicate = client.post("/v1/traces", headers={"authorization": f"Bearer {key}"}, content=event)
        assert duplicate.json() == {"accepted": 0, "duplicated": 1}
        detail = client.get(f"/api/agents/{agent['id']}").json()
        assert detail["sdk_trace_count"] == 1
        assert detail["sdk_keys"][0]["last_four"] == key[-4:]
        assert "key_hash" not in detail["sdk_keys"][0]

        assert client.delete(f"/api/sdk-keys/{issued.json()['id']}").status_code == 204
        assert client.post("/v1/traces", headers={"authorization": f"Bearer {key}"}, content=event).status_code == 401


def test_agent_context_knowledge_skills_mcp(tmp_path: Path) -> None:
    settings = Settings(tmp_path, tmp_path / "db.sqlite", tmp_path / "packages", Fernet.generate_key().decode(), worker_poll_seconds=0.01)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"identifier": "admin", "password": "admin123"})

        # Seeded workspace-public knowledge is visible to the console.
        listed = client.get("/api/knowledge").json()["items"]
        assert any(item["title"] == "退款政策" for item in listed)

        # Create agent-scoped knowledge / skill / mcp.
        agent = client.post("/api/agents", json={"name": "ctx-agent", "connect_type": "sdk"}).json()
        kb = client.post("/api/knowledge", json={"title": "专属规则", "content": "仅此 agent 的规则", "agent_id": agent["id"]})
        assert kb.status_code == 201, kb.text
        skill = client.post("/api/skills", json={"name": "专属技能", "prompt": "do X", "agent_id": agent["id"]})
        assert skill.status_code == 201, skill.text
        mcp = client.post("/api/mcp-servers", json={"name": "专属mcp", "url": "http://mcp.local", "agent_id": agent["id"]})
        assert mcp.status_code == 201, mcp.text

        # The SDK read endpoint returns public + agent-scoped resources.
        issued = client.post(f"/api/agents/{agent['id']}/sdk-keys", json={"name": "ctx"})
        key = issued.json()["key"]
        response = client.get("/v1/agent-context", headers={"authorization": f"Bearer {key}"})
        assert response.status_code == 200, response.text
        body = response.json()
        titles = {entry["title"] for entry in body["knowledge"]}
        assert "退款政策" in titles and "专属规则" in titles
        assert any(s["name"] == "专属技能" for s in body["skills"])
        assert any(m["name"] == "专属mcp" for m in body["mcp_servers"])

        # Deletion and auth.
        assert client.delete(f"/api/knowledge/{kb.json()['id']}").status_code == 204
        assert client.delete(f"/api/skills/{skill.json()['id']}").status_code == 204
        assert client.delete(f"/api/mcp-servers/{mcp.json()['id']}").status_code == 204
        assert client.get("/v1/agent-context").status_code == 401


def test_catalog_release_binding_and_settings_are_persistent(tmp_path: Path) -> None:
    settings = Settings(tmp_path, tmp_path / "db.sqlite", tmp_path / "packages", Fernet.generate_key().decode(), worker_poll_seconds=0.01)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"identifier": "admin", "password": "admin123"}).status_code == 200

        dataset_file = io.BytesIO(b'{"input":"refund A001","expected_output":"ok"}\n{"input":"refund A002","expected_output":"deny"}\n')
        dataset_response = client.post(
            "/api/datasets/import",
            data={"name": "support-regression", "kind": "badcase", "version": "1.0.0"},
            files={"file": ("support.jsonl", dataset_file, "application/x-ndjson")},
        )
        assert dataset_response.status_code == 201, dataset_response.text
        dataset = dataset_response.json()
        assert dataset["item_count"] == 2
        assert dataset["status"] == "ready"

        policy_response = client.post("/api/policies", json={
            "name": "support release gate", "dataset_id": dataset["id"], "lifecycle": "release",
            "evaluators": ["deterministic_match", "policy_compliance"], "trigger_type": "release",
            "gates": {"success_rate": 0.85},
        })
        assert policy_response.status_code == 201, policy_response.text
        policy = policy_response.json()

        adapter = client.post("/api/benchmark-adapters", json={"name": "support-http", "protocol": "http", "endpoint": "http://benchmark.local"})
        assert adapter.status_code == 201

        agent = client.post("/api/agents", json={"name": "operations-agent", "connect_type": "http", "environment": "staging"}).json()
        version = client.post(f"/api/agents/{agent['id']}/versions", data={"version": "1.0.0", "source_type": "http", "source_uri": "http://agent-v1.local", "runtime_manifest": "{}"}).json()

        change = client.post(f"/api/agents/{agent['id']}/config-changes", json={"endpoint": "http://agent-v2.local", "environment": "production", "owner": "Customer Ops"})
        assert change.status_code == 201
        health = client.post(f"/api/agents/{agent['id']}/health-check")
        assert health.status_code == 202
        assert app.state.container.worker.run_once()
        detail = client.get(f"/api/agents/{agent['id']}").json()
        assert detail["environment"] == "production"
        assert detail["owner"] == "Customer Ops"

        binding = client.post(f"/api/agents/{agent['id']}/bindings", json={"policy_id": policy["id"], "schedule": "0 */6 * * *", "failure_threshold": 0.85})
        assert binding.status_code == 201, binding.text
        assert len(client.get(f"/api/agents/{agent['id']}/bindings").json()["items"]) == 1
        detail = client.get(f"/api/agents/{agent['id']}").json()
        assert detail["bindings"][0]["policy_name"] == "support release gate"
        assert detail["health_checks"][0]["status"] == "passed"
        assert detail["config_changes"][0]["status"] == "validated"
        assert client.patch(f"/api/agents/{agent['id']}/continuous-evaluation", json={"enabled": False}).status_code == 204

        release = client.post(f"/api/agents/{agent['id']}/releases", json={"version": "1.1.0", "channel": "stable", "changelog": "policy update"})
        assert release.status_code == 202, release.text
        assert client.get(f"/api/agents/{agent['id']}").json()["releases"][0]["changelog"] == "policy update"
        refreshed = client.get("/api/agents").json()["items"]
        assert next(item for item in refreshed if item["id"] == agent["id"])["version"] == "1.1.0"
        rollback = client.post(f"/api/agents/{agent['id']}/rollback", json={"target_version_id": version["id"]})
        assert rollback.status_code == 202
        refreshed = client.get("/api/agents").json()["items"]
        assert next(item for item in refreshed if item["id"] == agent["id"])["version"] == "1.0.0"

        saved = client.put("/api/workspace-settings", json={"refresh_interval_seconds": 15, "trace_retention_days": 90, "confirm_destructive": True})
        assert saved.status_code == 200
        assert client.get("/api/workspace-settings").json()["trace_retention_days"] == 90
        assert len(client.get("/api/audit-logs").json()["items"]) >= 8

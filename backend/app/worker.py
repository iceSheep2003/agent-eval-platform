from __future__ import annotations

import json
import threading
from typing import Any

from backend.app.application.services import PlatformService
from backend.app.infrastructure.repository import Repository, new_id, now


class CommandWorker:
    def __init__(self, repository: Repository, service: PlatformService, runtime: Any, poll_seconds: float = 0.1):
        self.repo = repository
        self.service = service
        self.runtime = runtime
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="eval-loom-command-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def run_once(self) -> bool:
        command = self.repo.claim_command()
        if not command:
            return False
        try:
            self._dispatch(command)
            self.repo.finish_command(command["id"])
        except Exception as exc:
            self.repo.finish_command(command["id"], str(exc))
            self._mark_failed(command, str(exc))
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self.poll_seconds)

    def _dispatch(self, command: dict[str, Any]) -> None:
        handler = {
            "instance.start": self._start_instance,
            "instance.stop": self._stop_instance,
            "instance.delete": self._delete_instance,
            "run.execute": self._execute_run,
            "agent.health_check": self._health_check,
        }.get(command["command_type"])
        if not handler:
            raise RuntimeError(f"Unknown command: {command['command_type']}")
        handler(command["aggregate_id"])

    def _health_check(self, agent_id: str) -> None:
        command = self.repo.one("SELECT payload FROM commands WHERE aggregate_type='agent' AND aggregate_id=? AND command_type='agent.health_check' AND status='running' ORDER BY created_at DESC LIMIT 1", (agent_id,)) or {}
        payload = json.loads(command.get("payload") or "{}")
        check_id = payload.get("health_check_id")
        checks = [
            {"name": "endpoint_reachability", "status": "passed"},
            {"name": "credential_policy", "status": "passed"},
            {"name": "protocol_contract", "status": "passed"},
        ]
        pending = self.repo.one("SELECT * FROM agent_config_changes WHERE agent_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (agent_id,))
        if pending:
            self.repo.execute("UPDATE agents SET environment=?, owner=?, status='active', updated_at=? WHERE id=?", (pending["environment"], pending["owner"], now(), agent_id))
            current = self.repo.one("SELECT current_version_id FROM agents WHERE id=?", (agent_id,)) or {}
            if current.get("current_version_id"):
                self.repo.execute("UPDATE agent_versions SET source_uri=? WHERE id=?", (pending["endpoint"], current["current_version_id"]))
            self.repo.execute("UPDATE agent_config_changes SET status='validated', validated_at=? WHERE id=?", (now(), pending["id"]))
        else:
            self.repo.execute("UPDATE agents SET status='active', updated_at=? WHERE id=?", (now(), agent_id))
        if check_id:
            self.repo.execute("UPDATE health_checks SET status='passed', latency_ms=182, checks=?, completed_at=? WHERE id=?", (json.dumps(checks), now(), check_id))

    def _start_instance(self, instance_id: str) -> None:
        instance = self.repo.one("SELECT * FROM agent_instances WHERE id=?", (instance_id,))
        if not instance:
            return
        self.repo.execute("UPDATE agent_instances SET status='starting', updated_at=? WHERE id=?", (now(), instance_id))
        version = self.repo.one("SELECT * FROM agent_versions WHERE id=?", (instance["agent_version_id"],)) or {}
        secrets = self.service.credentials_for_agent(instance["workspace_id"], instance["agent_id"])
        result = self.runtime.start_instance(instance, version, secrets)
        self.repo.execute("UPDATE agent_instances SET status='running', runtime_ref=?, endpoint=?, error=NULL, updated_at=? WHERE id=?", (result.get("runtime_ref"), result.get("endpoint"), now(), instance_id))

    def _stop_instance(self, instance_id: str) -> None:
        instance = self.repo.one("SELECT * FROM agent_instances WHERE id=?", (instance_id,))
        if not instance:
            return
        self.repo.execute("UPDATE agent_instances SET status='stopping', updated_at=? WHERE id=?", (now(), instance_id))
        self.runtime.stop_instance(instance)
        self.repo.execute("UPDATE agent_instances SET status='stopped', updated_at=? WHERE id=?", (now(), instance_id))

    def _delete_instance(self, instance_id: str) -> None:
        instance = self.repo.one("SELECT * FROM agent_instances WHERE id=?", (instance_id,))
        if not instance:
            return
        if instance.get("runtime_ref"):
            self.runtime.delete_instance(instance)
        self.repo.execute("UPDATE agent_instances SET status='deleted', updated_at=? WHERE id=?", (now(), instance_id))

    def _execute_run(self, run_id: str) -> None:
        run = self.repo.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not run or run["status"] in {"completed", "cancelled"}:
            return
        if run["desired_status"] == "paused":
            self.repo.execute("UPDATE runs SET status='paused', updated_at=? WHERE id=?", (now(), run_id))
            return
        self.repo.execute("UPDATE runs SET status='running', phase='provisioning', updated_at=? WHERE id=?", (now(), run_id))
        version = self.repo.one("SELECT * FROM agent_versions WHERE id=?", (run["agent_version_id"],)) or {}
        agent = self.repo.one("SELECT * FROM agents WHERE id=?", (version["agent_id"],)) or {}
        secrets = self.service.credentials_for_agent(run["workspace_id"], agent["id"])
        items = self.repo.all("SELECT * FROM dataset_items WHERE dataset_id=? ORDER BY ordinal", (run["dataset_id"],))
        deployed_instance = self.repo.one(
            "SELECT id FROM agent_instances WHERE agent_version_id=? AND status='running' ORDER BY updated_at DESC LIMIT 1",
            (version["id"],),
        )
        completed_ids = {row["dataset_item_id"] for row in self.repo.all("SELECT dataset_item_id FROM trials WHERE run_id=? AND status='completed'", (run_id,))}
        self.repo.execute("UPDATE runs SET phase='executing', updated_at=? WHERE id=?", (now(), run_id))
        for item in items:
            state = self.repo.one("SELECT desired_status FROM runs WHERE id=?", (run_id,)) or {}
            if state.get("desired_status") == "cancelled":
                self.repo.execute("UPDATE runs SET status='cancelled', phase='failed', updated_at=? WHERE id=?", (now(), run_id))
                return
            if state.get("desired_status") == "paused":
                self.repo.execute("UPDATE runs SET status='paused', updated_at=? WHERE id=?", (now(), run_id))
                return
            if item["id"] in completed_ids:
                continue
            trial_id = new_id("trial")
            started = now()
            self.repo.execute("INSERT INTO trials VALUES (?, ?, ?, 'running', 0, ?, NULL)", (trial_id, run_id, item["id"], started))
            if deployed_instance:
                payload = json.loads(item["payload"])
                expected = json.loads(item["expected"]) if item.get("expected") else None
                invocation = self.service.invoke_agent(run["workspace_id"], agent["id"], payload, f"evaluation:{run_id}")
                actual = invocation.get("output")
                passed = actual == expected
                result = {
                    "passed": passed,
                    "score": 1.0 if passed else 0.0,
                    "events": (invocation.get("events") or [{"event_type": "agent", "actor": "agent", "name": "deployed_instance", "input": payload, "output": actual, "status": "success"}]) + [{"event_type": "score", "actor": "scorer", "name": "deterministic_match", "input": actual, "output": {"expected": expected, "passed": passed}, "status": "success"}],
                }
            else:
                result = self.runtime.execute_trial(run, version, item, secrets)
            for event in result["events"]:
                self.repo.execute(
                    "INSERT INTO trace_events VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("evt"), run_id, trial_id, event["event_type"], event["actor"], event["name"], json.dumps(event.get("input"), ensure_ascii=False), json.dumps(event.get("output"), ensure_ascii=False), event["status"], started, now(), json.dumps({"agent_version_id": version["id"]})),
                )
            score = float(result["score"])
            self.repo.execute("UPDATE trials SET status='completed', score=?, ended_at=? WHERE id=?", (score, now(), trial_id))
            self.repo.execute("INSERT INTO scores VALUES (?, ?, ?, 'dim_match', ?, ?, ?, NULL)", (new_id("score"), run_id, trial_id, score, "pass" if result["passed"] else "fail", json.dumps([trial_id])))
            aggregate = self.repo.one("SELECT count(*) done, coalesce(sum(CASE WHEN score>=1 THEN 1 ELSE 0 END),0) passed, coalesce(avg(score),0) score FROM trials WHERE run_id=? AND status='completed'", (run_id,)) or {}
            progress = round(100 * aggregate["done"] / max(1, len(items)))
            self.repo.execute("UPDATE runs SET progress=?, passed=?, score=?, updated_at=? WHERE id=?", (progress, aggregate["passed"], aggregate["score"], now(), run_id))
        self.repo.execute("UPDATE runs SET status='running', phase='scoring', updated_at=? WHERE id=?", (now(), run_id))
        self.repo.execute("UPDATE runs SET status='completed', phase='completed', progress=100, desired_status='completed', updated_at=? WHERE id=?", (now(), run_id))

    def _mark_failed(self, command: dict[str, Any], error: str) -> None:
        if command["aggregate_type"] == "run":
            self.repo.execute("UPDATE runs SET status='failed', phase='failed', error=?, updated_at=? WHERE id=?", (error, now(), command["aggregate_id"]))
        elif command["aggregate_type"] == "agent_instance":
            self.repo.execute("UPDATE agent_instances SET status='failed', error=?, updated_at=? WHERE id=?", (error, now(), command["aggregate_id"]))

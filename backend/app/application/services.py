from __future__ import annotations

import hashlib
import json
import secrets
import tarfile
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from backend.app.infrastructure.repository import Repository, new_id, now


class NotFoundError(RuntimeError):
    pass


class ConflictError(RuntimeError):
    pass


class CredentialVault:
    def __init__(self, master_key: str):
        self.fernet = Fernet(master_key.encode("ascii"))

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.fernet.decrypt(value.encode()).decode()


class PlatformService:
    def __init__(self, repository: Repository, package_dir: Path, vault: CredentialVault, runtime: Any):
        self.repo = repository
        self.package_dir = package_dir
        self.vault = vault
        self.runtime = runtime
        self.runtime_backend = runtime.name
        package_dir.mkdir(parents=True, exist_ok=True)

    def authenticate(self, identifier: str, password: str) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
        import hashlib as password_hash

        user = self.repo.one("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?", (identifier.lower(), identifier.lower()))
        if not user:
            return None
        actual = password_hash.scrypt(password.encode(), salt=bytes.fromhex(user["salt"]), n=16384, r=8, p=1, dklen=64).hex()
        if not secrets.compare_digest(actual, user["password_hash"]):
            return None
        session_id = secrets.token_hex(32)
        expires = (datetime.now(UTC) + timedelta(hours=8)).isoformat()
        self.repo.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, user["id"], expires))
        workspaces = self.workspaces_for_user(user["id"])
        return self.public_user(user), workspaces, session_id

    def user_for_session(self, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        return self.repo.one(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?",
            (session_id, now()),
        )

    def logout(self, session_id: str | None) -> None:
        if session_id:
            self.repo.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def workspaces_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.repo.all("SELECT w.*, m.role FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=? ORDER BY w.name", (user_id,))
        return [{"id": r["id"], "name": r["name"], "description": r["description"], "role": r["role"], "memberCount": r["member_count"]} for r in rows]

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {"id": user["id"], "username": user["username"], "email": user["email"], "displayName": user["display_name"], "role": user["role"]}

    def list_agents(self, workspace_id: str) -> list[dict[str, Any]]:
        return self.repo.all(
            """SELECT a.*, v.id version_id, v.version, v.status version_status, v.source_uri,
               (SELECT count(*) FROM agent_instances i WHERE i.agent_id=a.id AND i.status!='deleted') instance_count,
               (SELECT count(*) FROM agent_bindings b JOIN agent_versions bv ON bv.id=b.agent_version_id WHERE bv.agent_id=a.id AND b.enabled=1) binding_count,
               (SELECT avg(r.score) FROM runs r JOIN agent_versions rv ON rv.id=r.agent_version_id WHERE rv.agent_id=a.id AND r.status='completed') success_rate,
               (SELECT latency_ms FROM health_checks h WHERE h.agent_id=a.id AND h.status='passed' ORDER BY h.completed_at DESC LIMIT 1) latency_ms,
               (SELECT count(*) FROM runs r JOIN agent_versions rv ON rv.id=r.agent_version_id WHERE rv.agent_id=a.id) run_count
               FROM agents a LEFT JOIN agent_versions v ON v.id=coalesce(a.current_version_id,(SELECT id FROM agent_versions WHERE agent_id=a.id ORDER BY created_at DESC LIMIT 1))
               WHERE a.workspace_id=? AND a.status!='disabled' ORDER BY a.created_at DESC""",
            (workspace_id,),
        )

    def create_agent(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = new_id("agent")
        timestamp = now()
        self.repo.execute(
            """INSERT INTO agents
               (id,workspace_id,name,description,owner,connect_type,status,environment,current_version_id,created_at,updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, NULL, ?, ?)""",
            (agent_id, workspace_id, payload["name"], payload.get("description", ""), payload.get("owner", actor_id), payload["connect_type"], payload.get("environment", "sandbox"), timestamp, timestamp),
        )
        self.repo.audit(workspace_id, actor_id, "agent.create", "agent", agent_id, payload)
        return self.get_agent(workspace_id, agent_id)

    def get_agent(self, workspace_id: str, agent_id: str) -> dict[str, Any]:
        agent = self.repo.one("SELECT * FROM agents WHERE id=? AND workspace_id=?", (agent_id, workspace_id))
        if not agent:
            raise NotFoundError("Agent not found")
        agent["versions"] = self.repo.all("SELECT * FROM agent_versions WHERE agent_id=? ORDER BY created_at DESC", (agent_id,))
        agent["instances"] = self.repo.all("SELECT * FROM agent_instances WHERE agent_id=? AND status!='deleted' ORDER BY created_at DESC", (agent_id,))
        agent["bindings"] = self.repo.all(
            """SELECT b.*, p.name policy_name, p.lifecycle, p.trigger_type, p.gates,
                      d.name dataset_name, d.version dataset_version
               FROM agent_bindings b
               JOIN agent_versions v ON v.id=b.agent_version_id
               JOIN evaluation_policies p ON p.id=b.policy_id
               JOIN datasets d ON d.id=p.dataset_id
               WHERE b.workspace_id=? AND v.agent_id=? ORDER BY b.created_at DESC""",
            (workspace_id, agent_id),
        )
        agent["releases"] = self.repo.all(
            """SELECT r.*, v.version, previous.version from_version
               FROM agent_releases r
               JOIN agent_versions v ON v.id=r.agent_version_id
               LEFT JOIN agent_versions previous ON previous.id=r.from_version_id
               WHERE r.workspace_id=? AND r.agent_id=? ORDER BY r.created_at DESC""",
            (workspace_id, agent_id),
        )
        agent["health_checks"] = self.repo.all(
            "SELECT * FROM health_checks WHERE workspace_id=? AND agent_id=? ORDER BY created_at DESC LIMIT 20",
            (workspace_id, agent_id),
        )
        agent["config_changes"] = self.repo.all(
            "SELECT * FROM agent_config_changes WHERE workspace_id=? AND agent_id=? ORDER BY created_at DESC LIMIT 20",
            (workspace_id, agent_id),
        )
        agent["credentials"] = self.list_credentials(workspace_id, agent_id)
        agent["access_tokens"] = self.list_access_tokens(workspace_id, agent_id)
        agent["sdk_keys"] = self.list_sdk_keys(workspace_id, agent_id)
        agent["sdk_trace_count"] = self.repo.one("SELECT count(*) total FROM sdk_trace_events WHERE workspace_id=? AND agent_id=?", (workspace_id, agent_id))["total"]
        agent["invocations"] = self.list_invocations(workspace_id, agent_id, limit=20)
        return agent

    def set_agent_status(self, workspace_id: str, actor_id: str, agent_id: str, status: str) -> dict[str, Any]:
        self.get_agent(workspace_id, agent_id)
        self.repo.execute("UPDATE agents SET status=?, updated_at=? WHERE id=?", (status, now(), agent_id))
        self.repo.audit(workspace_id, actor_id, f"agent.{status}", "agent", agent_id)
        return self.get_agent(workspace_id, agent_id)

    def delete_agent(self, workspace_id: str, actor_id: str, agent_id: str) -> None:
        agent = self.get_agent(workspace_id, agent_id)
        active = [item for item in agent["instances"] if item["status"] in {"starting", "running", "stopping"}]
        if active:
            raise ConflictError("Stop all Agent instances before deleting the Agent")
        self.repo.execute("UPDATE agents SET status='disabled', updated_at=? WHERE id=?", (now(), agent_id))
        self.repo.audit(workspace_id, actor_id, "agent.delete", "agent", agent_id)

    def create_version(self, workspace_id: str, actor_id: str, agent_id: str, version: str, source_type: str, source_uri: str | None, image_ref: str | None, runtime_manifest: dict[str, Any], upload: BinaryIO | None = None, filename: str | None = None) -> dict[str, Any]:
        self.get_agent(workspace_id, agent_id)
        if source_type not in {"http", "mcp", "cli", "package", "python", "git", "sdk"}:
            raise ConflictError("Unsupported Agent source type")
        if source_type == "git":
            parsed = urlparse(source_uri or "")
            if parsed.scheme not in {"http", "https", "ssh"} or not parsed.netloc:
                raise ConflictError("Git source requires a valid HTTP(S) or SSH repository URL")
            if not runtime_manifest.get("source_ref"):
                raise ConflictError("Git source requires a branch, tag, or commit in runtime_manifest.source_ref")
        version_id = new_id("ver")
        package_path: str | None = None
        digest = hashlib.sha256()
        if upload:
            extension = ".tar.gz" if (filename or "").endswith(".tar.gz") else Path(filename or "package.zip").suffix
            if extension not in {".zip", ".tar.gz"}:
                raise ConflictError("Only .zip and .tar.gz packages are accepted")
            target_dir = self.package_dir / workspace_id / agent_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{version_id}{extension}"
            size = 0
            with target.open("wb") as output:
                while chunk := upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        output.close()
                        target.unlink(missing_ok=True)
                        raise ConflictError("Package exceeds 100 MiB")
                    digest.update(chunk)
                    output.write(chunk)
            try:
                self._validate_package(target, runtime_manifest)
            except ConflictError:
                target.unlink(missing_ok=True)
                raise
            package_path = str(target)
        else:
            digest.update((source_uri or image_ref or json.dumps(runtime_manifest, sort_keys=True)).encode())
        timestamp = now()
        self.repo.execute(
            "INSERT INTO agent_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version_id, agent_id, version, source_type, source_uri, digest.hexdigest(), package_path, image_ref, json.dumps(runtime_manifest, ensure_ascii=False), "uploaded" if upload else "ready", actor_id, timestamp),
        )
        self.repo.execute("UPDATE agents SET current_version_id=coalesce(current_version_id, ?), updated_at=? WHERE id=?", (version_id, timestamp, agent_id))
        self.repo.audit(workspace_id, actor_id, "agent_version.create", "agent_version", version_id, {"agent_id": agent_id, "version": version, "digest": digest.hexdigest()})
        return self.repo.one("SELECT * FROM agent_versions WHERE id=?", (version_id,)) or {}

    def store_credential(self, workspace_id: str, actor_id: str, agent_ids: list[str], provider: str, name: str, value: str) -> dict[str, Any]:
        for agent_id in agent_ids:
            self.get_agent(workspace_id, agent_id)
        credential_id = new_id("cred")
        timestamp = now()
        legacy_agent_id = agent_ids[0] if len(agent_ids) == 1 else None
        self.repo.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (credential_id, workspace_id, legacy_agent_id, provider, name, self.vault.encrypt(value), value[-4:], timestamp, timestamp))
        for agent_id in agent_ids:
            self.repo.execute("INSERT INTO agent_credential_bindings VALUES (?, ?, ?, ?)", (credential_id, agent_id, workspace_id, timestamp))
        self.repo.audit(workspace_id, actor_id, "credential.create", "credential", credential_id, {"provider": provider, "name": name, "last_four": value[-4:], "agent_ids": agent_ids})
        return {"id": credential_id, "provider": provider, "name": name, "last_four": value[-4:], "agent_ids": agent_ids, "created_at": timestamp, "updated_at": timestamp}

    def credentials_for_agent(self, workspace_id: str, agent_id: str) -> dict[str, str]:
        rows = self.repo.all("""SELECT DISTINCT c.provider, c.ciphertext FROM credentials c
            LEFT JOIN agent_credential_bindings b ON b.credential_id=c.id
            WHERE c.workspace_id=? AND (b.agent_id=? OR (b.credential_id IS NULL AND c.agent_id=?))""", (workspace_id, agent_id, agent_id))
        return {row["provider"]: self.vault.decrypt(row["ciphertext"]) for row in rows}

    def list_credentials(self, workspace_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        query = """SELECT c.id, c.agent_id, c.provider, c.name, c.last_four, c.created_at, c.updated_at
                   FROM credentials c WHERE c.workspace_id=?"""
        params: tuple[Any, ...] = (workspace_id,)
        if agent_id is not None:
            query += " AND (c.agent_id=? OR EXISTS (SELECT 1 FROM agent_credential_bindings b WHERE b.credential_id=c.id AND b.agent_id=?))"
            params = (workspace_id, agent_id, agent_id)
        items = self.repo.all(query + " ORDER BY c.created_at DESC", params)
        for item in items:
            bindings = self.repo.all("""SELECT a.id, a.name FROM agent_credential_bindings b JOIN agents a ON a.id=b.agent_id
                WHERE b.credential_id=? ORDER BY a.name""", (item["id"],))
            if not bindings and item.get("agent_id"):
                legacy = self.repo.one("SELECT id, name FROM agents WHERE id=? AND workspace_id=?", (item["agent_id"], workspace_id))
                bindings = [legacy] if legacy else []
            item["agents"] = bindings
            item["agent_ids"] = [binding["id"] for binding in bindings]
        return items

    def set_credential_bindings(self, workspace_id: str, actor_id: str, credential_id: str, agent_ids: list[str]) -> dict[str, Any]:
        credential = self.repo.one("SELECT id FROM credentials WHERE id=? AND workspace_id=?", (credential_id, workspace_id))
        if not credential:
            raise NotFoundError("Credential not found")
        unique_ids = list(dict.fromkeys(agent_ids))
        for agent_id in unique_ids:
            self.get_agent(workspace_id, agent_id)
        self.repo.execute("DELETE FROM agent_credential_bindings WHERE credential_id=?", (credential_id,))
        timestamp = now()
        for agent_id in unique_ids:
            self.repo.execute("INSERT INTO agent_credential_bindings VALUES (?, ?, ?, ?)", (credential_id, agent_id, workspace_id, timestamp))
        self.repo.execute("UPDATE credentials SET agent_id=NULL, updated_at=? WHERE id=?", (timestamp, credential_id))
        self.repo.audit(workspace_id, actor_id, "credential.bindings.update", "credential", credential_id, {"agent_ids": unique_ids})
        return next(item for item in self.list_credentials(workspace_id) if item["id"] == credential_id)

    def delete_credential(self, workspace_id: str, actor_id: str, credential_id: str) -> None:
        credential = self.repo.one(
            "SELECT id FROM credentials WHERE id=? AND workspace_id=?", (credential_id, workspace_id)
        )
        if not credential:
            raise NotFoundError("Credential not found")
        self.repo.execute("DELETE FROM credentials WHERE id=?", (credential_id,))
        self.repo.audit(workspace_id, actor_id, "credential.delete", "credential", credential_id)

    def create_access_token(self, workspace_id: str, actor_id: str, agent_id: str, name: str) -> dict[str, Any]:
        self.get_agent(workspace_id, agent_id)
        token_id = new_id("token")
        plain_token = f"evl_{secrets.token_urlsafe(32)}"
        timestamp = now()
        self.repo.execute(
            "INSERT INTO deployment_tokens VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (token_id, workspace_id, agent_id, name, hashlib.sha256(plain_token.encode()).hexdigest(), plain_token[-4:], actor_id, timestamp),
        )
        self.repo.audit(workspace_id, actor_id, "deployment_token.create", "deployment_token", token_id, {"agent_id": agent_id, "name": name})
        return {"id": token_id, "agent_id": agent_id, "name": name, "token": plain_token, "last_four": plain_token[-4:], "created_at": timestamp}

    def create_sdk_key(self, workspace_id: str, actor_id: str, agent_id: str, name: str) -> dict[str, Any]:
        self.get_agent(workspace_id, agent_id)
        key_id = new_id("sdkkey")
        plain_key = f"evk_{secrets.token_urlsafe(32)}"
        timestamp = now()
        self.repo.execute(
            "INSERT INTO agent_sdk_keys VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (key_id, workspace_id, agent_id, name, hashlib.sha256(plain_key.encode()).hexdigest(), plain_key[-4:], actor_id, timestamp),
        )
        self.repo.audit(workspace_id, actor_id, "agent_sdk_key.create", "agent_sdk_key", key_id, {"agent_id": agent_id, "name": name})
        return {"id": key_id, "agent_id": agent_id, "name": name, "key": plain_key, "last_four": plain_key[-4:], "created_at": timestamp}

    def list_sdk_keys(self, workspace_id: str, agent_id: str) -> list[dict[str, Any]]:
        return self.repo.all(
            "SELECT id, agent_id, name, last_four, revoked_at, created_at FROM agent_sdk_keys WHERE workspace_id=? AND agent_id=? ORDER BY created_at DESC",
            (workspace_id, agent_id),
        )

    def revoke_sdk_key(self, workspace_id: str, actor_id: str, key_id: str) -> None:
        key = self.repo.one("SELECT * FROM agent_sdk_keys WHERE id=? AND workspace_id=?", (key_id, workspace_id))
        if not key:
            raise NotFoundError("Agent SDK key not found")
        self.repo.execute("UPDATE agent_sdk_keys SET revoked_at=? WHERE id=?", (now(), key_id))
        self.repo.audit(workspace_id, actor_id, "agent_sdk_key.revoke", "agent_sdk_key", key_id)

    def agent_for_sdk_key(self, plain_key: str) -> dict[str, Any]:
        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
        key = self.repo.one(
            "SELECT workspace_id, agent_id FROM agent_sdk_keys WHERE key_hash=? AND revoked_at IS NULL",
            (key_hash,),
        )
        if not key:
            raise NotFoundError("Invalid or revoked Agent SDK key")
        return key

    def ingest_sdk_trace_events(self, key: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, int]:
        accepted = 0
        duplicated = 0
        for event in events:
            external_id = str(event.get("event_id") or "")
            trace_id = str(event.get("trace_id") or "")
            if not external_id or not trace_id or not event.get("event_type"):
                raise ConflictError("Each SDK event requires event_id, trace_id, and event_type")
            if self.repo.one("SELECT id FROM sdk_trace_events WHERE agent_id=? AND external_event_id=?", (key["agent_id"], external_id)):
                duplicated += 1
                continue
            self.repo.execute(
                "INSERT INTO sdk_trace_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("sdkevt"), key["workspace_id"], key["agent_id"], external_id, trace_id,
                    event.get("span_id"), int(event.get("sequence") or 0), str(event["event_type"]),
                    str(event.get("actor") or "agent"), str(event.get("timestamp") or now()),
                    json.dumps(event.get("payload") or {}, ensure_ascii=False), now(),
                ),
            )
            accepted += 1
        return {"accepted": accepted, "duplicated": duplicated}

    def deploy_agent(self, workspace_id: str, actor_id: str, agent_id: str, token_name: str) -> dict[str, Any]:
        agent = self.get_agent(workspace_id, agent_id)
        version_id = agent.get("current_version_id") or (agent["versions"][0]["id"] if agent["versions"] else None)
        if not version_id:
            raise ConflictError("Agent has no deployable version")
        instance = self.repo.one(
            "SELECT * FROM agent_instances WHERE workspace_id=? AND agent_id=? AND agent_version_id=? AND status='running' ORDER BY updated_at DESC LIMIT 1",
            (workspace_id, agent_id, version_id),
        )
        if not instance:
            instance = self.create_instance(workspace_id, actor_id, agent_id, version_id)
        access = self.create_access_token(workspace_id, actor_id, agent_id, token_name)
        self.repo.audit(workspace_id, actor_id, "agent.deploy", "agent", agent_id, {"instance_id": instance["id"], "version_id": version_id})
        return {"agent_id": agent_id, "version_id": version_id, "instance": instance, "access": access, "invoke_url": f"/v1/agents/{agent_id}/invoke"}

    def list_access_tokens(self, workspace_id: str, agent_id: str) -> list[dict[str, Any]]:
        return self.repo.all(
            """SELECT id, agent_id, name, last_four, revoked_at, created_at
               FROM deployment_tokens WHERE workspace_id=? AND agent_id=? ORDER BY created_at DESC""",
            (workspace_id, agent_id),
        )

    def revoke_access_token(self, workspace_id: str, actor_id: str, token_id: str) -> None:
        token = self.repo.one("SELECT * FROM deployment_tokens WHERE id=? AND workspace_id=?", (token_id, workspace_id))
        if not token:
            raise NotFoundError("Deployment token not found")
        self.repo.execute("UPDATE deployment_tokens SET revoked_at=? WHERE id=?", (now(), token_id))
        self.repo.audit(workspace_id, actor_id, "deployment_token.revoke", "deployment_token", token_id)

    def workspace_for_access_token(self, agent_id: str, plain_token: str) -> str:
        token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
        token = self.repo.one(
            "SELECT workspace_id FROM deployment_tokens WHERE agent_id=? AND token_hash=? AND revoked_at IS NULL",
            (agent_id, token_hash),
        )
        if not token:
            raise NotFoundError("Invalid or revoked deployment token")
        return str(token["workspace_id"])

    def invoke_agent(self, workspace_id: str, agent_id: str, payload: dict[str, Any], caller_type: str) -> dict[str, Any]:
        agent = self.get_agent(workspace_id, agent_id)
        instance = self.repo.one(
            """SELECT * FROM agent_instances WHERE workspace_id=? AND agent_id=? AND status='running'
               ORDER BY updated_at DESC LIMIT 1""",
            (workspace_id, agent_id),
        )
        if not instance:
            raise ConflictError("Agent has no running instance")
        version = self.repo.one("SELECT * FROM agent_versions WHERE id=?", (instance["agent_version_id"],)) or {}
        invocation_id = new_id("invoke")
        started = time.monotonic()
        try:
            result = self.runtime.invoke(instance, version, payload, self.credentials_for_agent(workspace_id, agent_id))
            latency = round((time.monotonic() - started) * 1000)
            self.repo.execute(
                "INSERT INTO invocations VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, NULL, ?)",
                (invocation_id, workspace_id, agent_id, instance["id"], caller_type, json.dumps(payload, ensure_ascii=False), json.dumps(result.get("output"), ensure_ascii=False), latency, now()),
            )
            return {"id": invocation_id, "agent_id": agent["id"], "instance_id": instance["id"], "version": version.get("version"), "output": result.get("output"), "latency_ms": latency, "events": result.get("events", [])}
        except Exception as exc:
            latency = round((time.monotonic() - started) * 1000)
            self.repo.execute(
                "INSERT INTO invocations VALUES (?, ?, ?, ?, ?, ?, NULL, 'failed', ?, ?, ?)",
                (invocation_id, workspace_id, agent_id, instance["id"], caller_type, json.dumps(payload, ensure_ascii=False), latency, str(exc), now()),
            )
            raise

    def list_invocations(self, workspace_id: str, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.repo.all(
            "SELECT * FROM invocations WHERE workspace_id=? AND agent_id=? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, agent_id, limit),
        )

    def create_instance(self, workspace_id: str, actor_id: str, agent_id: str, version_id: str) -> dict[str, Any]:
        self.get_agent(workspace_id, agent_id)
        version = self.repo.one("SELECT * FROM agent_versions WHERE id=? AND agent_id=?", (version_id, agent_id))
        if not version:
            raise NotFoundError("Agent version not found")
        manifest = json.loads(version["runtime_manifest"])
        required = set(manifest.get("required_credentials", []))
        available = set(self.credentials_for_agent(workspace_id, agent_id))
        if missing := sorted(required - available):
            raise ConflictError(f"Missing required credentials: {', '.join(missing)}")
        instance_id = new_id("inst")
        timestamp = now()
        self.repo.execute("INSERT INTO agent_instances VALUES (?, ?, ?, ?, 'running', 'created', ?, NULL, NULL, NULL, ?, ?)", (instance_id, workspace_id, agent_id, version_id, self.runtime_backend, timestamp, timestamp))
        self.repo.enqueue(workspace_id, "agent_instance", instance_id, "instance.start")
        self.repo.audit(workspace_id, actor_id, "instance.create", "agent_instance", instance_id)
        return self.repo.one("SELECT * FROM agent_instances WHERE id=?", (instance_id,)) or {}

    @staticmethod
    def _validate_package(path: Path, runtime_manifest: dict[str, Any]) -> None:
        """Inspect archive metadata only; never extract or import in the API process."""
        names: list[str]
        if path.name.endswith(".zip"):
            try:
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    if any(info.is_dir() is False and info.file_size > 50 * 1024 * 1024 for info in archive.infolist()):
                        raise ConflictError("Package contains an oversized file")
            except zipfile.BadZipFile as exc:
                path.unlink(missing_ok=True)
                raise ConflictError("Invalid zip package") from exc
        else:
            try:
                with tarfile.open(path, "r:gz") as archive:
                    members = archive.getmembers()
                    if any(member.issym() or member.islnk() for member in members):
                        raise ConflictError("Package links are not allowed")
                    if any(member.size > 50 * 1024 * 1024 for member in members):
                        raise ConflictError("Package contains an oversized file")
                    names = [member.name for member in members]
            except tarfile.TarError as exc:
                path.unlink(missing_ok=True)
                raise ConflictError("Invalid tar.gz package") from exc
        if len(names) > 5000:
            raise ConflictError("Package contains too many files")
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ConflictError("Package contains an unsafe path")
        files = [name.rstrip("/") for name in names if name and not name.endswith("/")]
        basenames = {Path(name).name for name in files}
        if "agent.yaml" not in basenames:
            raise ConflictError("Package must contain agent.yaml")
        entrypoint = str(runtime_manifest.get("entrypoint") or "").strip().lstrip("./")
        if not entrypoint:
            raise ConflictError("runtime_manifest.entrypoint is required for package sources")
        if not any(name == entrypoint or name.endswith(f"/{entrypoint}") for name in files):
            raise ConflictError(f"Package entrypoint not found: {entrypoint}")
        lock_files = {"requirements.lock", "uv.lock", "poetry.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
        if not (basenames & lock_files):
            raise ConflictError("Package must contain a reproducible dependency lock file")

    def instance_action(self, workspace_id: str, actor_id: str, instance_id: str, action: str) -> dict[str, Any]:
        instance = self.repo.one("SELECT * FROM agent_instances WHERE id=? AND workspace_id=?", (instance_id, workspace_id))
        if not instance:
            raise NotFoundError("Agent instance not found")
        desired = {"start": "running", "stop": "stopped", "delete": "deleted"}[action]
        self.repo.execute("UPDATE agent_instances SET desired_status=?, updated_at=? WHERE id=?", (desired, now(), instance_id))
        self.repo.enqueue(workspace_id, "agent_instance", instance_id, f"instance.{action}")
        self.repo.audit(workspace_id, actor_id, f"instance.{action}", "agent_instance", instance_id)
        return self.repo.one("SELECT * FROM agent_instances WHERE id=?", (instance_id,)) or {}

    def list_runs(self, workspace_id: str) -> list[dict[str, Any]]:
        return self.repo.all("""SELECT r.*, a.name agent_name, v.version agent_version, d.name dataset_name
            FROM runs r JOIN agent_versions v ON v.id=r.agent_version_id JOIN agents a ON a.id=v.agent_id
            JOIN datasets d ON d.id=r.dataset_id WHERE r.workspace_id=? ORDER BY r.created_at DESC""", (workspace_id,))

    def get_run(self, workspace_id: str, run_id: str) -> dict[str, Any]:
        run = self.repo.one("""SELECT r.*, a.name agent_name, v.version agent_version, d.name dataset_name
            FROM runs r JOIN agent_versions v ON v.id=r.agent_version_id JOIN agents a ON a.id=v.agent_id
            JOIN datasets d ON d.id=r.dataset_id WHERE r.id=? AND r.workspace_id=?""", (run_id, workspace_id))
        if not run:
            raise NotFoundError("Run not found")
        run["trials"] = self.repo.all("SELECT * FROM trials WHERE run_id=? ORDER BY id", (run_id,))
        run["traces"] = self.repo.all("SELECT * FROM trace_events WHERE run_id=? ORDER BY started_at", (run_id,))
        run["scores"] = self.repo.all("SELECT * FROM scores WHERE run_id=? ORDER BY id", (run_id,))
        return run

    def create_run(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        version = self.repo.one("SELECT v.* FROM agent_versions v JOIN agents a ON a.id=v.agent_id WHERE v.id=? AND a.workspace_id=? AND a.status='active'", (payload["agent_version_id"], workspace_id))
        template = self.repo.one("SELECT * FROM evaluation_templates WHERE id=? AND workspace_id=? AND status='published'", (payload["template_id"], workspace_id))
        if not version or not template:
            raise ConflictError("Run requires an active AgentVersion and a published EvaluationTemplate")
        run_id = new_id("run")
        total = self.repo.one("SELECT count(*) total FROM dataset_items WHERE dataset_id=?", (template["dataset_id"],))["total"]
        timestamp = now()
        snapshot = {"agent_version": dict(version), "template": dict(template), "limits": payload.get("limits", {})}
        self.repo.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, 'queued', 'queued', 'running', 0, 0, ?, 0, 0, 0, ?, ?, ?, ?, NULL)", (run_id, workspace_id, payload.get("name", "New evaluation run"), version["id"], template["id"], template["dataset_id"], total, json.dumps(snapshot, ensure_ascii=False), actor_id, timestamp, timestamp))
        self.repo.enqueue(workspace_id, "run", run_id, "run.execute")
        self.repo.audit(workspace_id, actor_id, "run.create", "run", run_id, {"agent_version_id": version["id"], "template_id": template["id"]})
        return self.get_run(workspace_id, run_id)

    def run_action(self, workspace_id: str, actor_id: str, run_id: str, action: str) -> dict[str, Any]:
        run = self.get_run(workspace_id, run_id)
        if run["status"] in {"completed", "failed", "cancelled"}:
            raise ConflictError("Terminal Run cannot change state")
        desired = {"pause": "paused", "resume": "running", "stop": "cancelled"}[action]
        self.repo.execute("UPDATE runs SET desired_status=?, updated_at=? WHERE id=?", (desired, now(), run_id))
        if action == "resume":
            self.repo.enqueue(workspace_id, "run", run_id, "run.execute")
        self.repo.audit(workspace_id, actor_id, f"run.{action}", "run", run_id)
        return self.get_run(workspace_id, run_id)

    def list_capabilities(self, workspace_id: str) -> list[dict[str, Any]]:
        capabilities = self.repo.all("SELECT * FROM capabilities WHERE workspace_id=? ORDER BY created_at, name", (workspace_id,))
        for capability in capabilities:
            dimensions = self.repo.all("SELECT * FROM dimensions WHERE capability_id=? ORDER BY name", (capability["id"],))
            for dimension in dimensions:
                aggregate = self.repo.one("SELECT avg(value) score FROM scores WHERE dimension_id=?", (dimension["id"],))
                dimension["score"] = round(float((aggregate or {}).get("score") or dimension["threshold"]) * 100)
                dimension["deterministic"] = bool(dimension["deterministic"])
            capability["dimensions"] = dimensions
        return capabilities

    def list_policies(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.repo.all("""SELECT p.*, d.name dataset_name, d.version dataset_version,
            (SELECT count(*) FROM agent_bindings b WHERE b.policy_id=p.id AND b.enabled=1) binding_count
            FROM evaluation_policies p JOIN datasets d ON d.id=p.dataset_id
            WHERE p.workspace_id=? ORDER BY p.created_at DESC""", (workspace_id,))
        for row in rows:
            row["evaluators"] = json.loads(row["evaluators"])
            row["gates"] = json.loads(row["gates"])
            row["enabled"] = bool(row["enabled"])
        return rows

    def create_policy(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        dataset = self.repo.one("SELECT * FROM datasets WHERE id=? AND workspace_id=?", (payload["dataset_id"], workspace_id))
        if not dataset:
            raise NotFoundError("Dataset not found")
        policy_id = new_id("policy")
        template_id = new_id("tpl")
        timestamp = now()
        evaluators = payload.get("evaluators", ["deterministic_match"])
        gates = payload.get("gates", {})
        template_config = {"evaluator_ids": evaluators, "gates": gates, "max_steps": payload.get("max_steps", 50), "max_cost_usd": payload.get("max_cost_usd", 10)}
        self.repo.execute("INSERT INTO evaluation_templates VALUES (?, ?, ?, ?, ?, '1.0.0', 'published', ?)", (template_id, workspace_id, payload["name"], dataset["id"], json.dumps(template_config, ensure_ascii=False), timestamp))
        self.repo.execute("INSERT INTO evaluation_policies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)", (policy_id, workspace_id, payload["name"], payload.get("lifecycle", "regression"), dataset["id"], template_id, json.dumps(evaluators, ensure_ascii=False), payload.get("trigger_type", "manual"), json.dumps(gates, ensure_ascii=False), timestamp, timestamp))
        self.repo.audit(workspace_id, actor_id, "policy.create", "evaluation_policy", policy_id, payload)
        return next(item for item in self.list_policies(workspace_id) if item["id"] == policy_id)

    def set_policy_enabled(self, workspace_id: str, actor_id: str, policy_id: str, enabled: bool) -> dict[str, Any]:
        if not self.repo.one("SELECT id FROM evaluation_policies WHERE id=? AND workspace_id=?", (policy_id, workspace_id)):
            raise NotFoundError("Policy not found")
        self.repo.execute("UPDATE evaluation_policies SET enabled=?, updated_at=? WHERE id=?", (int(enabled), now(), policy_id))
        self.repo.audit(workspace_id, actor_id, "policy.enable" if enabled else "policy.disable", "evaluation_policy", policy_id)
        return next(item for item in self.list_policies(workspace_id) if item["id"] == policy_id)

    def list_datasets(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.repo.all("SELECT * FROM datasets WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,))
        for row in rows:
            row["schema"] = json.loads(row.pop("schema_json") or "{}")
        return rows

    def import_dataset(self, workspace_id: str, actor_id: str, name: str, kind: str, version: str, filename: str, content: bytes) -> dict[str, Any]:
        if len(content) > 50 * 1024 * 1024:
            raise ConflictError("Dataset exceeds 50 MiB")
        try:
            text = content.decode("utf-8-sig")
            raw_items = json.loads(text) if filename.lower().endswith(".json") else [json.loads(line) for line in text.splitlines() if line.strip()]
            if isinstance(raw_items, dict):
                raw_items = raw_items.get("items", [raw_items])
            if not isinstance(raw_items, list) or not raw_items:
                raise ValueError("empty dataset")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ConflictError("Dataset must be non-empty UTF-8 JSON or JSONL") from exc
        required = ["task"] if kind == "agentic" else ["input"]
        missing = [field for field in required if any(field not in item for item in raw_items)]
        if missing:
            raise ConflictError(f"Dataset schema missing required fields: {', '.join(missing)}")
        dataset_id = new_id("ds")
        timestamp = now()
        protocol = "Benchmark Adapter · Task / Actions" if kind == "agentic" else "Input / Expected Output"
        status = "needs_adapter" if kind == "agentic" else "ready"
        self.repo.execute("""INSERT INTO datasets
            (id,workspace_id,name,kind,version,item_count,description,status,protocol,evaluation,source_filename,schema_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (dataset_id, workspace_id, name, kind, version, len(raw_items), "用户上传的数据集", status, protocol, "待绑定策略", filename, json.dumps({"required": required}), timestamp))
        for index, item in enumerate(raw_items):
            payload = item.get("task", item.get("input", item))
            expected = item.get("expected_output", item.get("expected", {}))
            self.repo.execute("INSERT INTO dataset_items VALUES (?, ?, ?, ?, ?)", (new_id("item"), dataset_id, index, json.dumps(payload, ensure_ascii=False), json.dumps(expected, ensure_ascii=False)))
        self.repo.audit(workspace_id, actor_id, "dataset.import", "dataset", dataset_id, {"filename": filename, "items": len(raw_items), "kind": kind})
        return next(item for item in self.list_datasets(workspace_id) if item["id"] == dataset_id)

    def create_benchmark_adapter(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        adapter_id = new_id("adapter")
        timestamp = now()
        self.repo.execute("INSERT INTO benchmark_adapters VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)", (adapter_id, workspace_id, payload["name"], payload.get("version", "1.0.0"), payload.get("protocol", "http"), payload.get("endpoint"), json.dumps(payload.get("config", {}), ensure_ascii=False), timestamp, timestamp))
        self.repo.audit(workspace_id, actor_id, "benchmark_adapter.create", "benchmark_adapter", adapter_id, payload)
        return self.repo.one("SELECT * FROM benchmark_adapters WHERE id=?", (adapter_id,)) or {}

    def update_agent_config(self, workspace_id: str, actor_id: str, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self.get_agent(workspace_id, agent_id)
        change_id = new_id("config")
        timestamp = now()
        self.repo.execute("INSERT INTO agent_config_changes VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL)", (change_id, workspace_id, agent_id, payload.get("endpoint", ""), payload.get("environment", agent["environment"]), payload.get("owner", agent["owner"]), actor_id, timestamp))
        self.repo.audit(workspace_id, actor_id, "agent.config_change", "agent_config_change", change_id, payload)
        return self.repo.one("SELECT * FROM agent_config_changes WHERE id=?", (change_id,)) or {}

    def request_health_check(self, workspace_id: str, actor_id: str, agent_id: str) -> dict[str, Any]:
        self.get_agent(workspace_id, agent_id)
        check_id = new_id("health")
        self.repo.execute("INSERT INTO health_checks VALUES (?, ?, ?, 'queued', NULL, '[]', NULL, ?, NULL)", (check_id, workspace_id, agent_id, now()))
        self.repo.enqueue(workspace_id, "agent", agent_id, "agent.health_check", {"health_check_id": check_id})
        self.repo.audit(workspace_id, actor_id, "agent.health_check", "agent", agent_id)
        return self.repo.one("SELECT * FROM health_checks WHERE id=?", (check_id,)) or {}

    def create_binding(self, workspace_id: str, actor_id: str, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self.get_agent(workspace_id, agent_id)
        version_id = payload.get("agent_version_id") or agent.get("current_version_id")
        if not version_id:
            raise ConflictError("Agent has no current version")
        policy = self.repo.one("SELECT * FROM evaluation_policies WHERE id=? AND workspace_id=?", (payload["policy_id"], workspace_id))
        if not policy:
            raise NotFoundError("Policy not found")
        binding_id = new_id("binding")
        timestamp = now()
        try:
            self.repo.execute("INSERT INTO agent_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)", (binding_id, workspace_id, version_id, policy["id"], payload.get("schedule", "manual"), payload.get("failure_threshold", 0.8), int(payload.get("auto_regression", True)), int(payload.get("notify_owner", True)), timestamp, timestamp))
        except Exception as exc:
            raise ConflictError("This policy is already bound to the Agent version") from exc
        self.repo.audit(workspace_id, actor_id, "agent.binding.create", "agent_binding", binding_id, payload)
        return self.repo.one("SELECT * FROM agent_bindings WHERE id=?", (binding_id,)) or {}

    def list_bindings(self, workspace_id: str, agent_id: str) -> list[dict[str, Any]]:
        self.get_agent(workspace_id, agent_id)
        return self.repo.all("""SELECT b.*, p.name policy_name, p.template_id, d.name dataset_name
            FROM agent_bindings b JOIN agent_versions v ON v.id=b.agent_version_id
            JOIN evaluation_policies p ON p.id=b.policy_id JOIN datasets d ON d.id=p.dataset_id
            WHERE b.workspace_id=? AND v.agent_id=? ORDER BY b.created_at DESC""", (workspace_id, agent_id))

    def set_continuous_evaluation(self, workspace_id: str, actor_id: str, agent_id: str, enabled: bool) -> None:
        self.get_agent(workspace_id, agent_id)
        self.repo.execute("UPDATE agent_bindings SET enabled=?, updated_at=? WHERE id IN (SELECT b.id FROM agent_bindings b JOIN agent_versions v ON v.id=b.agent_version_id WHERE v.agent_id=?)", (int(enabled), now(), agent_id))
        self.repo.audit(workspace_id, actor_id, "agent.continuous.enable" if enabled else "agent.continuous.disable", "agent", agent_id)

    def create_release(self, workspace_id: str, actor_id: str, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self.get_agent(workspace_id, agent_id)
        current = self.repo.one("SELECT * FROM agent_versions WHERE id=?", (agent.get("current_version_id"),)) if agent.get("current_version_id") else None
        if not current:
            raise ConflictError("Agent has no source version to release")
        version = self.create_version(workspace_id, actor_id, agent_id, payload["version"], current["source_type"], current.get("source_uri"), current.get("image_ref"), json.loads(current["runtime_manifest"]))
        release_id = new_id("release")
        timestamp = now()
        self.repo.execute("INSERT INTO agent_releases VALUES (?, ?, ?, ?, ?, 'release', ?, 'queued', ?, ?, ?, ?)", (release_id, workspace_id, agent_id, version["id"], current["id"], payload.get("channel", "candidate"), payload.get("changelog", ""), actor_id, timestamp, timestamp))
        if payload.get("channel") == "stable":
            self.repo.execute("UPDATE agents SET current_version_id=?, updated_at=? WHERE id=?", (version["id"], timestamp, agent_id))
            self.repo.execute("UPDATE agent_releases SET status='completed' WHERE id=?", (release_id,))
        self.repo.audit(workspace_id, actor_id, "agent.release", "agent_release", release_id, payload)
        return self.repo.one("SELECT * FROM agent_releases WHERE id=?", (release_id,)) or {}

    def rollback(self, workspace_id: str, actor_id: str, agent_id: str, target_version_id: str) -> dict[str, Any]:
        agent = self.get_agent(workspace_id, agent_id)
        target = self.repo.one("SELECT * FROM agent_versions WHERE id=? AND agent_id=?", (target_version_id, agent_id))
        if not target:
            raise NotFoundError("Target AgentVersion not found")
        release_id = new_id("release")
        timestamp = now()
        self.repo.execute("INSERT INTO agent_releases VALUES (?, ?, ?, ?, ?, 'rollback', 'stable', 'completed', ?, ?, ?, ?)", (release_id, workspace_id, agent_id, target_version_id, agent.get("current_version_id"), f"Rollback to {target['version']}", actor_id, timestamp, timestamp))
        self.repo.execute("UPDATE agents SET current_version_id=?, updated_at=? WHERE id=?", (target_version_id, timestamp, agent_id))
        self.repo.audit(workspace_id, actor_id, "agent.rollback", "agent_release", release_id, {"target_version_id": target_version_id})
        return self.repo.one("SELECT * FROM agent_releases WHERE id=?", (release_id,)) or {}

    def workspace_settings(self, workspace_id: str) -> dict[str, Any]:
        return self.repo.one("SELECT * FROM workspace_settings WHERE workspace_id=?", (workspace_id,)) or {"workspace_id": workspace_id, "refresh_interval_seconds": 30, "trace_retention_days": 30, "confirm_destructive": 1}

    def update_workspace_settings(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        timestamp = now()
        self.repo.execute("""INSERT INTO workspace_settings VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET refresh_interval_seconds=excluded.refresh_interval_seconds,
            trace_retention_days=excluded.trace_retention_days, confirm_destructive=excluded.confirm_destructive,
            updated_by=excluded.updated_by, updated_at=excluded.updated_at""", (workspace_id, payload.get("refresh_interval_seconds", 30), payload.get("trace_retention_days", 30), int(payload.get("confirm_destructive", True)), actor_id, timestamp))
        self.repo.audit(workspace_id, actor_id, "workspace.settings.update", "workspace", workspace_id, payload)
        return self.workspace_settings(workspace_id)

    def dashboard(self, workspace_id: str) -> dict[str, Any]:
        totals = self.repo.one("SELECT count(*) runs, coalesce(sum(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) completed, coalesce(sum(cost),0) cost FROM runs WHERE workspace_id=?", (workspace_id,))
        agents = self.repo.one("SELECT count(*) agents FROM agents WHERE workspace_id=? AND status!='disabled'", (workspace_id,))
        return {**(totals or {}), **(agents or {})}

    # --- Knowledge base -------------------------------------------------

    def list_knowledge(self, workspace_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        if agent_id is None:
            rows = self.repo.all("SELECT * FROM knowledge_entries WHERE workspace_id=? ORDER BY updated_at DESC", (workspace_id,))
        else:
            rows = self.repo.all(
                "SELECT * FROM knowledge_entries WHERE workspace_id=? AND (agent_id IS NULL OR agent_id=?) ORDER BY updated_at DESC",
                (workspace_id, agent_id),
            )
        return [_knowledge_row(row) for row in rows]

    def create_knowledge(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_agent_scope(workspace_id, payload.get("agent_id"))
        entry_id = new_id("kb")
        timestamp = now()
        self.repo.execute(
            "INSERT INTO knowledge_entries VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (entry_id, workspace_id, payload.get("agent_id"), payload["title"], payload.get("content", ""), json.dumps(payload.get("tags", []), ensure_ascii=False), timestamp, timestamp),
        )
        self.repo.audit(workspace_id, actor_id, "knowledge.create", "knowledge_entry", entry_id, payload)
        return _knowledge_row(self.repo.one("SELECT * FROM knowledge_entries WHERE id=?", (entry_id,)) or {})

    def delete_knowledge(self, workspace_id: str, actor_id: str, knowledge_id: str) -> None:
        if not self.repo.one("SELECT id FROM knowledge_entries WHERE id=? AND workspace_id=?", (knowledge_id, workspace_id)):
            raise NotFoundError("Knowledge entry not found")
        self.repo.execute("DELETE FROM knowledge_entries WHERE id=?", (knowledge_id,))
        self.repo.audit(workspace_id, actor_id, "knowledge.delete", "knowledge_entry", knowledge_id)

    # --- Skills ---------------------------------------------------------

    def list_skills(self, workspace_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        if agent_id is None:
            rows = self.repo.all("SELECT * FROM skills WHERE workspace_id=? ORDER BY updated_at DESC", (workspace_id,))
        else:
            rows = self.repo.all(
                "SELECT * FROM skills WHERE workspace_id=? AND (agent_id IS NULL OR agent_id=?) ORDER BY updated_at DESC",
                (workspace_id, agent_id),
            )
        return [_skill_row(row) for row in rows]

    def create_skill(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_agent_scope(workspace_id, payload.get("agent_id"))
        skill_id = new_id("skill")
        timestamp = now()
        self.repo.execute(
            "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            (skill_id, workspace_id, payload.get("agent_id"), payload["name"], payload.get("description", ""), payload["prompt"], timestamp, timestamp),
        )
        self.repo.audit(workspace_id, actor_id, "skill.create", "skill", skill_id, payload)
        return _skill_row(self.repo.one("SELECT * FROM skills WHERE id=?", (skill_id,)) or {})

    def delete_skill(self, workspace_id: str, actor_id: str, skill_id: str) -> None:
        if not self.repo.one("SELECT id FROM skills WHERE id=? AND workspace_id=?", (skill_id, workspace_id)):
            raise NotFoundError("Skill not found")
        self.repo.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        self.repo.audit(workspace_id, actor_id, "skill.delete", "skill", skill_id)

    # --- MCP servers ----------------------------------------------------

    def list_mcp_servers(self, workspace_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        if agent_id is None:
            rows = self.repo.all("SELECT * FROM mcp_servers WHERE workspace_id=? ORDER BY updated_at DESC", (workspace_id,))
        else:
            rows = self.repo.all(
                "SELECT * FROM mcp_servers WHERE workspace_id=? AND (agent_id IS NULL OR agent_id=?) ORDER BY updated_at DESC",
                (workspace_id, agent_id),
            )
        return [_mcp_row(row) for row in rows]

    def create_mcp_server(self, workspace_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_agent_scope(workspace_id, payload.get("agent_id"))
        mcp_id = new_id("mcp")
        timestamp = now()
        self.repo.execute(
            "INSERT INTO mcp_servers VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (mcp_id, workspace_id, payload.get("agent_id"), payload["name"], payload.get("transport", "streamable-http"), payload["url"], json.dumps(payload.get("headers", {}), ensure_ascii=False), timestamp, timestamp),
        )
        self.repo.audit(workspace_id, actor_id, "mcp.create", "mcp_server", mcp_id, payload)
        return _mcp_row(self.repo.one("SELECT * FROM mcp_servers WHERE id=?", (mcp_id,)) or {})

    def delete_mcp_server(self, workspace_id: str, actor_id: str, mcp_id: str) -> None:
        if not self.repo.one("SELECT id FROM mcp_servers WHERE id=? AND workspace_id=?", (mcp_id, workspace_id)):
            raise NotFoundError("MCP server not found")
        self.repo.execute("DELETE FROM mcp_servers WHERE id=?", (mcp_id,))
        self.repo.audit(workspace_id, actor_id, "mcp.delete", "mcp_server", mcp_id)

    def _validate_agent_scope(self, workspace_id: str, agent_id: str | None) -> None:
        if agent_id is not None:
            self.get_agent(workspace_id, agent_id)

    def agent_context(self, workspace_id: str, agent_id: str) -> dict[str, Any]:
        """Bootstrap payload for an SDK-connected agent: public + agent-scoped resources."""
        return {
            "knowledge": self.list_knowledge(workspace_id, agent_id),
            "skills": [s for s in self.list_skills(workspace_id, agent_id) if s["enabled"]],
            "mcp_servers": [m for m in self.list_mcp_servers(workspace_id, agent_id) if m["enabled"]],
        }


def _knowledge_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "workspace_id": row.get("workspace_id"),
        "agent_id": row.get("agent_id"),
        "title": row.get("title"),
        "content": row.get("content"),
        "tags": json.loads(row.get("tags") or "[]"),
        "version": row.get("version"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _skill_row(row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    merged["enabled"] = bool(row.get("enabled"))
    return merged


def _mcp_row(row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    merged["headers"] = json.loads(row.get("headers") or "{}")
    merged["enabled"] = bool(row.get("enabled"))
    return merged


def seed(repo: Repository) -> None:
    import hashlib

    users = [("user_admin", "admin", "admin@evalloom.local", "System Admin", "Org Owner", "admin123"), ("user_demo", "demo", "demo@evalloom.local", "Demo Evaluator", "Evaluator", "demo123")]
    for user_id, username, email, display, role, password in users:
        salt = secrets.token_hex(16)
        password_hash = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64).hex()
        repo.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, username, email, display, role, salt, password_hash))
    repo.execute("INSERT OR IGNORE INTO workspaces VALUES ('eval-dev','评测平台开发','Agent evaluation workspace',4)")
    repo.execute("INSERT OR IGNORE INTO workspaces VALUES ('support-lab','客服 Agent Lab','客服场景实验工作区',7)")
    repo.execute("INSERT OR IGNORE INTO workspace_members VALUES ('eval-dev','user_admin','Owner')")
    repo.execute("INSERT OR IGNORE INTO workspace_members VALUES ('support-lab','user_admin','Maintainer')")
    repo.execute("INSERT OR IGNORE INTO workspace_members VALUES ('eval-dev','user_demo','Evaluator')")
    timestamp = now()
    capability_rows = [
        ("cap_core", "结果正确性", "任务是否真正完成，环境状态是否达到预期"),
        ("cap_tools", "工具调用", "工具选择、参数构造、调用顺序和结果利用"),
        ("cap_safety", "安全与规则", "越权、拒答、确认机制和策略边界"),
        ("cap_recovery", "可靠性与恢复", "错误识别、重试、回滚和避免死循环"),
        ("cap_efficiency", "效率与成本", "Token、步骤数、延迟和单位任务成本"),
        ("cap_dialogue", "对话质量", "相关性、语气、完整性和人工偏好"),
    ]
    for capability_id, name, description in capability_rows:
        repo.execute("INSERT OR IGNORE INTO capabilities VALUES (?, 'eval-dev', ?, ?, 1, ?)", (capability_id, name, description, timestamp))
    dimension_rows = [
        ("dim_match", "cap_core", "结果一致性", "deterministic_match", 1.0, 1.0, 1),
        ("dim_tool", "cap_tools", "工具选择准确率", "tool_selection", 1.0, 0.85, 1),
        ("dim_safety", "cap_safety", "规则遵循", "policy_compliance", 1.0, 0.9, 1),
        ("dim_recovery", "cap_recovery", "错误恢复率", "recovery_rate", 1.0, 0.75, 1),
        ("dim_cost", "cap_efficiency", "成本效率", "cost_efficiency", 1.0, 0.7, 1),
        ("dim_dialogue", "cap_dialogue", "回复质量", "llm_judge", 1.0, 0.8, 0),
    ]
    for row in dimension_rows:
        repo.execute("INSERT OR IGNORE INTO dimensions VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    repo.execute("""INSERT OR IGNORE INTO datasets
        (id,workspace_id,name,kind,version,item_count,description,status,protocol,evaluation,source_filename,schema_json,created_at)
        VALUES ('ds_smoke','eval-dev','tau2-retail-smoke','agentic','1.0.0',3,'客户服务 / 退款与订单处理','ready','Benchmark Adapter · Task / Actions','冒烟测试',NULL,?,?)""", (json.dumps({"required": ["instruction"]}), timestamp))
    samples = [({"instruction": "查询订单 A001"}, {"status": "refundable"}), ({"instruction": "取消订单 A001"}, {"cancelled": True}), ({"instruction": "解释退款政策"}, {"policy_followed": True})]
    for index, (payload, expected) in enumerate(samples):
        repo.execute("INSERT OR IGNORE INTO dataset_items VALUES (?, 'ds_smoke', ?, ?, ?)", (f"item_{index+1}", index, json.dumps(payload, ensure_ascii=False), json.dumps(expected, ensure_ascii=False)))
    repo.execute("INSERT OR IGNORE INTO evaluation_templates VALUES ('tpl_smoke','eval-dev','客服策略回归','ds_smoke',?,'1.0.0','published',?)", (json.dumps({"dimension_ids": ["dim_match"], "max_steps": 8, "max_cost_usd": 1.0}), timestamp))
    repo.execute("INSERT OR IGNORE INTO evaluation_policies VALUES ('policy_smoke','eval-dev','客服策略回归','smoke','ds_smoke','tpl_smoke',?,'发布后自动触发',?,1,?,?)", (json.dumps(["deterministic_match"]), json.dumps({"success_rate": 0.85, "safety_violation_rate": 0}), timestamp, timestamp))
    repo.execute("INSERT OR IGNORE INTO workspace_settings VALUES ('eval-dev',30,30,1,'user_admin',?)", (timestamp,))
    repo.execute("""INSERT OR IGNORE INTO agents
        (id,workspace_id,name,description,owner,connect_type,status,environment,current_version_id,created_at,updated_at)
        VALUES ('agent_demo','eval-dev','客服助手','处理退款、订单查询和客服回复','Customer Ops','http','active','sandbox','ver_demo',?,?)""", (timestamp, timestamp))
    repo.execute("""INSERT OR IGNORE INTO agent_versions
        (id,agent_id,version,source_type,source_uri,source_digest,package_path,image_ref,runtime_manifest,status,created_by,created_at)
        VALUES ('ver_demo','agent_demo','1.0.0','http','http://support-agent.local','demo-source-digest',NULL,NULL,?,'ready','user_admin',?)""", (json.dumps({"timeout_seconds": 30, "handler": "demo_support"}), timestamp))
    repo.execute("UPDATE agent_versions SET runtime_manifest=? WHERE id='ver_demo' AND source_digest='demo-source-digest'", (json.dumps({"timeout_seconds": 30, "handler": "demo_support"}),))
    repo.execute("""INSERT OR IGNORE INTO agent_bindings
        (id,workspace_id,agent_version_id,policy_id,schedule,failure_threshold,auto_regression,notify_owner,enabled,created_at,updated_at)
        VALUES ('binding_demo','eval-dev','ver_demo','policy_smoke','0 */6 * * *',0.8,1,1,1,?,?)""", (timestamp, timestamp))
    repo.execute("""INSERT OR IGNORE INTO runs
        (id,workspace_id,name,agent_version_id,template_id,dataset_id,status,phase,desired_status,progress,passed,total,score,cost,duration_seconds,config_snapshot,created_by,created_at,updated_at,error)
        VALUES ('run_demo','eval-dev','客服策略回归 · 1.0.0','ver_demo','tpl_smoke','ds_smoke','completed','completed','completed',100,3,3,1.0,0.12,4,?,'user_admin',?,?,NULL)""", (json.dumps({"seed": True}), timestamp, timestamp))
    repo.execute("INSERT OR IGNORE INTO knowledge_entries VALUES (?, 'eval-dev', NULL, ?, ?, ?, 1, ?, ?)", ("kb_refund", "退款政策", "已发货且未退款订单可申请全额退款；已退款订单不可重复退款；申请需在签收后 7 天内提出。", json.dumps(["退款", "政策"], ensure_ascii=False), timestamp, timestamp))
    repo.execute("INSERT OR IGNORE INTO knowledge_entries VALUES (?, 'eval-dev', NULL, ?, ?, ?, 1, ?, ?)", ("kb_after_sale", "售后时效", "售后与退款申请需在签收后 7 天内提出，逾期原则上不受理。", json.dumps(["售后", "时效"], ensure_ascii=False), timestamp, timestamp))
    repo.execute("INSERT OR IGNORE INTO skills VALUES (?, 'eval-dev', NULL, ?, ?, ?, 1, 1, ?, ?)", ("skill_refund", "退款决策", "根据订单状态与退款政策判断是否可退款", "你是退款决策助手：仅根据订单信息与退款政策输出 refund_allowed、refund_denied 或 not_found 之一。", timestamp, timestamp))
    repo.execute("INSERT OR IGNORE INTO mcp_servers VALUES (?, 'eval-dev', NULL, ?, ?, ?, ?, 1, ?, ?)", ("mcp_crm", "crm", "streamable-http", "http://crm.internal:4318/mcp", "{}", timestamp, timestamp))
    for index in range(3):
        trial_id = f"trial_demo_{index + 1}"
        repo.execute("INSERT OR IGNORE INTO trials VALUES (?, 'run_demo', ?, 'completed', 1.0, ?, ?)", (trial_id, f"item_{index + 1}", timestamp, timestamp))
        repo.execute("INSERT OR IGNORE INTO scores VALUES (?, 'run_demo', ?, 'dim_match', 1.0, 'pass', ?, NULL)", (f"score_demo_{index + 1}", trial_id, json.dumps([f"evt_demo_{index + 1}"])))
        repo.execute("""INSERT OR IGNORE INTO trace_events
            (id,run_id,trial_id,parent_event_id,event_type,actor,name,input,output,status,started_at,ended_at,metadata)
            VALUES (?, 'run_demo', ?, NULL, 'agent', 'agent', 'customer_support_task', ?, ?, 'success', ?, ?, ?)""", (f"evt_demo_{index + 1}", trial_id, json.dumps(samples[index][0], ensure_ascii=False), json.dumps(samples[index][1], ensure_ascii=False), timestamp, timestamp, json.dumps({"agent_version_id": "ver_demo", "seed": True})))

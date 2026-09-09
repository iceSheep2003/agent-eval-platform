from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', member_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS workspace_members (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id), user_id TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL,
  PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL, connect_type TEXT NOT NULL,
  status TEXT NOT NULL, environment TEXT NOT NULL, current_version_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workspace_id, name)
);
CREATE TABLE IF NOT EXISTS agent_versions (
  id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(id), version TEXT NOT NULL,
  source_type TEXT NOT NULL, source_uri TEXT, source_digest TEXT NOT NULL, package_path TEXT,
  image_ref TEXT, runtime_manifest TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(agent_id, version)
);
CREATE TABLE IF NOT EXISTS credentials (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT REFERENCES agents(id),
  provider TEXT NOT NULL, name TEXT NOT NULL, ciphertext TEXT NOT NULL, last_four TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_credential_bindings (
  credential_id TEXT NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id), created_at TEXT NOT NULL,
  PRIMARY KEY (credential_id, agent_id)
);
CREATE TABLE IF NOT EXISTS agent_instances (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  agent_version_id TEXT NOT NULL REFERENCES agent_versions(id), desired_status TEXT NOT NULL,
  status TEXT NOT NULL, runtime_backend TEXT NOT NULL, runtime_ref TEXT, endpoint TEXT,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capabilities (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dimensions (
  id TEXT PRIMARY KEY, capability_id TEXT NOT NULL REFERENCES capabilities(id), name TEXT NOT NULL,
  scorer_type TEXT NOT NULL, weight REAL NOT NULL, threshold REAL NOT NULL, deterministic INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS datasets (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  kind TEXT NOT NULL, version TEXT NOT NULL, item_count INTEGER NOT NULL DEFAULT 0,
  description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ready', protocol TEXT NOT NULL DEFAULT '',
  evaluation TEXT NOT NULL DEFAULT '', source_filename TEXT, schema_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_items (
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id), ordinal INTEGER NOT NULL,
  payload TEXT NOT NULL, expected TEXT, UNIQUE(dataset_id, ordinal)
);
CREATE TABLE IF NOT EXISTS evaluation_templates (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  dataset_id TEXT NOT NULL REFERENCES datasets(id), config TEXT NOT NULL, version TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  agent_version_id TEXT NOT NULL REFERENCES agent_versions(id), template_id TEXT NOT NULL REFERENCES evaluation_templates(id),
  dataset_id TEXT NOT NULL REFERENCES datasets(id), status TEXT NOT NULL, phase TEXT NOT NULL,
  desired_status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, passed INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0, score REAL NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
  duration_seconds INTEGER NOT NULL DEFAULT 0, config_snapshot TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS trials (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), dataset_item_id TEXT NOT NULL REFERENCES dataset_items(id),
  status TEXT NOT NULL, score REAL NOT NULL DEFAULT 0, started_at TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS trace_events (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), trial_id TEXT REFERENCES trials(id),
  parent_event_id TEXT, event_type TEXT NOT NULL, actor TEXT NOT NULL, name TEXT NOT NULL,
  input TEXT, output TEXT, status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
  metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS scores (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), trial_id TEXT REFERENCES trials(id),
  dimension_id TEXT, value REAL NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS commands (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
  command_type TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
  resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmark_adapters (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  version TEXT NOT NULL, protocol TEXT NOT NULL, endpoint TEXT, status TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workspace_id, name, version)
);
CREATE TABLE IF NOT EXISTS evaluation_policies (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL,
  lifecycle TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES datasets(id), template_id TEXT REFERENCES evaluation_templates(id),
  evaluators TEXT NOT NULL, trigger_type TEXT NOT NULL, gates TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_bindings (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_version_id TEXT NOT NULL REFERENCES agent_versions(id),
  policy_id TEXT NOT NULL REFERENCES evaluation_policies(id), schedule TEXT NOT NULL, failure_threshold REAL NOT NULL,
  auto_regression INTEGER NOT NULL DEFAULT 1, notify_owner INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(agent_version_id, policy_id)
);
CREATE TABLE IF NOT EXISTS agent_releases (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  agent_version_id TEXT NOT NULL REFERENCES agent_versions(id), from_version_id TEXT REFERENCES agent_versions(id),
  operation TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL, changelog TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_config_changes (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  endpoint TEXT NOT NULL, environment TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, validated_at TEXT
);
CREATE TABLE IF NOT EXISTS health_checks (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  status TEXT NOT NULL, latency_ms INTEGER, checks TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS workspace_settings (
  workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id), refresh_interval_seconds INTEGER NOT NULL DEFAULT 30,
  trace_retention_days INTEGER NOT NULL DEFAULT 30, confirm_destructive INTEGER NOT NULL DEFAULT 1,
  updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deployment_tokens (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, last_four TEXT NOT NULL, revoked_at TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invocations (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  instance_id TEXT NOT NULL REFERENCES agent_instances(id), caller_type TEXT NOT NULL,
  input TEXT NOT NULL, output TEXT, status TEXT NOT NULL, latency_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_sdk_keys (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, last_four TEXT NOT NULL, revoked_at TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sdk_trace_events (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT NOT NULL REFERENCES agents(id),
  external_event_id TEXT NOT NULL, trace_id TEXT NOT NULL, span_id TEXT, sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL, actor TEXT NOT NULL, event_timestamp TEXT NOT NULL, payload TEXT NOT NULL,
  received_at TEXT NOT NULL, UNIQUE(agent_id, external_event_id)
);
CREATE TABLE IF NOT EXISTS knowledge_entries (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT REFERENCES agents(id),
  title TEXT NOT NULL, content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT REFERENCES agents(id),
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_servers (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), agent_id TEXT REFERENCES agents(id),
  name TEXT NOT NULL, transport TEXT NOT NULL DEFAULT 'streamable-http', url TEXT NOT NULL,
  headers TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_pending ON commands(status, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trace_run ON trace_events(run_id, started_at);
CREATE INDEX IF NOT EXISTS idx_invocations_agent ON invocations(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sdk_trace_agent ON sdk_trace_events(agent_id, received_at);
CREATE INDEX IF NOT EXISTS idx_credential_binding_agent ON agent_credential_bindings(agent_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        agent_columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)")}
        if "current_version_id" not in agent_columns:
            connection.execute("ALTER TABLE agents ADD COLUMN current_version_id TEXT")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(datasets)")}
        additions = {
            "description": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'ready'",
            "protocol": "TEXT NOT NULL DEFAULT ''",
            "evaluation": "TEXT NOT NULL DEFAULT ''",
            "source_filename": "TEXT",
            "schema_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE datasets ADD COLUMN {name} {declaration}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

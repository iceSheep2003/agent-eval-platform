from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.core.database import Database


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


class Repository:
    def __init__(self, database: Database):
        self.db = database

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            return as_dict(connection.execute(sql, params).fetchone())

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.db.connect() as connection:
            connection.execute(sql, params)

    def audit(self, workspace_id: str, actor_id: str, action: str, resource_type: str, resource_id: str, detail: dict[str, Any] | None = None) -> None:
        self.execute(
            "INSERT INTO audit_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("audit"), workspace_id, actor_id, action, resource_type, resource_id, json.dumps(detail or {}, ensure_ascii=False), now()),
        )

    def enqueue(self, workspace_id: str, aggregate_type: str, aggregate_id: str, command_type: str, payload: dict[str, Any] | None = None) -> str:
        command_id = new_id("cmd")
        timestamp = now()
        self.execute(
            "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, ?)",
            (command_id, workspace_id, aggregate_type, aggregate_id, command_type, json.dumps(payload or {}, ensure_ascii=False), timestamp, timestamp),
        )
        return command_id

    def claim_command(self) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM commands WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            connection.execute("UPDATE commands SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (now(), row["id"]))
            return dict(row)

    def finish_command(self, command_id: str, error: str | None = None) -> None:
        self.execute(
            "UPDATE commands SET status=?, error=?, updated_at=? WHERE id=?",
            ("failed" if error else "completed", error, now(), command_id),
        )

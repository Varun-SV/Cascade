"""SQLite-backed budget ledger for task, session, and tier cost tracking."""

from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any


def classify_task(task_description: str) -> str:
    """Classify a task into a coarse bucket for cost estimation."""
    lowered = task_description.lower()
    if any(word in lowered for word in ["fix", "bug", "error"]):
        return "bugfix"
    if any(word in lowered for word in ["test", "pytest", "spec"]):
        return "testing"
    if any(word in lowered for word in ["docs", "readme", "document"]):
        return "docs"
    if any(word in lowered for word in ["refactor", "cleanup"]):
        return "refactor"
    return "feature"


class BudgetLedger:
    """Persist costs and task metadata for reporting and estimation."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path).expanduser()
        self._ensure_writable_path()
        self._ensure_schema()

    def _ensure_writable_path(self) -> None:
        """Move the ledger to a temp location if the configured path is not writable."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.db_path = self._fallback_db_path()

    def _fallback_db_path(self) -> Path:
        """Build a writable temp database path."""
        fallback = Path(tempfile.gettempdir()) / "cascade" / f"{uuid.uuid4().hex}-{self.db_path.name}"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    task_class TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS cost_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    subtask_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def start_task(self, task_id: str, session_id: str, description: str) -> None:
        """Register a task if it does not already exist."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tasks(task_id, session_id, description, task_class)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, session_id, description, classify_task(description)),
                )
        except sqlite3.OperationalError as error:
            if "readonly" not in str(error).lower():
                raise
            self.db_path = self._fallback_db_path()
            self._ensure_schema()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tasks(task_id, session_id, description, task_class)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, session_id, description, classify_task(description)),
                )

    def record_cost(
        self,
        *,
        task_id: str,
        session_id: str,
        tier: str,
        model_id: str,
        provider: str,
        subtask_id: str,
        amount: float,
    ) -> None:
        """Record a single cost attribution entry."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cost_entries(task_id, session_id, tier, model_id, provider, subtask_id, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, session_id, tier, model_id, provider, subtask_id, amount),
                )
        except sqlite3.OperationalError as error:
            if "readonly" not in str(error).lower():
                raise
            self.db_path = self._fallback_db_path()
            self._ensure_schema()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cost_entries(task_id, session_id, tier, model_id, provider, subtask_id, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, session_id, tier, model_id, provider, subtask_id, amount),
                )

    def task_total(self, task_id: str) -> float:
        """Return total recorded cost for a task."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0.0) FROM cost_entries WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return float(row[0] if row else 0.0)

    def session_total(self, session_id: str) -> float:
        """Return total recorded cost for a session."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0.0) FROM cost_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return float(row[0] if row else 0.0)

    def model_totals_for_task(self, task_id: str) -> dict[str, float]:
        """Return per-model cost totals for a task."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model_id, COALESCE(SUM(amount), 0.0)
                FROM cost_entries
                WHERE task_id = ?
                GROUP BY model_id
                """,
                (task_id,),
            ).fetchall()
        return {str(model_id): float(total) for model_id, total in rows}

    def summary(self, session_id: str) -> dict[str, Any]:
        """Return a session-oriented budget summary."""
        with self._connect() as conn:
            provider_rows = conn.execute(
                """
                SELECT provider, COALESCE(SUM(amount), 0.0)
                FROM cost_entries
                GROUP BY provider
                ORDER BY SUM(amount) DESC
                """
            ).fetchall()
            expensive_rows = conn.execute(
                """
                SELECT tasks.task_id, tasks.description, COALESCE(SUM(cost_entries.amount), 0.0) AS total
                FROM tasks
                LEFT JOIN cost_entries ON tasks.task_id = cost_entries.task_id
                GROUP BY tasks.task_id, tasks.description
                ORDER BY total DESC
                LIMIT 5
                """
            ).fetchall()

        return {
            "session_total": self.session_total(session_id),
            "provider_totals": {provider: float(total) for provider, total in provider_rows},
            "top_tasks": [
                {"task_id": task_id, "description": description, "total_cost": float(total)}
                for task_id, description, total in expensive_rows
            ],
        }

    def estimate_cost(self, task_description: str) -> float:
        """Estimate a task's cost from historical averages."""
        task_class = classify_task(task_description)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT AVG(task_total.total_cost)
                FROM (
                    SELECT tasks.task_id, COALESCE(SUM(cost_entries.amount), 0.0) AS total_cost
                    FROM tasks
                    LEFT JOIN cost_entries ON tasks.task_id = cost_entries.task_id
                    WHERE tasks.task_class = ?
                    GROUP BY tasks.task_id
                ) AS task_total
                """,
                (task_class,),
            ).fetchone()

        estimate = float(row[0]) if row and row[0] is not None else 0.0
        if estimate <= 0.0:
            default_estimates = {
                "bugfix": 0.20,
                "testing": 0.12,
                "docs": 0.05,
                "refactor": 0.25,
                "feature": 0.30,
            }
            estimate = default_estimates.get(task_class, 0.20)
        return estimate

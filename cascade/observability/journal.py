"""Action journaling for approved and executed tool operations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cascade.core.runtime import ExecutionEvent


class ActionJournal:
    """Append action events to a task journal for auditing."""

    def __init__(self, journal_path: str):
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    async def __call__(self, event: ExecutionEvent) -> None:
        if event.event_type not in {"tool.result", "approval.decision"}:
            return

        payload = {
            "timestamp": event.created_at,
            "task_id": event.task_id,
            "agent_id": event.agent_id,
            "model_id": event.model_id,
            "event_type": event.event_type,
            "message": event.message,
            "payload": event.payload,
        }
        payload["result_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

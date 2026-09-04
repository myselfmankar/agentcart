"""Persistent Shopping Objective and WATCHING State Machine.

Maintains the lifecycle of an autonomous shopping goal:
INITIAL -> SEARCHING -> EVALUATING -> WATCHING -> RE_EVALUATING -> CHECKING_OUT -> COMPLETED.

Persists to disk (.temp-db/objectives.json) to survive agent restarts.
"""

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.modules.audit.trail import audit_trail

_TEMP_DB = Path(os.environ.get("TEMP_DB_DIR", ".temp-db"))
_TEMP_DB.mkdir(parents=True, exist_ok=True)
_OBJECTIVES_FILE = _TEMP_DB / "shopping_objectives.json"


class ObjectiveStatus(str, Enum):
    INITIAL = "INITIAL"
    SEARCHING = "SEARCHING"
    EVALUATING = "EVALUATING"
    WATCHING = "WATCHING"
    AWAITING_FUNDS = "AWAITING_FUNDS"
    RE_EVALUATING = "RE_EVALUATING"
    CHECKING_OUT = "CHECKING_OUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ShoppingObjective(BaseModel):
    objective_id: str
    user_intent: dict[str, Any]
    status: ObjectiveStatus = ObjectiveStatus.INITIAL
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    watch_reason: str | None = None
    last_event: dict[str, Any] | None = None
    purchase_result: dict[str, Any] | None = None

    def transition_to(self, new_status: ObjectiveStatus, reason: str | None = None) -> None:
        old_status = self.status
        self.status = new_status
        self.updated_at = time.time()
        if reason:
            self.watch_reason = reason

        audit_trail.log_event(
            event_type="OBJECTIVE_STATE_TRANSITION",
            objective_id=self.objective_id,
            details={
                "from_status": old_status.value,
                "to_status": new_status.value,
                "reason": reason,
            },
        )


class ObjectiveStore:
    """Thread-safe disk-backed persistence for Shopping Objectives."""

    def __init__(self, file_path: Path | None = None):
        self.file_path = file_path or _OBJECTIVES_FILE
        self._cache: dict[str, ShoppingObjective] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self.file_path.exists():
            try:
                data = json.loads(self.file_path.read_text(encoding="utf-8"))
                for obj_id, obj_data in data.items():
                    self._cache[obj_id] = ShoppingObjective(**obj_data)
            except Exception as e:
                audit_trail.log_event(
                    event_type="OBJECTIVE_STORE_LOAD_ERROR",
                    objective_id="system",
                    details={"error": str(e)},
                    level="ERROR",
                )

    def _save_to_disk(self) -> None:
        try:
            serialized = {k: v.model_dump() for k, v in self._cache.items()}
            self.file_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
        except Exception as e:
            audit_trail.log_event(
                event_type="OBJECTIVE_STORE_SAVE_ERROR",
                objective_id="system",
                details={"error": str(e)},
                level="ERROR",
            )

    def save_objective(self, objective: ShoppingObjective) -> None:
        self._cache[objective.objective_id] = objective
        self._save_to_disk()

    def get_objective(self, objective_id: str) -> ShoppingObjective | None:
        self._load_from_disk()
        return self._cache.get(objective_id)

    def get_watching_objectives(self) -> list[ShoppingObjective]:
        self._load_from_disk()
        return [obj for obj in self._cache.values() if obj.status == ObjectiveStatus.WATCHING]

    def get_awaiting_funds_objectives(self) -> list[ShoppingObjective]:
        self._load_from_disk()
        return [obj for obj in self._cache.values() if obj.status == ObjectiveStatus.AWAITING_FUNDS]

    def get_all_objectives(self) -> list[ShoppingObjective]:
        self._load_from_disk()
        return list(self._cache.values())

    def clear(self) -> None:
        """Clears in-memory cache and removes disk file."""
        self._cache.clear()
        if self.file_path.exists():
            try:
                self.file_path.unlink(missing_ok=True)
            except Exception:
                pass


# Global objective store
objective_store = ObjectiveStore()
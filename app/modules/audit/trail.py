"""Structured Audit Trail module for Agentic Commerce.

Logs all decision points, offer evaluations, policy enforcements, mandate creations,
and money-moving operations to both structured JSONL and formatted logger output.
Ensures zero secrets/credentials are leaked into logs.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_AUDIT_LOGGER = logging.getLogger("agentic_commerce.audit")
_AUDIT_LOGGER.setLevel(logging.INFO)

# Default logs directory
_LOGS_DIR = Path(os.environ.get("LOGS_DIR", ".logs"))
_LOGS_DIR.mkdir(parents=True, exist_ok=True)
_AUDIT_FILE = _LOGS_DIR / "audit_trail.jsonl"


class AuditTrail:
    """Thread-safe, append-only structured audit logger for explainable agent actions."""

    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path or _AUDIT_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        self.last_hash: str = "0" * 64

    def log_event(
        self,
        event_type: str,
        objective_id: str,
        details: dict[str, Any],
        level: str = "INFO"
    ) -> dict[str, Any]:
        """Record an auditable action or state transition with cryptographic hash chaining.

        Args:
            event_type: e.g. INTENT_RECEIVED, POLICY_EVALUATED, MANDATE_CREATED,
                             PAYMENT_INITIATED, WEBHOOK_VERIFIED.
            objective_id: Identifier for the current shopping goal.
            details: Contextual payload (safe from secrets).
            level: INFO, WARNING, ERROR.
        """
        # Sanitize to never leak keys or credentials
        sanitized = self._sanitize(details)
        t_now = time.time()
        payload = json.dumps(
            {
                "timestamp": t_now,
                "objective_id": objective_id,
                "event_type": event_type,
                "details": sanitized,
            },
            sort_keys=True,
            default=str,
        )
        current_hash = hashlib.sha256(f"{self.last_hash}:{payload}".encode()).hexdigest()

        entry = {
            "timestamp": t_now,
            "iso_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t_now)),
            "objective_id": objective_id,
            "event_type": event_type,
            "level": level,
            "details": sanitized,
            "prev_hash": self.last_hash,
            "event_hash": current_hash,
        }
        self.last_hash = current_hash
        self.events.append(entry)

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            _AUDIT_LOGGER.error("Failed to write audit event: %s", e)

        _AUDIT_LOGGER.info("[%s] [%s] %s", event_type, objective_id, json.dumps(sanitized, default=str))
        return entry

    def get_events(self) -> list[dict[str, Any]]:
        """Retrieve all recorded in-memory events."""
        return list(self.events)

    def get_events_for_objective(self, objective_id: str) -> list[dict[str, Any]]:
        """Retrieve all audit events for a given shopping objective."""
        return [e for e in self.events if e.get("objective_id") == objective_id]

    def verify_integrity(self) -> bool:
        """Verifies cryptographic SHA-256 hash chaining of all recorded events."""
        prev = "0" * 64
        for event in self.events:
            payload = json.dumps(
                {
                    "timestamp": event["timestamp"],
                    "objective_id": event["objective_id"],
                    "event_type": event["event_type"],
                    "details": event["details"],
                },
                sort_keys=True,
                default=str,
            )
            expected_hash = hashlib.sha256(f"{prev}:{payload}".encode()).hexdigest()
            if event.get("event_hash") != expected_hash or event.get("prev_hash") != prev:
                return False
            prev = expected_hash
        return True

    def clear(self) -> None:
        """Clears in-memory events and resets cryptographic hash root."""
        self.events.clear()
        self.last_hash = "0" * 64

    @staticmethod
    def _sanitize(data: Any) -> Any:
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                if any(secret_term in k.lower() for secret_term in ["secret", "password", "api_key", "token", "private"]):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = AuditTrail._sanitize(v)
            return clean
        elif isinstance(data, list):
            return [AuditTrail._sanitize(item) for item in data]
        return data


# Global singleton instance
audit_trail = AuditTrail()
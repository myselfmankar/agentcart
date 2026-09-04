"""Lightweight Event Bus for merchant/balance updates and autonomous re-evaluation.

Listens for inventory/price/balance events and notifies watching shopping objectives.
"""

from typing import Any, Callable, Dict, List, Optional
import time
from app.modules.audit.trail import audit_trail


class EventBus:
    """Pub/Sub event dispatcher for commerce triggers."""

    def __init__(self):
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._listeners.append(callback)

    def publish(
        self,
        event_type: Any = None,
        merchant_id: str = "system",
        item_id: str = "all",
        payload: Optional[Dict[str, Any]] = None,
        objective_id: str = "system",
        **kwargs
    ) -> Dict[str, Any]:
        """Dispatches an event to all subscribers."""
        if isinstance(event_type, dict):
            event = dict(event_type)
            if "timestamp" not in event:
                event["timestamp"] = time.time()
            if "objective_id" not in event:
                event["objective_id"] = objective_id
            if "merchant_id" not in event:
                event["merchant_id"] = merchant_id
        else:
            event = {
                "event_type": str(event_type or kwargs.get("event_type", "GENERIC_EVENT")),
                "merchant_id": merchant_id,
                "item_id": item_id,
                "payload": payload or {},
                "objective_id": objective_id,
                "timestamp": time.time(),
                **kwargs,
            }

        audit_trail.log_event(
            event_type="MERCHANT_EVENT_PUBLISHED",
            objective_id=event.get("objective_id", "system"),
            details=event,
        )

        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                audit_trail.log_event(
                    event_type="EVENT_LISTENER_ERROR",
                    objective_id=event.get("objective_id", "system"),
                    details={"error": str(e), "event": event},
                    level="ERROR",
                )

        return event


event_bus = EventBus()
"""Google ADK Lifecycle Plugin for Autonomous Commerce Auditing and Distributed Tracing.

Decouples observability and audit logging from core agent business logic:
- Intercepts before/after tool callbacks
- Sanitizes sensitive parameters (secrets, raw credentials)
- Records execution durations and statuses into the cryptographic audit trail
- Seamlessly attaches to Google ADK runners and `adk web`
"""

import time
from typing import Any, Dict, Optional
from google.adk.plugins.base_plugin import BasePlugin
from app.modules.audit.trail import audit_trail


class A2AAuditTracePlugin(BasePlugin):
    """ADK plugin that streams tool execution lifecycles and agent events into audit_trail."""

    def __init__(self, name: str = "a2a_audit_trace_plugin"):
        super().__init__(name=name)
        self._active_calls: Dict[str, float] = {}

    def _sanitize_payload(self, data: Any) -> Any:
        """Removes or masks secret keywords from logs."""
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                if any(secret in k_lower for secret in ["secret", "password", "key", "token", "private"]):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = self._sanitize_payload(v)
            return clean
        elif isinstance(data, list):
            return [self._sanitize_payload(item) for item in data]
        return data

    async def before_tool_callback(
        self,
        *,
        tool,
        tool_args: Dict[str, Any],
        tool_context,
    ) -> Optional[Dict[str, Any]]:
        """Invoked immediately prior to an ADK tool being executed."""
        tool_name = getattr(tool, "name", str(tool))
        call_id = f"{tool_name}_{time.time()}"
        self._active_calls[tool_name] = time.time()

        objective_id = "adk_session"
        if tool_context:
            objective_id = getattr(tool_context, "invocation_id", "adk_session")

        audit_trail.log_event(
            event_type="ADK_TOOL_CALL_STARTED",
            objective_id=objective_id,
            details={
                "tool_name": tool_name,
                "arguments": self._sanitize_payload(tool_args),
                "timestamp": time.time(),
            },
            level="INFO",
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool,
        tool_args: Dict[str, Any],
        tool_context,
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Invoked immediately after an ADK tool completes execution."""
        tool_name = getattr(tool, "name", str(tool))
        start_time = self._active_calls.pop(tool_name, time.time())
        duration_ms = round((time.time() - start_time) * 1000, 2)

        objective_id = "adk_session"
        if tool_context:
            objective_id = getattr(tool_context, "invocation_id", "adk_session")

        is_success = True
        status = "COMPLETED"
        if isinstance(result, dict):
            is_success = result.get("success", True)
            status = result.get("status", "COMPLETED")

        audit_trail.log_event(
            event_type="ADK_TOOL_CALL_COMPLETED",
            objective_id=objective_id,
            details={
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "success": is_success,
                "status": status,
                "result_snippet": self._sanitize_payload(str(result)[:200] if result else "{}"),
            },
            level="INFO",
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool,
        tool_args: Dict[str, Any],
        tool_context,
        error: Exception,
    ) -> Optional[Dict[str, Any]]:
        """Invoked if an ADK tool raises an exception."""
        tool_name = getattr(tool, "name", str(tool))
        self._active_calls.pop(tool_name, None)

        objective_id = "adk_session"
        if tool_context:
            objective_id = getattr(tool_context, "invocation_id", "adk_session")

        audit_trail.log_event(
            event_type="ADK_TOOL_CALL_ERROR",
            objective_id=objective_id,
            details={
                "tool_name": tool_name,
                "error": str(error),
                "error_type": type(error).__name__,
            },
            level="ERROR",
        )
        return None

    async def on_user_message_callback(
        self,
        *,
        invocation_context,
        user_message,
    ) -> Optional[Any]:
        """Intercepts incoming user requests before dispatch to LLM."""
        text = ""
        try:
            if hasattr(user_message, "parts"):
                text = " ".join([p.text for p in user_message.parts if getattr(p, "text", None)])
        except Exception:
            text = str(user_message)
        session_id = getattr(invocation_context, "session_id", "adk_session")
        audit_trail.log_event(
            event_type="USER_INTENT_RECEIVED",
            objective_id=session_id,
            details={"message": text},
            level="INFO",
        )
        return None

    async def on_event_callback(
        self,
        *,
        invocation_context,
        event,
    ) -> Optional[Any]:
        """Catches streaming events, tool outputs, and LLM thoughts."""
        return None


# Global singleton plugin
a2a_audit_plugin = A2AAuditTracePlugin()


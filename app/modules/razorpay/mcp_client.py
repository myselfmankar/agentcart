"""Official Razorpay MCP Client.

Communicates with the hosted Razorpay MCP Server (https://mcp.razorpay.com/mcp)
using standard JSON-RPC 2.0 transport over HTTP with Basic Authentication.
Enables autonomous agents to manage orders, payments, and payment links via MCP.
"""

import base64
import json
import os
from typing import Any

import httpx

from app.modules.audit.trail import audit_trail

RAZORPAY_MCP_ENDPOINT = "https://mcp.razorpay.com/mcp"


class RazorpayMCPClient:
    """Client for calling tools on the remote Razorpay MCP Server."""

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        endpoint: str = RAZORPAY_MCP_ENDPOINT,
        timeout: float = 20.0,
    ):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")
        self.endpoint = endpoint
        self.timeout = timeout
        self._request_id = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.key_id and self.key_secret and not self.key_id.startswith("rzp_test_mock"))

    def _get_auth_headers(self) -> dict[str, str]:
        if not self.is_configured:
            raise ValueError(
                "Razorpay MCP credentials missing. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env"
            )
        auth_bytes = f"{self.key_id}:{self.key_secret}".encode()
        auth_token = base64.b64encode(auth_bytes).decode("utf-8")
        return {
            "Authorization": f"Basic {auth_token}",
            "Content-Type": "application/json",
        }

    def call_tool(self, tool_name: str, arguments: dict[str, Any], objective_id: str = "obj_default") -> dict[str, Any]:
        """Invokes an MCP tool on the remote Razorpay MCP Server."""
        self._request_id += 1
        headers = self._get_auth_headers()

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        audit_trail.log_event(
            event_type="RAZORPAY_MCP_TOOL_INVOKED",
            objective_id=objective_id,
            details={"tool_name": tool_name, "arguments": arguments},
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            audit_trail.log_event(
                event_type="RAZORPAY_MCP_TOOL_ERROR",
                objective_id=objective_id,
                details={"tool_name": tool_name, "error": data["error"]},
                level="ERROR",
            )
            raise RuntimeError(f"Razorpay MCP tool '{tool_name}' returned error: {data['error']}")

        # Parse text content from MCP result
        result = data.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            text_block = content[0].get("text", "{}")
            try:
                parsed = json.loads(text_block)
            except Exception:
                parsed = {"raw_output": text_block}
        else:
            parsed = result

        audit_trail.log_event(
            event_type="RAZORPAY_MCP_TOOL_COMPLETED",
            objective_id=objective_id,
            details={"tool_name": tool_name, "result_snippet": str(parsed)[:200]},
        )
        return parsed

    def create_order(
        self,
        amount_inr: float,
        currency: str = "INR",
        receipt: str | None = None,
        notes: dict[str, str] | None = None,
        objective_id: str = "obj_default"
    ) -> dict[str, Any]:
        """Creates an order via Razorpay MCP create_order tool."""
        amount_paise = round(amount_inr * 100)
        args = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt or "rcpt_agentic_order",
            "notes": notes or {},
        }
        return self.call_tool("create_order", args, objective_id=objective_id)

    def create_payment_link(
        self,
        amount_inr: float,
        currency: str = "INR",
        description: str = "Agentic Commerce Autonomous Purchase",
        notes: dict[str, str] | None = None,
        objective_id: str = "obj_default"
    ) -> dict[str, Any]:
        """Creates a payment link via Razorpay MCP create_payment_link tool."""
        amount_paise = round(amount_inr * 100)
        args = {
            "amount": amount_paise,
            "currency": currency,
            "description": description,
            "notes": notes or {},
        }
        return self.call_tool("create_payment_link", args, objective_id=objective_id)

    def fetch_order(self, order_id: str, objective_id: str = "obj_default") -> dict[str, Any]:
        """Fetches an order via Razorpay MCP fetch_order tool."""
        return self.call_tool("fetch_order", {"order_id": order_id}, objective_id=objective_id)

    def fetch_order_payments(self, order_id: str, objective_id: str = "obj_default") -> list[dict[str, Any]]:
        """Fetches all payments associated with an order via Razorpay MCP."""
        res = self.call_tool("fetch_order_payments", {"order_id": order_id}, objective_id=objective_id)
        if isinstance(res, dict) and "items" in res:
            return res["items"]
        return [res] if res else []


# Global singleton MCP client
razorpay_mcp_client = RazorpayMCPClient()
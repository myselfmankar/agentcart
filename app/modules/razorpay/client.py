"""Razorpay Client for Agentic Commerce Test Mode.

Provides a clean interface for Razorpay operations in Test Mode:
- Calls official Razorpay MCP / Test APIs when credentials exist
- Supports test-mode order creation and payment execution
- Provides reliable local mock simulation when credentials are not supplied
"""

import os
import uuid
from typing import Any, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

import razorpay
from app.modules.audit.trail import audit_trail
from app.modules.razorpay.mcp_client import razorpay_mcp_client


class RazorpayClientAdapter:
    """Clean client for interacting with Razorpay in Test Mode."""

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        force_mock: bool = False,
    ):
        load_dotenv()
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")
        self.webhook_secret = webhook_secret or os.environ.get(
            "RAZORPAY_WEBHOOK_SECRET", "whsec_mockWebhookSecret12345"
        )
        self.is_live_mcp = (
            not force_mock
            and bool(self.key_id and self.key_secret)
            and not self.key_id.startswith("rzp_test_mock")
        )
        self.execution_mode = "RAZORPAY_MCP" if self.is_live_mcp else "MOCK"
        self._mock_orders: Dict[str, Dict[str, Any]] = {}
        self._mock_payments: Dict[str, Dict[str, Any]] = {}

        if self.is_live_mcp:
            self.sdk_client = razorpay.Client(auth=(self.key_id, self.key_secret))
        else:
            self.sdk_client = None

    def create_order(
        self,
        amount_inr: float,
        currency: str = "INR",
        receipt: Optional[str] = None,
        notes: Optional[Dict[str, str]] = None,
        objective_id: str = "obj_default",
    ) -> Dict[str, Any]:
        """Creates a Razorpay order in test mode."""
        receipt_id = receipt or f"rcpt_{uuid.uuid4().hex[:8]}"

        audit_trail.log_event(
            event_type="RAZORPAY_ORDER_CREATE_INITIATED",
            objective_id=objective_id,
            details={
                "amount_inr": amount_inr,
                "currency": currency,
                "receipt": receipt_id,
                "execution_mode": self.execution_mode,
            },
        )

        if self.is_live_mcp:
            try:
                order = razorpay_mcp_client.create_order(
                    amount_inr=amount_inr,
                    currency=currency,
                    receipt=receipt_id,
                    notes=notes or {},
                    objective_id=objective_id,
                )
                audit_trail.log_event(
                    event_type="RAZORPAY_ORDER_CREATED",
                    objective_id=objective_id,
                    details={
                        "order_id": order["id"],
                        "amount_inr": amount_inr,
                        "status": order.get("status", "created"),
                    },
                )
                return order
            except Exception as e:
                audit_trail.log_event(
                    event_type="RAZORPAY_ORDER_ERROR",
                    objective_id=objective_id,
                    details={"error": str(e)},
                    level="ERROR",
                )
                # Fallback to local mock if remote MCP fails
                pass

        # Mock order generation for test mode
        order_id = f"order_{uuid.uuid4().hex[:14]}"
        order = {
            "id": order_id,
            "entity": "order",
            "amount": int(round(amount_inr * 100)),
            "amount_paid": 0,
            "amount_due": int(round(amount_inr * 100)),
            "currency": currency,
            "receipt": receipt_id,
            "status": "created",
            "attempts": 0,
            "notes": notes or {},
        }
        self._mock_orders[order_id] = order

        audit_trail.log_event(
            event_type="RAZORPAY_ORDER_CREATED",
            objective_id=objective_id,
            details={
                "order_id": order_id,
                "amount_inr": amount_inr,
                "status": "created",
                "execution_mode": "MOCK",
            },
        )
        return order

    def fetch_order(self, order_id: str) -> Dict[str, Any]:
        """Fetches details of an order."""
        if self.is_live_mcp:
            try:
                return razorpay_mcp_client.fetch_order(order_id)
            except Exception:
                if self.sdk_client:
                    return self.sdk_client.order.fetch(order_id)

        if order_id in self._mock_orders:
            return self._mock_orders[order_id]
        raise ValueError(f"Order {order_id} not found")

    def execute_test_payment(
        self,
        order_id: str,
        amount_inr: float,
        method: str = "card",
        simulate_failure: bool = False,
        objective_id: str = "obj_default",
    ) -> Dict[str, Any]:
        """Executes and captures a payment against an order in test mode."""
        amount_paise = int(round(amount_inr * 100))

        audit_trail.log_event(
            event_type="RAZORPAY_PAYMENT_INITIATED",
            objective_id=objective_id,
            details={
                "order_id": order_id,
                "amount_inr": amount_inr,
                "method": method,
                "simulate_failure": simulate_failure,
            },
        )

        if simulate_failure:
            audit_trail.log_event(
                event_type="RAZORPAY_PAYMENT_FAILED",
                objective_id=objective_id,
                details={
                    "order_id": order_id,
                    "reason": "Simulated card decline / insufficient funds",
                },
                level="WARNING",
            )
            return {
                "id": f"pay_{uuid.uuid4().hex[:14]}",
                "status": "failed",
                "order_id": order_id,
                "amount": amount_paise,
                "currency": "INR",
                "error_code": "PAYMENT_DECLINED",
                "error_description": "Card was declined by issuing bank (test mode)",
            }

        # Captured test payment
        payment_id = f"pay_{uuid.uuid4().hex[:14]}"
        payment = {
            "id": payment_id,
            "entity": "payment",
            "amount": amount_paise,
            "currency": "INR",
            "status": "captured",
            "order_id": order_id,
            "method": method,
            "captured": True,
            "description": f"Autonomous payment for order {order_id}",
        }
        self._mock_payments[payment_id] = payment

        if order_id in self._mock_orders:
            self._mock_orders[order_id]["status"] = "paid"
            self._mock_orders[order_id]["amount_paid"] = amount_paise
            self._mock_orders[order_id]["attempts"] = 1

        audit_trail.log_event(
            event_type="RAZORPAY_PAYMENT_CAPTURED",
            objective_id=objective_id,
            details={
                "payment_id": payment_id,
                "order_id": order_id,
                "amount_inr": amount_inr,
                "status": "captured",
            },
        )
        return payment


# Global singleton client
razorpay_client = RazorpayClientAdapter()
"""End-to-End Tests for Single Merchant Autonomous Purchase Flow."""

from app.merchants import merchant_c
from app.modules.audit.trail import audit_trail
from app.shopping_agent.orchestrator import shopping_orchestrator


def test_happy_path_single_merchant():
    """Verify autonomous shopping succeeds when price and constraints are met."""
    intent = {
        "description": "Buy me Adidas blue sneakers, size 10, under Rs. 5,500",
        "query": "adidas",
        "max_price": 5500.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent, merchant=merchant_c)
    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    assert result["amount_paid_inr"] > 0
    assert result["order_id"].startswith("order_")
    assert result["payment_id"].startswith("pay_")

    # Verify audit trail has full transparent sequence
    events = audit_trail.get_events_for_objective(result["objective_id"])
    event_types = [e["event_type"] for e in events]
    assert "INTENT_RECEIVED" in event_types
    assert "POLICY_EVALUATED" in event_types
    assert "PAYMENT_POLICY_CHECK" in event_types
    assert "RAZORPAY_ORDER_CREATED" in event_types
    assert "RAZORPAY_PAYMENT_CAPTURED" in event_types
    assert "PURCHASE_COMPLETED" in event_types


def test_policy_rejection_over_budget():
    """Verify deterministic policy prevents purchase when price exceeds budget."""
    intent = {
        "description": "Buy Adidas sneakers under Rs. 4,000",
        "query": "adidas",
        "max_price": 4000.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent, merchant=merchant_c)
    assert result["success"] is False
    assert result["status"] == "POLICY_REJECTED"
    assert any("PRICE_EXCEEDED" in v for v in result["violations"])

    # Ensure no money action occurred
    events = audit_trail.get_events_for_objective(result["objective_id"])
    event_types = [e["event_type"] for e in events]
    assert "RAZORPAY_ORDER_CREATED" not in event_types
    assert "RAZORPAY_PAYMENT_CAPTURED" not in event_types


def test_payment_failure_handled_without_false_success():
    """Verify that a payment failure is reported gracefully and never claims success."""
    intent = {
        "description": "Buy Adidas blue sneakers under Rs. 5,500",
        "query": "adidas",
        "max_price": 5500.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(
        intent,
        merchant=merchant_c,
        simulate_payment_failure=True
    )
    assert result["success"] is False
    assert result["status"] == "PAYMENT_FAILED"
    assert "failed" in result["error"].lower() or "declined" in result["error"].lower()
"""Tests for Deterministic Policy Gating and Hard Purchase Constraints."""

import pytest
from app.modules.policy.engine import policy_engine
from app.modules.acp.models import Item
from app.shopping_agent.orchestrator import shopping_orchestrator
from app.merchants import merchant_c
from app.modules.audit.trail import audit_trail


def test_policy_rejects_price_over_budget():
    """Policy must reject when price exceeds user-specified maximum budget."""
    item = Item(
        id="item_overprice",
        name="Expensive Shoes",
        brand="Adidas",
        price=6000.0,
        stock=5,
        attributes={"size": 10, "color": "blue"},
    )
    intent = {"max_price": 5000.0, "size": 10, "color": "blue", "auto_purchase": True}
    
    decision = policy_engine.evaluate_offer(item, intent)
    assert decision.allowed is False
    assert any("PRICE_EXCEEDED" in v for v in decision.violations)


def test_policy_rejects_size_mismatch():
    """Policy must reject when shoe size does not match requested size."""
    item = Item(
        id="item_wrong_size",
        name="Adidas Sneakers",
        brand="Adidas",
        price=4500.0,
        stock=5,
        attributes={"size": 9, "color": "blue"},  # Size 9, requested 10
    )
    intent = {"max_price": 5000.0, "size": 10, "color": "blue", "auto_purchase": True}
    
    decision = policy_engine.evaluate_offer(item, intent)
    assert decision.allowed is False
    assert any("VARIANT_MISMATCH" in v for v in decision.violations)


def test_policy_rejects_color_mismatch():
    """Policy must reject when item color does not match requested color."""
    item = Item(
        id="item_wrong_color",
        name="Adidas Red Sneakers",
        brand="Adidas",
        price=4500.0,
        stock=5,
        attributes={"size": 10, "color": "red"},  # Red, requested blue
    )
    intent = {"max_price": 5000.0, "size": 10, "color": "blue", "auto_purchase": True}
    
    decision = policy_engine.evaluate_offer(item, intent)
    assert decision.allowed is False
    assert any("COLOR_MISMATCH" in v for v in decision.violations)


def test_policy_rejects_when_auto_purchase_disabled():
    """Policy must reject autonomous checkout if user did not give permission."""
    item = Item(
        id="item_ok",
        name="Adidas Blue Sneakers",
        brand="Adidas",
        price=4500.0,
        stock=5,
        attributes={"size": 10, "color": "blue"},
    )
    intent = {"max_price": 5000.0, "size": 10, "color": "blue", "auto_purchase": False}
    
    decision = policy_engine.evaluate_offer(item, intent)
    assert decision.allowed is False
    assert any("USER_CONFIRMATION_REQUIRED" in v for v in decision.violations)


def test_policy_rejects_duplicate_payment_reference():
    """Policy must reject duplicate payment executions with the same reference (replay protection)."""
    ref = "tx_nonce_12345"
    d1 = policy_engine.evaluate_payment(amount=4500.0, authorized_max_amount=5000.0, payment_reference=ref)
    assert d1.allowed is True

    # Replay attempt
    d2 = policy_engine.evaluate_payment(amount=4500.0, authorized_max_amount=5000.0, payment_reference=ref)
    assert d2.allowed is False
    assert any("DUPLICATE_PAYMENT_ATTEMPT" in v for v in d2.violations)


def test_orchestrator_hard_gates_against_policy_bypass():
    """Ensure that the Shopping Agent orchestrator halts and never touches payment APIs on policy rejection."""
    intent = {
        "description": "Buy Adidas sneakers with too low budget",
        "query": "adidas",
        "max_price": 3500.0,  # Below Merchant C's ₹4,899
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent, merchant=merchant_c)
    assert result["success"] is False
    assert result["status"] == "POLICY_REJECTED"

    # Verify no payment was created or captured
    events = audit_trail.get_events_for_objective(result["objective_id"])
    event_types = [e["event_type"] for e in events]
    assert "RAZORPAY_ORDER_CREATED" not in event_types
    assert "RAZORPAY_PAYMENT_CAPTURED" not in event_types
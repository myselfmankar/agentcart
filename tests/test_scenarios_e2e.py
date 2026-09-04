"""Comprehensive End-to-End Buildathon Scenarios."""

import pytest
from app.shopping_agent.orchestrator import shopping_orchestrator
from app.merchants import merchant_b, merchant_c
from app.modules.watch.objective import ObjectiveStatus, ObjectiveStore, ShoppingObjective
from app.modules.watch.event_bus import event_bus
from app.modules.policy.engine import policy_engine
from app.modules.razorpay.client import razorpay_client
from app.modules.audit.trail import audit_trail
from app.modules.buyer.ledger import buyer_ledger
from adk_agents.shopping_agent.buyer_agent import run_autonomous_purchase


def test_scenario_7_stock_exhausted_during_checkout():
    """Verify that if stock is depleted between selection and checkout, it fails safely."""
    item = merchant_c.get_item("adidas-runfalcon-3_blue_10")
    orig_stock = item.stock if item else 8
    merchant_c.set_stock("adidas-runfalcon-3_blue_10", 1)

    intent = {
        "description": "Buy Adidas sneakers size 10 under 5500",
        "query": "adidas",
        "max_price": 5500.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    try:
        # First purchase succeeds and depletes stock to 0
        res1 = shopping_orchestrator.execute_intent(intent, merchant=merchant_c)
        assert res1["success"] is True
        assert merchant_c.get_item("adidas-runfalcon-3_blue_10").stock == 0

        # Second purchase immediately attempts checkout on now out-of-stock item
        res2 = shopping_orchestrator.execute_intent(intent, merchant=merchant_c)
        assert res2["success"] is False
        assert res2["status"] in ["POLICY_REJECTED", "NO_OFFER_FOUND"]

        # Ensure no payment order was created for second purchase
        events = audit_trail.get_events_for_objective(res2["objective_id"])
        event_types = [e["event_type"] for e in events]
        assert "RAZORPAY_PAYMENT_CAPTURED" not in event_types

    finally:
        merchant_c.set_stock("adidas-runfalcon-3_blue_10", orig_stock)


def test_scenario_complete_audit_trail_integrity():
    """Verify that every successful run produces an explainable, secret-free audit trail."""
    intent = {
        "description": "Audit trail test run",
        "query": "adidas",
        "max_price": 5000.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    res = shopping_orchestrator.execute_intent(intent)
    assert res["success"] is True
    obj_id = res["objective_id"]

    events = audit_trail.get_events_for_objective(obj_id)
    assert len(events) >= 4

    # Verify no secret keywords exist in audit trail
    for event in events:
        dumped = str(event).lower()
        for forbidden in ["mocksecret", "private_key", "password"]:
            assert forbidden not in dumped


def test_scenario_1_happy_path_adidas_blue_sneakers():
    """Scenario 1: 'Buy Adidas blue sneakers, size 10, under Rs. 5,000.'
    At least one merchant produces a valid offer. Purchase completes successfully.
    """
    buyer_ledger.reset(available_balance=50000.0, per_transaction_limit=10000.0)
    result = run_autonomous_purchase(
        query="Adidas blue sneakers",
        brand="Adidas",
        color="blue",
        size=10,
        max_budget=5000.0,
        auto_purchase=True,
    )

    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    assert result["amount_paid_inr"] <= 5000.0
    assert result["merchant"] in ["FastFeet", "UrbanKicks"]
    assert result["order_id"].startswith("order_")
    assert result["payment_id"].startswith("pay_")


def test_scenario_2_delivery_constraint_within_2_days():
    """Scenario 2: 'Buy Adidas blue sneakers, size 10, under Rs. 5,000. I need them within 2 days.'
    Merchants evaluated against 2-day delivery capability.
    """
    buyer_ledger.reset(available_balance=50000.0, per_transaction_limit=10000.0)
    result = run_autonomous_purchase(
        query="Adidas blue sneakers",
        brand="Adidas",
        color="blue",
        size=10,
        max_budget=5000.0,
        max_delivery_days=2,
        auto_purchase=True,
    )

    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    # UrbanKicks has 2-day express, FastFeet has 1-day express; ShoeKart has 6-day (3d express)
    assert result["merchant"] in ["FastFeet", "UrbanKicks"]


def test_scenario_3_negotiation_discounts_above_limit():
    """Scenario 3: Request where merchant base price is above buyer limit (Rs. 5,099 > Rs. 5,000),
    but policy discount/counter brings final offer below budget.
    """
    buyer_ledger.reset(available_balance=50000.0, per_transaction_limit=10000.0)
    # Target FastFeet whose base price for Runfalcon 3 is Rs. 5,099
    intent = {
        "description": "Buy Adidas Runfalcon 3 under Rs. 5,000 with negotiation",
        "query": "Adidas Runfalcon 3",
        "brand": "Adidas",
        "color": "blue",
        "size": 10,
        "max_price": 4900.0,
        "quantity": 1,
        "auto_purchase": True,
    }
    result = shopping_orchestrator.execute_intent(intent, enable_watching=False)
    assert result["success"] is True
    assert result["amount_paid_inr"] <= 4900.0


def test_scenario_4_no_match_impossible_constraint_watching():
    """Scenario 4: Deliberately impossible constraint (budget Rs. 1,000 for brand sneakers).
    Verifies that no qualifying offer exists and enters WATCHING state.
    """
    intent = {
        "description": "Impossible budget for Adidas sneakers",
        "query": "Adidas",
        "brand": "Adidas",
        "color": "blue",
        "size": 10,
        "max_price": 1000.0,
        "quantity": 1,
        "auto_purchase": True,
    }
    result = shopping_orchestrator.execute_intent(intent, enable_watching=True)
    assert result["success"] is False
    assert result["status"] == "WATCHING"
    assert "WATCHING" in result["message"] or "watching" in result["message"].lower()


def test_scenario_5_insufficient_balance_no_payment():
    """Scenario 5: Valid offer qualifies, checkout created, but buyer balance check fails.
    AP2 payment authorization does NOT proceed and Razorpay is NOT called.
    """
    buyer_ledger.set_limits(available_balance=1500.0, per_transaction_limit=5000.0, publish_event=False)
    result = run_autonomous_purchase(
        query="Adidas blue sneakers",
        brand="Adidas",
        color="blue",
        size=10,
        max_budget=5000.0,
        auto_purchase=True,
    )

    assert result["success"] is False
    assert result["status"] in ["rejected", "AWAITING_FUNDS", "WATCHING_FOR_QUALIFYING_OFFER"]
    assert result["reason"] == "INSUFFICIENT_BUYER_BALANCE"
    assert result["razorpay_called"] is False
    assert buyer_ledger.available_balance == 1500.0
"""Tests for Multi-Merchant Autonomous Decision Making over A2A."""

import json
from pathlib import Path
import pytest
from app.shopping_agent.orchestrator import shopping_orchestrator
from app.modules.a2a.client import a2a_client
from app.modules.audit.trail import audit_trail


def test_multi_merchant_autonomous_selection():
    """Verify Shopping Agent compares Merchant proposals, negotiates with FastFeet, and completes purchase."""
    intent = {
        "description": "Buy me Adidas blue sneakers, size 10, under Rs. 5,000",
        "query": "adidas",
        "max_price": 5000.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent)
    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    assert "FastFeet" in result["merchant"]
    assert result["amount_paid_inr"] <= 5000.0
    assert len(result["proposals"]) == 3
    assert result["ai_reasoning"] != ""

    # Verify audit trail contains multi-merchant decision comparison
    events = audit_trail.get_events_for_objective(result["objective_id"])
    event_types = [e["event_type"] for e in events]
    assert "MERCHANT_PROPOSAL_RECEIVED" in event_types
    assert "AI_BUYER_DECISION_FINALIZED" in event_types
    assert "PURCHASE_COMPLETED" in event_types


def test_all_merchants_disqualified_when_budget_too_low():
    """Verify that when no merchant qualifies, explicit rejection reasons are produced."""
    intent = {
        "description": "Buy Adidas sneakers under Rs. 4,000",
        "query": "adidas",
        "max_price": 4000.0,  # All 3 merchants are above Rs. 4,000 or out of stock
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent)
    assert result["success"] is False
    assert result["status"] == "NO_OFFER_FOUND"
    assert len(result["proposals"]) == 3
    assert "budget" in result["reasoning"].lower() or "exceeds" in result["reasoning"].lower()


def test_merchant_policy_independence_and_decoupling():
    """Verifies that changing Merchant C's isolated policy.json directly affects subsequent A2A proposals."""
    policy_path = Path("merchants/merchant_c/policy.json")
    original_text = policy_path.read_text(encoding="utf-8")
    policy_data = json.loads(original_text)

    try:
        # Change Merchant C's negotiation floor to Rs. 4800
        policy_data["negotiation_policy"]["floor_price"] = 4800
        policy_path.write_text(json.dumps(policy_data, indent=2), encoding="utf-8")

        # Buyer Agent requests proposals over A2A
        proposals = a2a_client.request_proposals(
            query="adidas",
            filters={"size": 10, "color": "blue"},
            target_merchant_id="merchant_c",
        )
        assert len(proposals) == 1
        prop_c = proposals[0]

        # Case 1: Negotiate against competitor quote of Rs. 4899 -> Merchant C undercuts by Rs. 50 (to 4849)
        counter1 = a2a_client.negotiate("merchant_c", prop_c, competing_price=4899.0)
        assert counter1 is not None
        assert counter1.proposed_price == 4849.0

        # Case 2: Negotiate against competitor quote of Rs. 4820 -> undercut target 4770 hits floor at 4800
        counter2 = a2a_client.negotiate("merchant_c", counter1, competing_price=4820.0)
        assert counter2 is not None
        assert counter2.proposed_price == 4800.0

        # Case 3: Negotiate against aggressive competitor quote of Rs. 4750 -> below floor, Merchant C declines
        declined = a2a_client.negotiate("merchant_c", counter2, competing_price=4750.0)
        assert declined is None

    finally:
        policy_path.write_text(original_text, encoding="utf-8")
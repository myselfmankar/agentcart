"""Test Autonomous Execution Loop for Buyer Agent."""

import pytest

from adk_agents.shopping_agent.buyer_agent import (
    buyer_agent,
    root_agent,
    run_autonomous_purchase,
    shopping_agent,
)
from app.modules.audit.trail import audit_trail
from app.modules.buyer.ledger import buyer_ledger
from app.modules.watch.objective import objective_store


@pytest.fixture(autouse=True)
def setup_test_env():
    buyer_ledger.reset(available_balance=6000.0, per_transaction_limit=5000.0)
    objective_store.clear()
    audit_trail.clear()
    yield
    buyer_ledger.reset(available_balance=6000.0, per_transaction_limit=5000.0)
    objective_store.clear()


def test_buyer_agent_composition():
    """Verifies that the Buyer Agent is the sole user-facing autonomous representative."""
    assert root_agent.name == "buyer_agent"
    assert buyer_agent.name == "buyer_agent"
    assert shopping_agent.name == "buyer_agent"
    tool_names = [t.__name__ for t in buyer_agent.tools]
    assert "run_autonomous_purchase" in tool_names
    assert "check_buyer_balance" not in tool_names
    assert "search_merchant_proposals" not in tool_names
    assert "negotiate_with_merchant" not in tool_names


def test_autonomous_single_pass_execution():
    """Verifies that run_autonomous_purchase executes the full A2A multi-merchant pipeline in a single turn."""
    result = run_autonomous_purchase(
        query="adidas",
        max_budget=5000.0,
        size=10,
        color="blue",
        auto_purchase=True,
    )

    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    assert result["merchant"] == "FastFeet"
    amount = result["amount_paid_inr"]
    assert amount > 0
    assert result["order_id"].startswith("order_")
    assert result["payment_id"].startswith("pay_")
    assert result["closed_checkout_mandate_id"].startswith("closed_chk_")
    assert result["closed_payment_mandate_id"].startswith("closed_pay_")
    assert result["checkout_receipt_id"].startswith("rcpt_chk_")
    assert result["payment_receipt_id"].startswith("rcpt_pay_")
    assert buyer_ledger.available_balance == 6000.0 - amount

    # Verify audit events
    events = [e["event_type"] for e in audit_trail.get_events()]
    assert "INTENT_RECEIVED" in events
    assert "merchant.discovered" in events
    assert "AI_BUYER_SOLICITING_PROPOSALS" in events
    assert "MERCHANT_PROPOSAL_RECEIVED" in events
    assert "BUYER_NEGOTIATION_ACCEPTED" in events
    assert "AI_BUYER_DECISION_FINALIZED" in events
    assert "POLICY_EVALUATED" in events
    assert "checkout.created" in events
    assert "buyer.balance.checked" in events
    assert "PAYMENT_POLICY_CHECK" in events
    assert "buyer.balance.debited" in events
    assert "checkout.completed" in events
    assert "PURCHASE_COMPLETED" in events


def test_autonomous_rejection_on_low_balance():
    """Verifies that autonomous purchasing rejects cleanly without money movement when balance is insufficient."""
    buyer_ledger.set_limits(available_balance=2500.0, per_transaction_limit=5000.0, publish_event=False)

    result = run_autonomous_purchase(
        query="adidas",
        max_budget=5000.0,
        size=10,
        color="blue",
        auto_purchase=True,
    )

    assert result["success"] is False
    assert result["status"] in ["rejected", "AWAITING_FUNDS", "WATCHING_FOR_QUALIFYING_OFFER"]
    assert result["reason"] == "INSUFFICIENT_BUYER_BALANCE"
    assert result["razorpay_called"] is False
    assert buyer_ledger.available_balance == 2500.0

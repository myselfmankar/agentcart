"""Test Buyer Spending Authority, Available Balance vs. Transaction Limits, and Ledger Reconciliations."""

import pytest

from app.modules.audit.trail import audit_trail
from app.modules.buyer.ledger import buyer_ledger
from app.modules.watch.objective import ObjectiveStatus, objective_store
from app.shopping_agent.orchestrator import shopping_orchestrator


@pytest.fixture(autouse=True)
def setup_buyer_ledger():
    """Reset buyer ledger, objective store, and audit trail before each test."""
    buyer_ledger.reset(available_balance=6000.0, per_transaction_limit=5000.0)
    objective_store.clear()
    audit_trail.clear()
    yield
    buyer_ledger.reset(available_balance=6000.0, per_transaction_limit=5000.0)
    objective_store.clear()


def test_insufficient_buyer_balance_rejection_scenario():
    """Regression Scenario:
    Buyer balance = ₹3,000
    Transaction limit = ₹5,000
    User Budget = ₹5,000
    Merchant negotiated offer = ~₹4,849

    Expected:
    - Product / budget constraints pass.
    - ACP checkout created.
    - Buyer balance check FAILS (required_amount > ₹3,000).
    - No AP2 closed payment mandate issued.
    - Razorpay payment NOT called.
    - Machine-readable rejection result with shortfall.
    - Audit logs recorded: buyer.balance.checked, buyer.balance.insufficient, payment.not_attempted.
    """
    buyer_ledger.set_limits(available_balance=3000.0, per_transaction_limit=5000.0, publish_event=False)

    intent = {
        "description": "Buy Adidas blue sneakers size 10 under Rs. 5000",
        "query": "adidas",
        "size": 10,
        "color": "blue",
        "max_price": 5000.0,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent=intent, enable_watching=False)

    assert result["success"] is False
    assert result["status"] == "rejected"
    assert result["reason"] == "INSUFFICIENT_BUYER_BALANCE"
    assert result["required_amount"] > 3000.0
    assert result["available_balance"] == 3000.0
    assert result["shortfall"] == result["required_amount"] - 3000.0
    assert result["currency"] == "INR"
    assert result["razorpay_called"] is False
    assert "3,000" in result["message"]

    # Verify audit trail events
    events = [e["event_type"] for e in audit_trail.get_events()]
    assert "buyer.balance.checked" in events
    assert "buyer.balance.insufficient" in events
    assert "payment.not_attempted" in events
    assert "PURCHASE_COMPLETED" not in events

    # Verify balance was NOT deducted
    assert buyer_ledger.available_balance == 3000.0


def test_per_transaction_limit_exceeded_scenario():
    """Scenario:
    Buyer available balance = ₹6,000
    Per-transaction limit = ₹4,500
    Offer = ~₹4,849

    Expected:
    - Fails due to TRANSACTION_LIMIT_EXCEEDED.
    - Razorpay payment NOT called.
    """
    buyer_ledger.set_limits(available_balance=6000.0, per_transaction_limit=4500.0, publish_event=False)

    intent = {
        "description": "Buy Adidas blue sneakers size 10 under Rs. 5000",
        "query": "adidas",
        "size": 10,
        "color": "blue",
        "max_price": 5000.0,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent=intent, enable_watching=False)

    assert result["success"] is False
    assert result["reason"] == "TRANSACTION_LIMIT_EXCEEDED"
    assert result["razorpay_called"] is False
    assert buyer_ledger.available_balance == 6000.0


def test_ledger_debit_reconciliation_on_success():
    """Verifies that balance is deducted exactly once on successful payment capture."""
    buyer_ledger.set_limits(available_balance=6000.0, per_transaction_limit=5000.0, publish_event=False)

    intent = {
        "description": "Buy Adidas blue sneakers size 10 under Rs. 5000",
        "query": "adidas",
        "size": 10,
        "color": "blue",
        "max_price": 5000.0,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent=intent)

    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    amount = result["amount_paid_inr"]
    assert amount > 0

    # Balance debited from 6000 to (6000 - amount)
    expected_remaining = 6000.0 - amount
    assert buyer_ledger.available_balance == expected_remaining
    assert result["remaining_balance_inr"] == expected_remaining

    # Idempotent debit test: re-recording the same transaction does not double debit
    double_debit = buyer_ledger.record_debit(
        transaction_id=f"tx_{result['objective_id']}",
        amount=amount,
        currency="INR",
        merchant_id="merchant_c",
        razorpay_order_id=result["order_id"],
        razorpay_payment_id=result["payment_id"],
    )
    assert double_debit is False
    assert buyer_ledger.available_balance == expected_remaining


def test_payment_failure_does_not_debit_balance():
    """Verifies that payment capture failure does not debit the buyer balance."""
    buyer_ledger.set_limits(available_balance=6000.0, per_transaction_limit=5000.0, publish_event=False)

    intent = {
        "description": "Buy Adidas blue sneakers size 10 under Rs. 5000",
        "query": "adidas",
        "size": 10,
        "color": "blue",
        "max_price": 5000.0,
        "auto_purchase": True,
    }

    result = shopping_orchestrator.execute_intent(intent=intent, simulate_payment_failure=True)

    assert result["success"] is False
    assert result["status"] == "PAYMENT_FAILED"
    # Balance must remain untouched at ₹6,000
    assert buyer_ledger.available_balance == 6000.0


def test_watching_insufficient_balance_and_topup_re_evaluation():
    """Verifies WATCHING state when balance is insufficient, followed by deposit and re-evaluation."""
    buyer_ledger.set_limits(available_balance=3000.0, per_transaction_limit=5000.0, publish_event=False)

    intent = {
        "description": "Buy Adidas blue sneakers size 10 under Rs. 5000",
        "query": "adidas",
        "size": 10,
        "color": "blue",
        "max_price": 5000.0,
        "auto_purchase": True,
    }

    obj_id = "obj_watch_bal_test"
    result = shopping_orchestrator.execute_intent(
        intent=intent,
        enable_watching=True,
        objective_id=obj_id,
    )

    assert result["success"] is False
    assert result["status"] in ["AWAITING_FUNDS", "WATCHING_FOR_QUALIFYING_OFFER"]
    assert result["reason"] == "INSUFFICIENT_BUYER_BALANCE"

    obj = objective_store.get_objective(obj_id)
    assert obj is not None
    assert obj.status in [ObjectiveStatus.AWAITING_FUNDS, ObjectiveStatus.WATCHING]

    # Buyer deposits funds (+₹3,000). This triggers synchronous re-evaluation via event bus!
    buyer_ledger.deposit(3000.0, currency="INR")

    # Objective was re-evaluated automatically via event_bus subscription and finalized
    updated_obj = objective_store.get_objective(obj_id)
    assert updated_obj.status == ObjectiveStatus.COMPLETED
    assert updated_obj.purchase_result["success"] is True
    amount = updated_obj.purchase_result["amount_paid_inr"]
    assert buyer_ledger.available_balance == 6000.0 - amount

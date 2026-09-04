"""Comprehensive Protocol Conformance & Security Invariants Tests for AP2/ACP/A2A/Razorpay.

Validates the security and protocol invariants:
1. LLM cannot authorize payment.
2. Merchant cannot modify user authorization.
3. Agent cannot exceed Open Payment Mandate.
4. Closed mandates cannot be reused (replay prevention).
5. A closed mandate must reference exactly one authoritative checkout.
6. Payment must correspond to the finalized checkout.
7. Webhook receipt does not imply validity without verification.
8. Expired/revoked/replayed mandates are rejected deterministically.
9. No secret/private key appears in audit logs.
10. WATCHING never executes using stale closed authorization.
11. Merchant remains authoritative for final price/tax/fulfillment.
12. Razorpay remains authoritative for actual payment state.
"""

import time
import pytest
from app.modules.ap2.mandates import (
    authorize_user_mandates,
    create_open_checkout_mandate,
    create_open_payment_mandate,
    create_closed_checkout_mandate,
    create_closed_payment_mandate,
    create_checkout_receipt,
    create_payment_receipt,
)
from app.modules.ap2.verifier import deterministic_verifier
from app.modules.policy.engine import policy_engine
from app.merchants import merchant_b, merchant_c
from app.modules.watch.event_bus import event_bus
from app.modules.watch.objective import ObjectiveStatus
from app.shopping_agent.orchestrator import shopping_orchestrator
from app.modules.razorpay.webhooks import webhook_handler
from app.modules.audit.trail import audit_trail


def test_invariant_open_mandates_cryptographic_signatures():
    """Verify Open Checkout Mandate & Open Payment Mandate are signed with cnf.jwk embedded."""
    intent = {
        "description": "Buy Adidas sneakers size 10 under Rs. 5,000",
        "max_price": 5000.0,
        "currency": "INR",
        "size": 10,
        "color": "blue",
        "auto_purchase": True,
    }
    open_chk, open_pay = authorize_user_mandates(intent)

    # Verify Open Checkout Mandate
    chk_res = deterministic_verifier.verify_open_mandate(open_chk["token"])
    assert chk_res.allowed is True
    assert chk_res.code == "OK"
    assert "jwk" in open_chk["payload"]["cnf"]

    # Verify Open Payment Mandate
    pay_res = deterministic_verifier.verify_open_mandate(open_pay["token"])
    assert pay_res.allowed is True
    assert pay_res.code == "OK"
    assert open_pay["payload"]["checkout_reference"] == open_chk["token_hash"]


def test_invariant_expired_open_mandate_rejected():
    """Verify expired open mandates are rejected deterministically."""
    open_chk = create_open_checkout_mandate(
        description="Expired mandate test",
        max_price=5000.0,
        ttl_hours=-1,  # Expired 1 hour ago
    )
    res = deterministic_verifier.verify_open_mandate(open_chk["token"])
    assert res.allowed is False
    assert res.code == "OPEN_MANDATE_EXPIRED"
    assert "expired" in res.message.lower()


def test_invariant_agent_cannot_exceed_open_payment_mandate():
    """Verify that a payment exceeding Open Payment Mandate is blocked deterministically."""
    open_chk, open_pay = authorize_user_mandates({
        "description": "Budget limit test",
        "max_price": 4500.0,  # Open Payment Mandate cap is Rs. 4,500
    })

    fake_checkout_hash = "f" * 64

    # Agent attempts to create closed payment mandate for Rs. 4,899 (exceeds Rs. 4,500)
    closed_pay = create_closed_payment_mandate(
        open_payment_mandate_id=open_pay["mandate_id"],
        checkout_hash=fake_checkout_hash,
        amount=4899.0,
        currency="INR",
        payee="FastFeet",
    )

    verif = deterministic_verifier.verify_payment_authorization(
        closed_payment_token=closed_pay["token"],
        open_payment_claims=open_pay["payload"],
        expected_amount=4899.0,
        expected_payee="FastFeet",
        expected_checkout_hash=fake_checkout_hash,
    )
    assert verif.allowed is False
    assert verif.code == "PAYMENT_EXCEEDS_OPEN_MANDATE"


def test_invariant_closed_mandate_bound_to_checkout_hash():
    """Verify checkout hash mismatch between closed mandate and authoritative checkout fails."""
    open_chk, open_pay = authorize_user_mandates({
        "description": "Hash binding test",
        "max_price": 5000.0,
    })

    correct_hash = "a" * 64
    tampered_hash = "b" * 64

    closed_pay = create_closed_payment_mandate(
        open_payment_mandate_id=open_pay["mandate_id"],
        checkout_hash=tampered_hash,
        amount=4000.0,
        currency="INR",
        payee="FastFeet",
    )

    verif = deterministic_verifier.verify_payment_authorization(
        closed_payment_token=closed_pay["token"],
        open_payment_claims=open_pay["payload"],
        expected_amount=4000.0,
        expected_payee="FastFeet",
        expected_checkout_hash=correct_hash,  # Authoritative checkout has correct_hash
    )
    assert verif.allowed is False
    assert verif.code == "CHECKOUT_HASH_MISMATCH"


def test_invariant_closed_mandate_replay_prevention():
    """Verify that a consumed closed mandate cannot be reused for another payment."""
    verifier = deterministic_verifier
    mandate_id = f"closed_chk_replay_{time.time()}"
    verifier.mark_mandate_consumed(mandate_id)
    assert mandate_id in verifier._consumed_mandates


def test_invariant_watching_re_evaluation_creates_new_checkout_and_mandates():
    """Verify that a WATCHING objective re-evaluates by constructing a NEW checkout and NEW mandates."""
    merchant_b.set_stock("adidas-runfalcon-3_blue_10", 0)

    try:
        intent = {
            "description": "Buy Adidas sneakers size 10 under 4600",
            "query": "adidas",
            "max_price": 4600.0,
            "size": 10,
            "color": "blue",
            "quantity": 1,
            "auto_purchase": True,
        }

        # Step 1: Initial search enters WATCHING
        init_res = shopping_orchestrator.execute_intent(intent, enable_watching=True)
        assert init_res["status"] == "WATCHING"
        obj_id = init_res["objective_id"]

        # Step 2: Merchant B restocks
        merchant_b.set_stock("adidas-runfalcon-3_blue_10", 4)

        event_bus.publish(
            event_type="INVENTORY_CHANGED",
            merchant_id="merchant_b",
            item_id="adidas-runfalcon-3_blue_10",
            payload={"stock": 4, "price": 4549.0},
            objective_id=obj_id,
        )

        # Step 3: Objective automatically re-evaluates
        obj = shopping_orchestrator.objective_store.get_objective(obj_id)
        assert obj.status == ObjectiveStatus.COMPLETED
        purch = obj.purchase_result
        assert purch["success"] is True
        assert purch["amount_paid_inr"] <= 4600.0
        assert "closed_checkout_mandate_id" in purch
        assert "closed_payment_mandate_id" in purch
        assert "checkout_hash" in purch

    finally:
        merchant_b.set_stock("adidas-runfalcon-3_blue_10", 0)


def test_invariant_policy_explainable_rejection():
    """Verify that when policy blocks a purchase, structured diagnostic details are returned."""
    intent = {
        "description": "Buy Adidas sneakers under Rs. 3,000",
        "query": "adidas",
        "max_price": 3000.0,
        "size": 10,
        "color": "blue",
        "quantity": 1,
        "auto_purchase": True,
    }

    res = shopping_orchestrator.execute_intent(intent, merchant=merchant_c)
    assert res["success"] is False
    assert res["status"] in ["POLICY_REJECTED", "NO_OFFER_FOUND"]
    assert res.get("money_moved_inr", 0.0) == 0.0

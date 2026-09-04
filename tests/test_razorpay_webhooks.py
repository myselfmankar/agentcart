"""Tests for Razorpay Webhook Verification, Idempotency, and State Truth."""

import hmac
import hashlib
import json
import pytest
from app.modules.razorpay.webhooks import webhook_handler, WebhookVerificationError
from app.modules.watch.objective import ShoppingObjective, ObjectiveStatus, objective_store
from app.modules.audit.trail import audit_trail

SECRET = "whsec_mockWebhookSecret12345"


def generate_signature(body_bytes: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def test_valid_webhook_signature_and_processing():
    """Verify that a genuine payment.captured webhook updates the objective."""
    obj_id = "obj_wh_test_1"
    obj = ShoppingObjective(objective_id=obj_id, user_intent={"max_price": 5000.0})
    obj.transition_to(ObjectiveStatus.CHECKING_OUT, "Awaiting payment")
    obj.purchase_result = {"success": True, "amount_paid_inr": 4899.0}
    objective_store.save_objective(obj)

    payload = {
        "id": "evt_capture_123",
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_999",
                    "order_id": "order_test_999",
                    "amount": 489900,
                    "status": "captured",
                    "notes": {"objective_id": obj_id},
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = generate_signature(body_bytes)

    success, msg, data = webhook_handler.process_webhook(
        raw_body=body_bytes, signature=sig, event_id="evt_capture_123"
    )

    assert success is True
    assert "CAPTURED" in msg

    # Objective should now be verified via webhook
    updated = objective_store.get_objective(obj_id)
    assert updated.status == ObjectiveStatus.COMPLETED
    assert updated.purchase_result.get("webhook_verified") is True


def test_invalid_webhook_signature_raises_error():
    """Webhook with forged or corrupted signature must be rejected."""
    payload = {"id": "evt_forged", "event": "payment.captured"}
    body_bytes = json.dumps(payload).encode("utf-8")
    fake_sig = "a" * 64

    with pytest.raises(WebhookVerificationError):
        webhook_handler.process_webhook(raw_body=body_bytes, signature=fake_sig)


def test_duplicate_webhook_is_idempotent():
    """Duplicate delivery of the same webhook event ID must be safely ignored."""
    payload = {
        "id": "evt_idemp_1",
        "entity": "event",
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_1", "notes": {}}}},
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = generate_signature(body_bytes)

    # First delivery
    success1, msg1, _ = webhook_handler.process_webhook(body_bytes, sig, event_id="evt_idemp_1")
    assert success1 is True
    assert msg1 != "DUPLICATE_IGNORED"

    # Redelivery of same event ID
    success2, msg2, _ = webhook_handler.process_webhook(body_bytes, sig, event_id="evt_idemp_1")
    assert success2 is True
    assert msg2 == "DUPLICATE_IGNORED"


def test_payment_failed_webhook_transitions_objective_to_failed():
    """When a webhook arrives with payment.failed, objective transitions to FAILED without claiming success."""
    obj_id = "obj_wh_failed_2"
    obj = ShoppingObjective(objective_id=obj_id, user_intent={"max_price": 5000.0})
    obj.transition_to(ObjectiveStatus.CHECKING_OUT, "Awaiting payment")
    objective_store.save_objective(obj)

    payload = {
        "id": "evt_fail_999",
        "entity": "event",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_failed_000",
                    "order_id": "order_fail_000",
                    "status": "failed",
                    "error_description": "Card expired",
                    "notes": {"objective_id": obj_id},
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = generate_signature(body_bytes)

    success, msg, data = webhook_handler.process_webhook(body_bytes, sig, event_id="evt_fail_999")
    assert success is True
    assert "FAILED" in msg

    updated = objective_store.get_objective(obj_id)
    assert updated.status == ObjectiveStatus.FAILED
    assert "payment failed" in updated.watch_reason.lower()


def test_virtual_account_credited_webhook_wakes_awaiting_funds():
    """Verify that a virtual_account.credited webhook deposits funds and wakes AWAITING_FUNDS objectives."""
    from app.modules.buyer.ledger import buyer_ledger
    from app.shopping_agent.orchestrator import shopping_orchestrator

    buyer_ledger.reset(available_balance=1000.0, per_transaction_limit=10000.0)
    obj_id = "obj_awaiting_funds_test"

    # Execute purchase with low balance (available: 1000, required ~4650)
    intent = {
        "description": "Buy Adidas blue sneakers size 10",
        "query": "adidas",
        "size": 10,
        "color": "blue",
        "max_price": 5000.0,
        "auto_purchase": True,
    }
    result = shopping_orchestrator.execute_intent(intent, enable_watching=True, objective_id=obj_id)
    assert result["status"] == "AWAITING_FUNDS"

    obj = objective_store.get_objective(obj_id)
    assert obj.status == ObjectiveStatus.AWAITING_FUNDS

    # Webhook arrives: user deposited Rs. 5,000 via UPI into Virtual Account
    payload = {
        "id": "evt_topup_123",
        "entity": "event",
        "event": "virtual_account.credited",
        "payload": {
            "virtual_account": {
                "entity": {
                    "id": "va_test_99",
                    "amount_paid": 500000,  # 500,000 paise = Rs. 5,000
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = generate_signature(body_bytes)

    success, msg, _ = webhook_handler.process_webhook(body_bytes, sig, event_id="evt_topup_123")
    assert success is True
    assert buyer_ledger.available_balance > 1000.0

    # Objective was automatically awakened from AWAITING_FUNDS and completed!
    updated = objective_store.get_objective(obj_id)
    assert updated.status == ObjectiveStatus.COMPLETED
    assert updated.purchase_result["success"] is True
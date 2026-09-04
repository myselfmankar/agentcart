"""ACP Checkout Coordinator.

Handles checkout session lifecycle:
- Initialization with line items and authoritative merchant pricing
- Fulfillment selection & tax/shipping calculation
- Authoritative merchant signing of checkout session (producing Checkout JWT & checkout_hash)
- Payment allowance attachment
- Completion, cancellation, and failure transitions
"""

import hashlib
import time
import uuid

from jwcrypto import jwt

from app.modules.acp.models import (
    AuthoritativeCheckoutToken,
    CheckoutSession,
    CheckoutStatus,
    FulfillmentOption,
    Item,
    LineItem,
    PaymentAllowance,
)
from app.modules.ap2.keys import get_merchant_key


class CheckoutManager:
    """Manages active ACP checkout sessions and enforces merchant authoritative state."""

    def __init__(self):
        self._sessions: dict[str, CheckoutSession] = {}

    def create_session(
        self,
        merchant_id: str,
        merchant_name: str,
        items: list[Item],
        quantities: list[int] | None = None,
        ttl_minutes: int = 15,
        tax_rate: float = 0.0,
        shipping_cost: float = 0.0,
        fulfillment: FulfillmentOption | None = None,
    ) -> CheckoutSession:
        if quantities is None:
            quantities = [1] * len(items)

        line_items = []
        subtotal = 0.0
        for item, qty in zip(items, quantities):
            total = item.price * qty
            subtotal += total
            line_items.append(LineItem(item=item, quantity=qty, total=total))

        tax = round(subtotal * tax_rate, 2)
        shipping = shipping_cost if fulfillment is None else fulfillment.cost
        total_amount = round(subtotal + tax + shipping, 2)

        session_id = f"chk_sess_{uuid.uuid4().hex[:12]}"
        now = time.time()
        session = CheckoutSession(
            id=session_id,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            line_items=line_items,
            currency="INR",
            subtotal=subtotal,
            tax=tax,
            shipping=shipping,
            total_amount=total_amount,
            status=CheckoutStatus.READY_FOR_PAYMENT,
            fulfillment=fulfillment,
            created_at=now,
            expires_at=now + (ttl_minutes * 60),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> CheckoutSession | None:
        return self._sessions.get(session_id)

    def select_fulfillment(self, session_id: str, fulfillment: FulfillmentOption) -> CheckoutSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        session.fulfillment = fulfillment
        session.shipping = fulfillment.cost
        session.total_amount = round(session.subtotal + session.tax + session.shipping, 2)
        return session

    def sign_authoritative_checkout(self, session_id: str) -> AuthoritativeCheckoutToken:
        """Merchant cryptographically signs the finalized checkout session into a Checkout JWT."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")

        merchant_key = get_merchant_key(session.merchant_id)
        now = int(time.time())
        exp = int(session.expires_at)

        claims = {
            "iss": session.merchant_id,
            "sub": session.id,
            "aud": "shopping_agent",
            "iat": now,
            "exp": exp,
            "currency": session.currency,
            "subtotal": session.subtotal,
            "tax": session.tax,
            "shipping": session.shipping,
            "total_amount": session.total_amount,
            "line_items": [
                {
                    "item_id": li.item.id,
                    "name": li.item.name,
                    "quantity": li.quantity,
                    "price": li.item.price,
                    "total": li.total,
                }
                for li in session.line_items
            ],
            "status": session.status.value,
        }

        token = jwt.JWT(
            header={"alg": "ES256", "kid": merchant_key.key_id, "typ": "JWT"},
            claims=claims,
        )
        token.make_signed_token(merchant_key)
        checkout_jwt = token.serialize()
        checkout_hash = hashlib.sha256(checkout_jwt.encode("utf-8")).hexdigest()

        session.checkout_jwt = checkout_jwt
        session.checkout_hash = checkout_hash

        return AuthoritativeCheckoutToken(
            session_id=session.id,
            merchant_id=session.merchant_id,
            checkout_jwt=checkout_jwt,
            checkout_hash=checkout_hash,
            total_amount=session.total_amount,
            currency=session.currency,
            expires_at=session.expires_at,
        )

    def attach_payment_allowance(self, session_id: str, allowance: PaymentAllowance) -> CheckoutSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        session.payment_allowance = allowance
        return session

    def attach_payment_order(self, session_id: str, payment_order_id: str) -> CheckoutSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        session.payment_order_id = payment_order_id
        session.status = CheckoutStatus.PROCESSING_PAYMENT
        return session

    def complete_session(self, session_id: str, payment_id: str) -> CheckoutSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        session.payment_id = payment_id
        session.status = CheckoutStatus.COMPLETED
        return session

    def cancel_session(self, session_id: str, reason: str = "User canceled") -> CheckoutSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        session.status = CheckoutStatus.CANCELED
        session.metadata["cancellation_reason"] = reason
        return session

    def fail_session(self, session_id: str, reason: str) -> CheckoutSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        session.status = CheckoutStatus.FAILED
        session.metadata["failure_reason"] = reason
        return session


# Default singleton checkout manager
checkout_manager = CheckoutManager()
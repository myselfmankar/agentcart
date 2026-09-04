"""Streamlined Protocol-Faithful AP2 Mandate Generator and Signer.

Implements the core AP2 protocol flow:
1. Open Checkout Mandate: User-signed constraints and shopping bounds.
2. Open Payment Mandate: Bounded payment authorization tied to user intent.
3. Closed Checkout Mandate: Agent-signed presentation bound to finalized merchant checkout.
4. Closed Payment Mandate: Payment authorization bound to checkout hash & order amount.
5. Checkout & Payment Receipts: Audit-verifiable completion receipts.
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from jwcrypto import jwt, jwk
from app.modules.ap2.keys import get_agent_provider_key, get_agent_key, get_merchant_key


class MandateStatus(str):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class OpenCheckoutMandateModel(BaseModel):
    mandate_id: str
    vct: str = "https://ap2.dev/vct/open_checkout_mandate_v1"
    natural_language_description: str
    category: Optional[str] = "shoes"
    brand: Optional[str] = None
    size: Optional[Any] = None
    color: Optional[str] = None
    max_price: float
    currency: str = "INR"
    quantity: int = 1
    allowed_merchants: Optional[List[str]] = None
    auto_purchase: bool = True
    cnf: Dict[str, Any]
    iat: int
    exp: int


class OpenPaymentMandateModel(BaseModel):
    mandate_id: str
    vct: str = "https://ap2.dev/vct/open_payment_mandate_v1"
    max_amount: float
    currency: str = "INR"
    allowed_payment_methods: List[str] = Field(default_factory=lambda: ["razorpay"])
    allowed_payees: Optional[List[str]] = None
    checkout_reference: str
    cnf: Dict[str, Any]
    iat: int
    exp: int


class ClosedCheckoutMandateModel(BaseModel):
    mandate_id: str
    open_checkout_mandate_id: str
    vct: str = "https://ap2.dev/vct/closed_checkout_mandate_v1"
    checkout_jwt: str
    checkout_hash: str
    merchant_id: str
    nonce: str
    aud: str = "merchant"
    iat: int
    exp: int


class ClosedPaymentMandateModel(BaseModel):
    mandate_id: str
    open_payment_mandate_id: str
    vct: str = "https://ap2.dev/vct/closed_payment_mandate_v1"
    checkout_hash: str
    amount: float
    currency: str = "INR"
    payee: str
    payment_method: str = "razorpay"
    payment_reference: str
    nonce: str
    aud: str = "payment_processor"
    iat: int
    exp: int


class CheckoutReceipt(BaseModel):
    receipt_id: str
    mandate_id: str
    checkout_hash: str
    merchant_id: str
    status: str = "VERIFIED"
    timestamp: float = Field(default_factory=time.time)
    signature: Optional[str] = None


class PaymentReceipt(BaseModel):
    receipt_id: str
    closed_payment_mandate_id: str
    checkout_hash: str
    order_id: str
    payment_id: str
    amount: float
    currency: str
    status: str = "CAPTURED"
    timestamp: float = Field(default_factory=time.time)
    signature: Optional[str] = None


# --- Mandate Generators & Signers ---

def create_open_checkout_mandate(
    description: str,
    max_price: float,
    currency: str = "INR",
    brand: Optional[str] = None,
    size: Optional[Any] = None,
    color: Optional[str] = None,
    quantity: int = 1,
    allowed_merchants: Optional[List[str]] = None,
    auto_purchase: bool = True,
    ttl_hours: int = 24,
) -> Dict[str, Any]:
    """Generates and signs the Open Checkout Mandate representing shopping constraints."""
    provider_key = get_agent_provider_key()
    agent_key = get_agent_key()
    agent_pub_jwk = json.loads(agent_key.export_public())

    mandate_id = f"open_chk_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    exp = now + (ttl_hours * 3600)

    claims = {
        "mandate_id": mandate_id,
        "vct": "https://ap2.dev/vct/open_checkout_mandate_v1",
        "natural_language_description": description,
        "brand": brand,
        "size": size,
        "color": color,
        "max_price": float(max_price),
        "currency": currency,
        "quantity": quantity,
        "allowed_merchants": allowed_merchants,
        "auto_purchase": auto_purchase,
        "cnf": {"jwk": agent_pub_jwk},
        "iat": now,
        "exp": exp,
    }

    token = jwt.JWT(
        header={"alg": "ES256", "kid": provider_key.key_id, "typ": "JWT"},
        claims=claims,
    )
    token.make_signed_token(provider_key)
    signed_jwt = token.serialize()
    token_hash = hashlib.sha256(signed_jwt.encode("utf-8")).hexdigest()

    return {
        "mandate_id": mandate_id,
        "token": signed_jwt,
        "token_hash": token_hash,
        "payload": claims,
        "status": MandateStatus.ACTIVE,
    }


def create_open_payment_mandate(
    open_checkout_token_hash: str,
    max_amount: float,
    currency: str = "INR",
    allowed_merchants: Optional[List[str]] = None,
    ttl_hours: int = 24,
) -> Dict[str, Any]:
    """Generates and signs the Open Payment Mandate representing bounded payment authority."""
    provider_key = get_agent_provider_key()
    agent_key = get_agent_key()
    agent_pub_jwk = json.loads(agent_key.export_public())

    mandate_id = f"open_pay_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    exp = now + (ttl_hours * 3600)

    claims = {
        "mandate_id": mandate_id,
        "vct": "https://ap2.dev/vct/open_payment_mandate_v1",
        "max_amount": float(max_amount),
        "currency": currency,
        "allowed_payment_methods": ["razorpay"],
        "allowed_payees": allowed_merchants,
        "checkout_reference": open_checkout_token_hash,
        "cnf": {"jwk": agent_pub_jwk},
        "iat": now,
        "exp": exp,
    }

    token = jwt.JWT(
        header={"alg": "ES256", "kid": provider_key.key_id, "typ": "JWT"},
        claims=claims,
    )
    token.make_signed_token(provider_key)
    signed_jwt = token.serialize()
    token_hash = hashlib.sha256(signed_jwt.encode("utf-8")).hexdigest()

    return {
        "mandate_id": mandate_id,
        "token": signed_jwt,
        "token_hash": token_hash,
        "payload": claims,
        "status": MandateStatus.ACTIVE,
    }


def create_closed_checkout_mandate(
    open_checkout_mandate_id: str,
    checkout_jwt: str,
    checkout_hash: str,
    merchant_id: str,
    ttl_hours: int = 1,
) -> Dict[str, Any]:
    """Generates and signs the Closed Checkout Mandate bound to the merchant checkout hash."""
    agent_key = get_agent_key()
    mandate_id = f"closed_chk_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    exp = now + (ttl_hours * 3600)

    claims = {
        "mandate_id": mandate_id,
        "open_checkout_mandate_id": open_checkout_mandate_id,
        "vct": "https://ap2.dev/vct/closed_checkout_mandate_v1",
        "checkout_jwt": checkout_jwt,
        "checkout_hash": checkout_hash,
        "merchant_id": merchant_id,
        "nonce": uuid.uuid4().hex,
        "aud": "merchant",
        "iat": now,
        "exp": exp,
    }

    token = jwt.JWT(
        header={"alg": "ES256", "kid": agent_key.key_id, "typ": "JWT"},
        claims=claims,
    )
    token.make_signed_token(agent_key)
    signed_jwt = token.serialize()

    return {
        "mandate_id": mandate_id,
        "token": signed_jwt,
        "payload": claims,
        "checkout_hash": checkout_hash,
    }


def create_closed_payment_mandate(
    open_payment_mandate_id: str,
    checkout_hash: str,
    amount: float,
    payee: str,
    currency: str = "INR",
    payment_method: str = "razorpay",
    payment_reference: Optional[str] = None,
    ttl_hours: int = 1,
) -> Dict[str, Any]:
    """Generates and signs the Closed Payment Mandate bound to the finalized checkout hash."""
    agent_key = get_agent_key()
    mandate_id = f"closed_pay_{uuid.uuid4().hex[:12]}"
    ref = payment_reference or f"pref_{uuid.uuid4().hex[:10]}"
    now = int(time.time())
    exp = now + (ttl_hours * 3600)

    claims = {
        "mandate_id": mandate_id,
        "open_payment_mandate_id": open_payment_mandate_id,
        "vct": "https://ap2.dev/vct/closed_payment_mandate_v1",
        "checkout_hash": checkout_hash,
        "amount": float(amount),
        "currency": currency,
        "payee": payee,
        "payment_method": payment_method,
        "payment_reference": ref,
        "nonce": uuid.uuid4().hex,
        "aud": "payment_processor",
        "iat": now,
        "exp": exp,
    }

    token = jwt.JWT(
        header={"alg": "ES256", "kid": agent_key.key_id, "typ": "JWT"},
        claims=claims,
    )
    token.make_signed_token(agent_key)
    signed_jwt = token.serialize()

    return {
        "mandate_id": mandate_id,
        "token": signed_jwt,
        "payload": claims,
        "checkout_hash": checkout_hash,
        "payment_reference": ref,
    }


def create_checkout_receipt(
    mandate_id: str,
    checkout_hash: str,
    merchant_id: str,
) -> Dict[str, Any]:
    """Merchant signs Checkout Receipt confirming the checkout session is verified."""
    merchant_key = get_merchant_key(merchant_id)
    receipt_id = f"rcpt_chk_{uuid.uuid4().hex[:10]}"
    now = time.time()

    claims = {
        "receipt_id": receipt_id,
        "mandate_id": mandate_id,
        "checkout_hash": checkout_hash,
        "merchant_id": merchant_id,
        "status": "VERIFIED",
        "timestamp": now,
    }

    token = jwt.JWT(
        header={"alg": "ES256", "kid": merchant_key.key_id},
        claims=claims,
    )
    token.make_signed_token(merchant_key)

    return {
        "receipt_id": receipt_id,
        "jwt": token.serialize(),
        "status": "VERIFIED",
        "merchant_id": merchant_id,
    }


def create_payment_receipt(
    closed_payment_mandate_id: str,
    checkout_hash: str,
    order_id: str,
    payment_id: str,
    amount: float,
    currency: str,
    merchant_id: str,
) -> Dict[str, Any]:
    """Issues immutable payment receipt for finalized capture."""
    merchant_key = get_merchant_key(merchant_id)
    receipt_id = f"rcpt_pay_{uuid.uuid4().hex[:10]}"
    now = time.time()

    claims = {
        "receipt_id": receipt_id,
        "closed_payment_mandate_id": closed_payment_mandate_id,
        "checkout_hash": checkout_hash,
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": amount,
        "currency": currency,
        "status": "CAPTURED",
        "timestamp": now,
    }

    token = jwt.JWT(
        header={"alg": "ES256", "kid": merchant_key.key_id},
        claims=claims,
    )
    token.make_signed_token(merchant_key)

    return {
        "receipt_id": receipt_id,
        "jwt": token.serialize(),
        "status": "CAPTURED",
        "order_id": order_id,
        "payment_id": payment_id,
    }


def authorize_user_mandates(intent: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Creates bounded Open Checkout and Open Payment Mandates from user intent."""
    max_price = float(intent.get("max_price", 5000.0))
    currency = intent.get("currency", "INR")
    auto_purchase = intent.get("auto_purchase", True)

    open_checkout = create_open_checkout_mandate(
        description=intent.get("description", "Autonomous purchase"),
        max_price=max_price,
        currency=currency,
        brand=intent.get("brand"),
        size=intent.get("size"),
        color=intent.get("color"),
        quantity=int(intent.get("quantity", 1)),
        allowed_merchants=intent.get("allowed_merchants"),
        auto_purchase=auto_purchase,
    )

    open_payment = create_open_payment_mandate(
        open_checkout_token_hash=open_checkout["token_hash"],
        max_amount=max_price,
        currency=currency,
        allowed_merchants=intent.get("allowed_merchants"),
    )

    return open_checkout, open_payment
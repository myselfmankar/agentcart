"""Deterministic AP2 Mandate Verifier.

Deterministically verifies AP2 mandates, hash bindings, and budget bounds:
- Root open checkout and payment bounds
- Merchant checkout session integrity
- Payment authorization bounds
"""

import hashlib
import json
import time
from typing import Any

from jwcrypto import jwt
from pydantic import BaseModel, Field

from app.modules.ap2.keys import get_agent_key, get_agent_provider_key, get_merchant_key


class VerificationResult(BaseModel):
    allowed: bool
    code: str
    stage: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class DeterministicAP2Verifier:
    """Deterministic cryptographic and policy verifier for AP2 mandates."""

    def __init__(self):
        self._consumed_mandates = set()

    def mark_mandate_consumed(self, mandate_id: str) -> None:
        """Marks a closed mandate as consumed to prevent replay attacks."""
        self._consumed_mandates.add(mandate_id)

    def is_mandate_consumed(self, mandate_id: str) -> bool:
        return mandate_id in self._consumed_mandates

    def verify_open_mandate(self, mandate_token: str) -> VerificationResult:
        """Verifies root signature and expiry in an Open Mandate."""
        provider_key = get_agent_provider_key()
        try:
            verified_jwt = jwt.JWT()
            verified_jwt.deserialize(mandate_token, key=provider_key)
            claims = json.loads(verified_jwt.claims)
        except Exception as e:
            err_msg = str(e).lower()
            if "expired" in err_msg or "jwtexpired" in type(e).__name__.lower():
                return VerificationResult(
                    allowed=False,
                    code="OPEN_MANDATE_EXPIRED",
                    stage="open_mandate",
                    message=f"Open Mandate is expired: {e}",
                    details={"error": str(e)},
                )
            return VerificationResult(
                allowed=False,
                code="OPEN_MANDATE_INVALID",
                stage="open_mandate",
                message=f"Cryptographic verification of Open Mandate failed: {e}",
                details={"error": str(e)},
            )

        now = int(time.time())
        exp = claims.get("exp", 0)
        if exp and now > exp:
            return VerificationResult(
                allowed=False,
                code="OPEN_MANDATE_EXPIRED",
                stage="open_mandate",
                message=f"Open Mandate expired at {exp}, current time is {now}",
            )

        return VerificationResult(
            allowed=True,
            code="OK",
            stage="open_mandate",
            message="Open Mandate cryptographically valid",
            details=claims,
        )

    def verify_closed_checkout_mandate(
        self,
        closed_checkout_token: str,
        open_checkout_claims: dict[str, Any],
        authoritative_checkout_jwt: str,
    ) -> VerificationResult:
        """Verifies closed checkout mandate matches merchant hash and intent limits."""
        agent_key = get_agent_key()
        try:
            verified_jwt = jwt.JWT()
            verified_jwt.deserialize(closed_checkout_token, key=agent_key)
            closed_claims = json.loads(verified_jwt.claims)
        except Exception as e:
            return VerificationResult(
                allowed=False,
                code="CLOSED_CHECKOUT_SIGNATURE_INVALID",
                stage="closed_checkout",
                message=f"Failed to verify Closed Checkout Mandate signature: {e}",
            )

        # Verify hash match
        actual_hash = hashlib.sha256(authoritative_checkout_jwt.encode("utf-8")).hexdigest()
        mandate_hash = closed_claims.get("checkout_hash")
        if actual_hash != mandate_hash:
            return VerificationResult(
                allowed=False,
                code="CHECKOUT_HASH_MISMATCH",
                stage="closed_checkout",
                message="Closed Checkout Mandate checkout_hash does not match authoritative checkout",
            )

        # Deserialize authoritative checkout JWT to verify merchant signature & price bound
        merchant_id = closed_claims.get("merchant_id", "")
        merchant_key = get_merchant_key(merchant_id)
        chk_jwt = jwt.JWT()
        chk_jwt.deserialize(authoritative_checkout_jwt, key=merchant_key)
        chk_data = json.loads(chk_jwt.claims)

        final_price = float(chk_data.get("total_amount", chk_data.get("final_total", 0.0)))
        max_budget = float(open_checkout_claims.get("max_price", 0.0))
        if final_price > max_budget:
            return VerificationResult(
                allowed=False,
                code="CHECKOUT_EXCEEDS_BUDGET",
                stage="closed_checkout",
                message=f"Checkout total ₹{final_price:,.2f} exceeds Open Mandate budget ₹{max_budget:,.2f}",
            )

        return VerificationResult(
            allowed=True,
            code="OK",
            stage="closed_checkout",
            message="Closed Checkout Mandate verified successfully",
            details={"final_price": final_price, "max_budget": max_budget},
        )

    def verify_payment_authorization(
        self,
        closed_payment_token: str,
        open_payment_claims: dict[str, Any],
        expected_amount: float,
        expected_payee: str,
        expected_checkout_hash: str,
    ) -> VerificationResult:
        """Verifies closed payment mandate conforms to open limits and checkout."""
        agent_key = get_agent_key()
        try:
            verified_jwt = jwt.JWT()
            verified_jwt.deserialize(closed_payment_token, key=agent_key)
            claims = json.loads(verified_jwt.claims)
        except Exception as e:
            return VerificationResult(
                allowed=False,
                code="CLOSED_PAYMENT_SIGNATURE_INVALID",
                stage="closed_payment",
                message=f"Failed to verify Closed Payment Mandate: {e}",
            )

        if claims.get("checkout_hash") != expected_checkout_hash:
            return VerificationResult(
                allowed=False,
                code="CHECKOUT_HASH_MISMATCH",
                stage="closed_payment",
                message="Closed Payment Mandate not bound to current checkout session",
            )

        mandate_amount = float(claims.get("amount", 0.0))
        max_authorized = float(open_payment_claims.get("max_amount", 0.0))
        if mandate_amount > max_authorized:
            return VerificationResult(
                allowed=False,
                code="PAYMENT_EXCEEDS_OPEN_MANDATE",
                stage="closed_payment",
                message=f"Mandate payment amount ₹{mandate_amount:,.2f} exceeds authorized cap ₹{max_authorized:,.2f}",
            )

        if round(mandate_amount, 2) != round(expected_amount, 2):
            return VerificationResult(
                allowed=False,
                code="AMOUNT_MISMATCH",
                stage="closed_payment",
                message=f"Mandate amount ₹{mandate_amount:,.2f} does not match expected ₹{expected_amount:,.2f}",
            )

        return VerificationResult(
            allowed=True,
            code="OK",
            stage="closed_payment",
            message="Payment authorization verified successfully",
            details={"amount": mandate_amount, "payee": expected_payee},
        )


# Global singleton
deterministic_verifier = DeterministicAP2Verifier()
"""Deterministic Policy Engine for Autonomous Commerce.

GATES ALL MONEY-MOVING ACTIONS.
The deterministic policy engine must approve every transaction before checkout creation
or payment execution. No LLM output or prompt injection can bypass these constraints.
"""

from typing import Any

from app.modules.acp.models import Item
from app.modules.audit.trail import audit_trail


class PolicyDecision:
    """Result of a deterministic policy evaluation."""

    def __init__(self, allowed: bool, violations: list[str] | None = None, details: dict[str, Any] | None = None):
        self.allowed = allowed
        self.violations = violations or []
        self.details = details or {}

    def __bool__(self):
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": self.violations,
            "details": self.details,
        }


class PolicyEngine:
    """Enforces deterministic constraints on candidate offers and payment actions."""

    def __init__(self):
        self._processed_payment_references: set[str] = set()

    def evaluate_offer(
        self,
        item: Item,
        user_intent: dict[str, Any],
        objective_id: str = "obj_default"
    ) -> PolicyDecision:
        """Deterministically evaluates if an offer is eligible for purchase."""
        violations = []
        details = {
            "item_id": item.id,
            "item_name": item.name,
            "item_price": item.price,
            "stock": item.stock,
            "user_max_budget": user_intent.get("max_price"),
            "currency": item.currency,
        }

        # 1. Price constraint: Hard ceiling
        max_price = user_intent.get("max_price")
        if max_price is not None and item.price > float(max_price):
            violations.append(
                f"PRICE_EXCEEDED: Item price Rs. {item.price:,.2f} exceeds user budget of Rs. {float(max_price):,.2f}"
            )

        # 2. Stock constraint: Must be in stock
        req_qty = int(user_intent.get("quantity", 1))
        if item.stock < req_qty:
            violations.append(
                f"OUT_OF_STOCK: Requested quantity {req_qty} exceeds available stock ({item.stock})"
            )

        # 3. Variant constraints (Size, Color, Brand)
        required_brand = user_intent.get("brand")
        if required_brand and required_brand.lower() not in item.brand.lower():
            violations.append(
                f"BRAND_MISMATCH: Requested brand '{required_brand}' does not match item brand '{item.brand}'"
            )

        required_size = user_intent.get("size")
        if required_size is not None:
            item_size = item.attributes.get("size")
            if item_size is not None and str(item_size) != str(required_size):
                violations.append(
                    f"VARIANT_MISMATCH: Requested size {required_size} does not match item size {item_size}"
                )

        required_color = user_intent.get("color")
        if required_color is not None:
            item_color = item.attributes.get("color", "").lower()
            if required_color.lower() not in item_color:
                violations.append(
                    f"COLOR_MISMATCH: Requested color '{required_color}' does not match item color '{item_color}'"
                )

        # 4. Autonomous purchase consent
        if not user_intent.get("auto_purchase", True):
            violations.append(
                "USER_CONFIRMATION_REQUIRED: Autonomous purchase not authorized by user intent"
            )

        # 5. Merchant whitelist constraint
        allowed_merchants = user_intent.get("allowed_merchants")
        merchant_id = item.attributes.get("merchant_id")
        merchant_name = item.attributes.get("merchant_name")
        if (
            allowed_merchants
            and (merchant_id or merchant_name)
            and merchant_id not in allowed_merchants
            and merchant_name not in allowed_merchants
        ):
            violations.append(
                f"MERCHANT_NOT_ALLOWED: Merchant '{merchant_id or merchant_name}' is not in allowed list: {allowed_merchants}"
            )

        # 6. Currency constraint
        expected_currency = user_intent.get("currency", "INR")
        if item.currency.upper() != expected_currency.upper():
            violations.append(
                f"CURRENCY_MISMATCH: Offer currency '{item.currency}' does not match requested '{expected_currency}'"
            )

        # 7. Delivery deadline constraint
        max_delivery_days = user_intent.get("max_delivery_days")
        if max_delivery_days is not None:
            try:
                max_days = int(max_delivery_days)
                deliv_info = item.attributes.get("delivery", {})
                std_days = int(deliv_info.get("standard_days", 4))
                exp_days = int(deliv_info.get("express_days", std_days))
                fastest_days = min(std_days, exp_days)
                if fastest_days > max_days:
                    violations.append(
                        f"DELIVERY_TOO_SLOW: Fastest delivery ({fastest_days} days) exceeds requested deadline of {max_days} days"
                    )
            except (ValueError, TypeError):
                pass

        allowed = len(violations) == 0
        decision = PolicyDecision(allowed=allowed, violations=violations, details=details)

        audit_trail.log_event(
            event_type="POLICY_EVALUATED",
            objective_id=objective_id,
            details=decision.to_dict(),
            level="INFO" if allowed else "WARNING"
        )
        return decision

    def evaluate_payment(
        self,
        amount: float,
        authorized_max_amount: float,
        currency: str = "INR",
        payment_reference: str | None = None,
        objective_id: str = "obj_default"
    ) -> PolicyDecision:
        """Deterministic safety check executed immediately prior to payment execution."""
        violations = []

        # 1. Budget cap check against Open Mandate
        if amount > authorized_max_amount:
            violations.append(
                f"PAYMENT_EXCEEDS_MANDATE: Requested charge Rs. {amount:,.2f} exceeds authorized limit Rs. {authorized_max_amount:,.2f}"
            )

        # 2. Idempotency / replay protection
        if payment_reference:
            if payment_reference in self._processed_payment_references:
                violations.append(
                    f"DUPLICATE_PAYMENT_ATTEMPT: Payment reference '{payment_reference}' has already been processed"
                )
            else:
                self._processed_payment_references.add(payment_reference)

        allowed = len(violations) == 0
        decision = PolicyDecision(
            allowed=allowed,
            violations=violations,
            details={
                "requested_amount": amount,
                "authorized_max": authorized_max_amount,
                "currency": currency,
                "reference": payment_reference,
            }
        )

        audit_trail.log_event(
            event_type="PAYMENT_POLICY_CHECK",
            objective_id=objective_id,
            details=decision.to_dict(),
            level="INFO" if allowed else "ERROR"
        )
        if allowed:
            audit_trail.log_event(
                event_type="payment.authorized",
                objective_id=objective_id,
                details={"amount": amount, "currency": currency, "reference": payment_reference},
            )
        return decision


# Global singleton
policy_engine = PolicyEngine()
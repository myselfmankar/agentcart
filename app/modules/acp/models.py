"""ACP (Agentic Commerce Protocol) Models.

Defines standardized commerce data structures for agent-to-merchant transactions:
- Catalog items and attributes
- Cart line items
- Fulfillment options
- Payment allowances (delegated payment model)
- Checkout sessions, authoritative tokens, and statuses
- Payment confirmation and receipts
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CheckoutStatus(str, Enum):
    DRAFT = "draft"
    READY_FOR_PAYMENT = "ready_for_payment"
    PROCESSING_PAYMENT = "processing_payment"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class FulfillmentOption(BaseModel):
    id: str
    name: str
    cost: float = 0.0
    estimated_days: int = 3


class Item(BaseModel):
    id: str
    name: str
    brand: str
    price: float
    currency: str = "INR"
    stock: int
    attributes: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class LineItem(BaseModel):
    item: Item
    quantity: int = 1
    total: float


class PaymentAllowance(BaseModel):
    """Explicit ACP delegated payment allowance model."""
    max_amount: float
    currency: str = "INR"
    expiry: float
    checkout_session_id: str
    merchant_id: str
    one_time_usage: bool = True
    idempotency_key: str
    risk_signals: dict[str, Any] = Field(default_factory=dict)


class AuthoritativeCheckoutToken(BaseModel):
    """Merchant-signed authoritative token securing checkout integrity."""
    session_id: str
    merchant_id: str
    checkout_jwt: str
    checkout_hash: str
    total_amount: float
    currency: str
    expires_at: float


class CheckoutSession(BaseModel):
    id: str
    merchant_id: str
    merchant_name: str
    line_items: list[LineItem]
    currency: str = "INR"
    subtotal: float
    tax: float = 0.0
    shipping: float = 0.0
    total_amount: float
    status: CheckoutStatus = CheckoutStatus.DRAFT
    fulfillment: FulfillmentOption | None = None
    payment_order_id: str | None = None
    payment_id: str | None = None
    checkout_jwt: str | None = None
    checkout_hash: str | None = None
    payment_allowance: PaymentAllowance | None = None
    created_at: float
    expires_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentConfirmation(BaseModel):
    success: bool
    order_id: str
    payment_id: str | None = None
    amount: float
    currency: str
    status: str
    timestamp: float


class MerchantProposal(BaseModel):
    """ACP Commercial Proposal submitted by a merchant agent to the shopping buyer agent."""
    merchant_id: str
    merchant_name: str
    item: Item
    base_price: float
    discount_type: str = "none"  # "flat", "percentage", "negotiable", "none"
    discount_amount: float = 0.0
    proposed_price: float
    currency: str = "INR"
    stock: int
    is_in_stock: bool
    standard_delivery_days: int = 4
    express_delivery_days: int = 2
    express_delivery_fee: float = 0.0
    is_negotiable: bool = False
    minimum_price_floor: float | None = None
    commercial_pitch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
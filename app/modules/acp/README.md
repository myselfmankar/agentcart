# ACP Protocol: Agentic Commerce (`app/modules/acp`)
### *Standardized Commerce Models & Authoritative Checkout Sessions for AI Agents*

---

## Why This Module Exists

Every online merchant backend has its own custom data structure: Shopify uses GraphQL checkout nodes, WooCommerce uses REST endpoints, and custom retailers use internal schemas.

An autonomous shopping agent cannot be written with hardcoded, store-specific API adapters for thousands of individual merchants. 

The **Agentic Commerce Protocol (ACP)** solves this by establishing a vendor-neutral, machine-readable language for autonomous e-commerce:
- Standardizes how catalogs, variant attributes, and stock quantities are represented (`Item`, `LineItem`).
- Formats dynamic commercial offers and discount proposals (`MerchantProposal`).
- Establishes a verifiable, stateful checkout lifecycle (`CheckoutSession`) signed with merchant cryptographic keys.

---

## How It Works: The ACP Commerce Model

ACP structures commerce into strict, verifiable phases:

```
[Agent Query / Search]
          │
          ▼
   MerchantProposal  ───► Base price, discounts, standard & express delivery timelines
          │
          ▼
   CheckoutSession   ───► Line items, tax, shipping, fulfillment, total amount
          │
          ▼
AuthoritativeCheckout ──► Merchant signs checkout_jwt + checkout_hash (ES256)
          │
          ▼
 PaymentConfirmation ───► Binds Razorpay order_id, payment_id, and settlement status
```

### Core Data Models ([`app/modules/acp/models.py`](file:///d:/_try2/app/modules/acp/models.py))

| Model | Purpose | Key Attributes |
| :--- | :--- | :--- |
| **`Item`** | Canonical product SKU | `id`, `name`, `brand`, `price`, `currency`, `stock`, `attributes` (size, color) |
| **`LineItem`** | Cart line entry | `item: Item`, `quantity: int`, `total: float` |
| **`MerchantProposal`** | Binding commercial offer | `proposal_id`, `merchant_id`, `item`, `base_price`, `proposed_price`, `discount_amount`, `standard_delivery_days`, `express_delivery_days` |
| **`CheckoutSession`** | Formal checkout cart | `id`, `merchant_id`, `line_items`, `subtotal`, `tax`, `shipping`, `total_amount`, `status` (`DRAFT`, `READY_FOR_PAYMENT`, `COMPLETED`), `checkout_jwt`, `checkout_hash` |
| **`AuthoritativeCheckoutToken`** | Merchant cryptographic commitment | `session_id`, `merchant_id`, `checkout_jwt`, `checkout_hash`, `total_amount`, `expires_at` |
| **`PaymentAllowance`** | Delegated spending allowance | `max_amount`, `currency`, `expiry`, `idempotency_key`, `risk_signals` |

---

## Authoritative Signing & Anti-Tampering

One of ACP's most critical innovations is the **Authoritative Checkout Token**:
1. When a merchant creates a checkout session, it computes a SHA-256 hash (`checkout_hash`) over the exact item IDs, quantities, and agreed prices.
2. The merchant signs this hash using its private ECDSA key (`ES256`), producing `checkout_jwt`.
3. The Buyer Agent passes this token to the AP2 verification engine and Razorpay gateway.
4. If an intermediary attempts to tamper with line items or inflate the price, the cryptographic hash fails, terminating the session immediately.

---

## Invariants & Guardrails

- **Zero Arbitrary Mutations**: Once a checkout session status reaches `READY_FOR_PAYMENT`, line items and totals are locked and cannot be edited.
- **Short TTLs**: Checkouts include explicit expiration timestamps (`expires_at`, default 15 minutes) to protect merchants from stale price exposure.
- **Idempotency**: Every payment allowance and session uses unique UUIDs to prevent double billing.

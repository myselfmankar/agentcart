# AP2 Protocol: Agent Payments (`app/modules/ap2`)
### *Cryptographic Mandates & Tamper-Evident Authorizations for AI Commerce*

---

## Why This Module Exists

In human e-commerce, user authorization is granted interactively via credit card numbers, CVVs, and One-Time Passwords (OTPs) sent over SMS. 

In **autonomous agent commerce**, the human is not present during checkout. An autonomous buyer agent needs a cryptographic mechanism to prove:
1. **User Authorization**: The user genuinely gave permission to buy within specific bounds (max price, product category, merchant whitelist).
2. **Merchant Commitment**: The merchant cannot secretly increase the price or swap out items once the buyer agrees to purchase.
3. **Payment Integrity**: The payment processor (Razorpay) receives mathematical proof that the amount charged corresponds strictly to the verified checkout items.

The **Agent Payments Protocol (AP2)** solves this problem using **cryptographic mandates** signed with ES256 (ECDSA P-256 + SHA-256) JSON Web Tokens (JWTs).

---

## How It Works: The 4-Stage Mandate Lifecycle

AP2 follows a strict 4-stage lifecycle moving from open bounds to closed cryptographic commitments:

```
[User Intent]
      │
      ▼
1. Open Checkout Mandate  ───► Defines bounds (Max Price Rs. 5,000, Size 10, INR)
2. Open Payment Mandate   ───► Sets payment cap and approved processor ("razorpay")
      │
      ▼  (Merchant negotiates & creates authoritative checkout)
      │
3. Closed Checkout Mandate ──► Binds exact items & price to merchant's checkout_hash
4. Closed Payment Mandate  ──► Authorizes exact settlement to payee with nonce
      │
      ▼
[Payment Captured via Razorpay]
      │
      ▼
5. Cryptographic Receipts  ──► CheckoutReceipt & PaymentReceipt with audit hashes
```

### Mandate Models ([`app/modules/ap2/mandates.py`](file:///d:/_try2/app/modules/ap2/mandates.py))

| Mandate Type | Signed By | Purpose & Contents |
| :--- | :--- | :--- |
| **Open Checkout Mandate** | User / Agent | Encodes intent bounds: `max_price`, `category`, `brand`, `size`, `color`, `allowed_merchants`, and expiration (`exp`). |
| **Open Payment Mandate** | Buyer Agent | Encodes payment authority: `max_amount`, `allowed_payment_methods: ["razorpay"]`, and authorization key confirmation (`cnf`). |
| **Closed Checkout Mandate**| Buyer Agent | Encodes the finalized cart: references `open_checkout_mandate_id`, merchant ID, `checkout_jwt`, and SHA-256 `checkout_hash`. |
| **Closed Payment Mandate** | Buyer Agent | Encodes the single-use execution: exact `amount`, `payee`, `checkout_hash`, cryptographic `nonce`, and audience `payment_processor`. |
| **Payment Receipt** | Payment Gateway | Proof of settlement containing `razorpay_order_id`, `razorpay_payment_id`, status `CAPTURED`, and audit timestamp. |

---

## Verification Engine ([`app/modules/ap2/verifier.py`](file:///d:/_try2/app/modules/ap2/verifier.py))

The `AP2Verifier` runs deterministic mathematical checks:
1. **Signature Verification**: Validates ES256 signatures against the public JWK of the issuer.
2. **Expiration Enforcement**: Rejects mandates where `iat` or `exp` have lapsed.
3. **Hash Integrity**: Re-hashes the checkout object (`SHA-256`) and verifies it matches `checkout_hash`. If a merchant or proxy attempted to change price by Rs. 1, the hash mismatch causes instant rejection.
4. **Amount Binding**: Ensures `amount <= max_amount` authorized in the parent open mandate.

---

## Invariants & Guardrails

- **Immutable Proof**: Mandates are cryptographically signed JWTs; once serialized, any alteration invalidates the signature.
- **Single-Use Nonce**: Closed mandates include a unique nonce to prevent replay attacks across different orders.
- **Zero Raw Credential Exposure**: No credit card PANs, passwords, or bank tokens are ever shared across the network.

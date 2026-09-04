# Autonomous Merchant Agents (`app/merchants`)
### *Independent Seller Representatives, Dynamic Pricing & Authoritative Checkout Assembly*

---

## Why This Module Exists

In standard e-commerce, websites are passive databases. If a buyer wants a discount, they must search for coupon codes. If two stores compete, they cannot negotiate dynamically with the buyer in real time.

In **autonomous commerce**, merchants are represented by active **Autonomous Seller Agents**:
- **Independent Business Objectives**: Each store agent has its own policy, margin floor, and fulfillment promises.
- **Dynamic 1-to-1 Negotiation**: Stores can counter-offer to win a deal against a competitor, without sacrificing profitability.
- **Cryptographic Authority**: Merchants hold their own private signing keys to generate authoritative ACP checkout sessions and AP2 cart mandates.
- **Isolated State**: Stores maintain separate catalog databases and policies (`merchants/merchant_{a,b,c}/`).

---

## How It Works: The Merchant Lifecycle

```
[Buyer Query over A2A]
           │
           ▼
  create_proposal(query, filters)
   ├── Loads live inventory from catalog.json
   ├── Inspects fulfillment & pricing policy from policy.json
   └── Formulates binding MerchantProposal (base price, discount, delivery)
           │
           ▼ (Buyer counters: "ShoeKart quoted Rs. 4,700, can you beat it?")
  negotiate(proposal_id, competing_price)
   ├── Checks allows_negotiation policy
   ├── Computes margin_floor_discount
   └── Formulates CounterProposal (e.g. Rs. 4,650)
           │
           ▼ (Buyer selects winning offer)
  create_checkout(item_id, quantity, agreed_price)
   └── Assembles CheckoutSession and signs ES256 checkout_hash
```

### The Three Calibrated Merchants

| Merchant | ID | Commercial Objective | Delivery Speed | Negotiation Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **UrbanKicks** | `merchant_a` | Streetwear & utility apparel; volume-driven. | 2 to 4 Days | Moderate discounts up to margin floor. |
| **ShoeKart** | `merchant_b` | Performance running; brand protection. | 3 to 5 Days | Non-negotiable; firm premium pricing. |
| **FastFeet** | `merchant_c` | Athletic footwear & gym tees; competitive. | 2 to 4 Days | Aggressive dynamic counter-negotiations. |

### Core Architecture ([`base_merchant_agent.py`](file:///d:/_try2/app/merchants/base_merchant_agent.py))

1. **`get_agent_card()`**:
   Generates a standardized A2A `AgentCard` advertising the store's identity, endpoint URL, supported protocols (`["a2a", "acp", "ap2"]`), and callable skills.

2. **`create_proposal(query, filters)`**:
   Leverages the Gemini LLM to interpret natural language queries against the store's full catalog. Selects matching variants, applies store discounts, and attaches delivery timeline commitments.

3. **`negotiate(proposal_id, competing_price)`**:
   Evaluates a competing counter-offer from the buyer. If `policy["negotiation_policy"]["allows_negotiation"]` is true, it undercuts the competitor as long as the proposed price remains above the store's `min_margin_price`.

4. **`create_checkout(...)` & `complete_checkout(...)`**:
   Constructs the authoritative ACP checkout session, binds the agreed price, locks inventory, and decrements stock once a verified Razorpay payment ID is received.

---

## Invariants & Guardrails

- **Hard Margin Floors**: An LLM seller agent can NEVER negotiate below the deterministic `margin_floor_discount` defined in `policy.json`.
- **Authoritative Cryptography**: Checkout totals and SKU IDs are hashed and signed with the merchant's private key; the buyer cannot tamper with prices.
- **Stock Decrement Safety**: Stock is only permanently decremented upon receipt of a valid Razorpay payment capture identifier.

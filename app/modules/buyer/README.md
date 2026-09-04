# Buyer Ledger & Treasury (`app/modules/buyer`)
### *Deterministic Spending Authority, Velocity Limits & Double-Entry Ledger*

---

## Why This Module Exists

If an autonomous shopping agent had uncontrolled direct access to bank rails, an algorithmic bug or runaway loop could drain the user's entire bank account in seconds.

The **Buyer Ledger & Treasury Module** provides a strict financial buffer:
- **Pre-Allocated Spending Authority**: The agent operates strictly within a pre-authorized treasury balance (e.g. Rs. 50,000).
- **Per-Transaction Velocity Caps**: Even if the available balance is Rs. 50,000, a per-transaction limit (e.g. Rs. 10,000) prevents catastrophic single-order overspending.
- **Double-Entry Ledger Integrity**: Every debit is atomically matched to an order ID, payment ID, and merchant ID.
- **Overdraft Protection**: Balance checks are purely mathematical and local; if balance is insufficient, checkout is blocked with `INSUFFICIENT_FUNDS` before any API call is sent to Razorpay.

---

## How It Works

```
[Candidate Checkout Session]
               │
               ▼
       can_spend(amount)
        ├── Check 1: amount <= available_balance
        └── Check 2: amount <= per_transaction_limit
               │
       ┌───────┴────────┐
       ▼                ▼
   [Approved]       [Rejected]
       │                │
       ▼                ▼
 Razorpay Payment   Transitions Objective to AWAITING_FUNDS
       │
       ▼
 record_debit() ───► Atomically writes transaction to data/buyer/ledger.json
                     and updates data/buyer/balance.json
```

### Core Operations ([`ledger.py`](file:///d:/_try2/app/modules/buyer/ledger.py))

| Method | Description | Guardrail / Behavior |
| :--- | :--- | :--- |
| **`can_spend(amount)`** | Verifies spending capacity before checkout. | Returns `BuyerLimitDecision(allowed: bool)`. Computes shortfall if funds are insufficient. |
| **`record_debit(...)`** | Records payment settlement upon capture. | Atomically decrements `available_balance` and records `razorpay_order_id`, `razorpay_payment_id`, and `merchant_id`. |
| **`credit_balance(amount)`** | Deposits funds into the treasury. | Increases balance and emits `FUNDS_ADDED` event across the Event Bus, waking up dormant watch objectives. |
| **`reset_balance(...)`** | Resets testing treasury to defaults. | Used for test suite setup and calibration. |

---

## Invariants & Guardrails

- **Atomic File Writes**: Ledger balances are written to disk using temporary file replacement patterns to prevent corruption during unexpected shutdowns.
- **Strict Non-Negative Balances**: Debits that would result in a negative balance are rejected at the code level.
- **Immutable Log**: `ledger.json` is append-only; historical transaction records cannot be modified or deleted.

# AWAITING_FUNDS State Machine & Razorpay Webhook Architecture

This document defines the separation of market-driven monitoring (`WATCHING`) from buyer-driven funding (`AWAITING_FUNDS`), and maps how **Razorpay / RazorpayX Webhooks** drive autonomous agent state transitions.

---

## 1. Architectural Philosophy: Market vs. Wallet

Historically, agents combined all waiting conditions into a single generic `WATCHING` state. This created operational ambiguity:

| Condition | Cause | Waiting On | Correct State |
|---|---|---|---|
| Price too high / Out of stock | Sellers do not have a qualifying offer | **Merchants** (restocks, price cuts, flash sales) | **`WATCHING`** |
| Offer matched, but user balance is low | Terms negotiated, checkout assembled, but wallet needs funds | **Buyer / User** (deposit funds into RazorpayX) | **`AWAITING_FUNDS`** |

```text
                                 [ BUYER INTENT ]
                                        │
                                        ▼
                             [ EVALUATING PROPOSALS ]
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 │                                             │
      No qualifying offers found                       Qualifying offer found!
                 │                                             │
                 ▼                                             ▼
          [ WATCHING ]                                [ CHECK BUYER BALANCE ]
    (Waiting on Merchants:                                     │
   price drops, restocks, etc.)                 ┌──────────────┴──────────────┐
                                                │                             │
                                         Balance is LOW                 Balance OK
                                                │                             │
                                                ▼                             ▼
                                       [ AWAITING_FUNDS ]             [ CHECKING_OUT ]
                                     (Waiting on User:                        │
                                   top-up on RazorpayX)                       ▼
                                                                        [ COMPLETED ]
```

---

## 2. Zero-Trust Financial Isolation (Privacy & Security)

To make the agent safe for any user:
1. **The LLM never knows total user wealth**: The model is never told the user's bank balance or total savings. It only receives the specific task budget (`max_budget`).
2. **Dedicated RazorpayX Vault**: The user maintains an isolated balance in RazorpayX (e.g. `account_number: 2323230040010540`).
3. **Deterministic Spending Gate**: The Policy Engine and RazorpayX verify whether funds exist before signing payment mandates.
4. **Clean Halting**: If funds are insufficient, the agent transitions to **`AWAITING_FUNDS`** and halts without risking overdrafts or rogue spending.

---

## 3. Razorpay & RazorpayX Webhook Event Mapping

Razorpay webhooks act as the asynchronous truth for real-world money movement. Here is how Razorpay events connect directly to agent state transitions:

```text
   Razorpay / RazorpayX Webhook
                │
                ▼
   ┌────────────────────────┐
   │ HMAC-SHA256 Validation │  (X-Razorpay-Signature)
   └────────────┬───────────┘
                │
                ▼
   ┌────────────────────────┐
   │ Idempotency Check      │  (Deduplicate event_id)
   └────────────┬───────────┘
                │
    ┌───────────┴───────────────────────────────┐
    │                                           │
[virtual_account.credited]              [payment.captured / payout.processed]
    │                                           │
    ▼                                           ▼
Deposit to BuyerLedger                  Reconcile debit & order
Publish `BALANCE_CHANGED`               Transition to `COMPLETED`
    │                                           │
    ▼                                           ▼
Wake up `AWAITING_FUNDS` objectives!    Generate Cryptographic Receipts
Execute pending checkout!
```

### Event Specification Table

| Razorpay Webhook Event | Source | Payload Data | Agent Action & State Transition |
|---|---|---|---|
| **`virtual_account.credited`** | Razorpay Smart Collect | `amount`, `customer_id`, `payment_id` | **Top-Up Detected**: Calls `buyer_ledger.deposit()`. Publishes `BALANCE_CHANGED` on `event_bus`. Wakes up all objectives in **`AWAITING_FUNDS`** to finalize checkout. |
| **`payout.processed`** | RazorpayX | `payout_id`, `fund_account_id`, `amount` | **Disbursal Complete**: Confirms money settled to the merchant's fund account (UPI/IMPS). |
| **`payout.queued`** | RazorpayX (`queue_if_low_balance`) | `payout_id`, `status: queued` | **Queued in RazorpayX**: Transitions objective to **`AWAITING_FUNDS`** until account balance is topped up. |
| **`payout.failed` / `payout.rejected`** | RazorpayX | `payout_id`, `error_description` | **Payment Failed**: Transitions objective to `FAILED`. Emits audit log. |
| **`payment.captured`** | Razorpay Gateway | `payment_id`, `order_id`, `amount` | **Payment Success**: Verifies payment signature and transitions objective to `COMPLETED`. |
| **`payment.failed`** | Razorpay Gateway | `payment_id`, `error_code`, `description` | **Decline**: Transitions objective to `FAILED`. |

---

## 4. Lifecycle Walkthrough: How Awaiting Funds Works

1. **User Request**: `"Buy Adidas blue sneakers, size 10, under 5000"`
2. **Discovery & Negotiation**: Winning offer selected from FastFeet for **₹4,650**.
3. **Limit Check**: Current buyer balance in RazorpayX is **₹1,500**.
4. **State Transition**:
   - Old status: `EVALUATING`
   - New status: **`AWAITING_FUNDS`**
   - Message: *"Offer found at Rs. 4,650, but available balance is Rs. 1,500. Shortfall is Rs. 3,150. Paused in AWAITING_FUNDS."*
5. **Top-Up Occurs**:
   - User deposits ₹5,000 on `x.razorpay.com` (or via UPI to virtual account).
   - Razorpay webhook `virtual_account.credited` arrives (or local `deposit()` occurs).
6. **Reactive Wakeup**:
   - Event `BALANCE_CHANGED` triggers `ShoppingAgentOrchestrator.handle_merchant_event`.
   - The orchestrator finds the objective in **`AWAITING_FUNDS`**, verifies new balance (₹6,500 >= ₹4,650), executes checkout, captures Razorpay payment, and transitions to **`COMPLETED`**!

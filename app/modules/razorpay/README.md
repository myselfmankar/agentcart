# Razorpay Gateway & MCP Adapter (`app/modules/razorpay`)
### *Autonomous Financial Settlement, Test Mode Orders & Verifiable Payouts*

---

## Why This Module Exists

Autonomous commerce cannot stop at generating recommendations—it must complete the monetary loop. However, exposing unrestricted payment APIs directly to an LLM creates enormous financial security risks.

The **Razorpay Gateway Module** provides a controlled, sandboxed payment adapter:
- **Test Mode by Design**: Safely executes orders and payouts in Razorpay Test Sandbox without risk of real capital loss.
- **Protocol & Unit Abstraction**: Seamlessly converts commercial amounts into integer subunits (e.g. Rs. 5,000 -> 500,000 paise).
- **Dual MCP & SDK Execution**: Directly integrates with the official Razorpay Model Context Protocol (MCP) server or the official `razorpay` Python SDK, with automatic local mock fallbacks for offline testing.
- **Cryptographic Webhook Verification**: Asynchronously captures payment status events and verifies HMAC-SHA256 signatures before triggering downstream fulfillments.

---

## How It Works

```
[Buyer Agent (Post-Policy Approval)]
                 │
                 ├── 1. create_order(amount_inr, receipt, notes)
                 ▼
       [Razorpay Sandbox / Test Mode]
        ├── Creates Order: order_QW89xyz (Status: created)
        │
        ├── 2. execute_payout(merchant_id, amount_inr)
        ▼
       [Merchant Settlement Rails]
        ├── Dispatches Payout: pout_ABC123 (Status: processed)
        │
        ├── 3. Asynchronous Webhook Notification
        ▼
       [Webhook Handler]
        └── Verifies HMAC-SHA256 signature -> triggers order completion
```

### Key Components

1. **`RazorpayClientAdapter` ([`client.py`](file:///d:/_try2/app/modules/razorpay/client.py))**:
   - `create_order()`: Calls `razorpay.Order.create` with amount converted to paise and currency `INR`.
   - `execute_payout()`: Directs funds to the winning merchant account via RazorpayX payout APIs or test simulations.
   - `fetch_order()` & `fetch_payment()`: Verifies live status and payment capture details.

2. **Razorpay MCP Client ([`mcp_client.py`](file:///d:/_try2/app/modules/razorpay/mcp_client.py))**:
   - Connects to Razorpay's MCP Server over stdio / JSON-RPC.
   - Dispatches structured tool calls (`razorpay_create_order`, `razorpay_fetch_payment`).

3. **Webhook Verification ([`webhooks.py`](file:///d:/_try2/app/modules/razorpay/webhooks.py))**:
   - `verify_webhook_signature(payload, signature, secret)`: Computes HMAC-SHA256 signature of the raw body and compares it in constant time against `X-Razorpay-Signature`.
   - Dispatches verified events (`payment.captured`, `order.paid`) to the internal Watch event bus.

---

## Invariants & Guardrails

- **Zero Direct LLM Invocation**: The LLM NEVER calls Razorpay directly; it only requests checkout via the deterministic policy gate.
- **Paise Conversion Integrity**: Financial amounts are strictly validated to prevent floating-point precision errors during currency subunit conversion.
- **Fail-Safe Mock Fallback**: If network connectivity drops or API keys are absent, the system falls back to a deterministic in-memory sandbox without crashing the agent runtime.

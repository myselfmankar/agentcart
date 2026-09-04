# Audit Trail & OpenTelemetry (`app/modules/audit`)
### *Cryptographically Hash-Chained Audit Logging & Explainable AI Decisions*

---

## Why This Module Exists

Autonomous AI that spends real money must never operate as a "black box". 

If a user, regulator, or fraud prevention system asks:
- *"Why did the agent pick FastFeet instead of UrbanKicks?"*
- *"Who authorized the Rs. 4,899 charge?"*
- *"Did the policy engine verify the size and budget constraints before Razorpay was called?"*

The system must provide an immutable, mathematically verifiable answer.

The **Audit Trail Module** guarantees total explainability and non-repudiation:
- **Blockchain-Style Hash Chaining**: Every log event includes a SHA-256 hash of its contents combined with the previous event's hash (`prev_hash`). Any manual editing or record tampering breaks the cryptographic chain.
- **Zero Secret Leakage**: Automatically scrubs private keys, webhook secrets, JWT bearer tokens, and passwords from logs.
- **Google ADK Plugin Integration**: Hooks directly into the Google ADK runtime to monitor agent turns, tool invocations, and state transitions.

---

## How It Works

```
Agent Action (e.g. POLICY_EVALUATED)
               │
               ▼
       audit_trail.log_event(...)
               │
               ├── 1. Sanitize payload (strip keys & secrets)
               ├── 2. Hash payload + prev_hash -> event_hash (SHA-256)
               ├── 3. Append to .logs/audit_trail.jsonl
               └── 4. Stream to Python logging & OpenTelemetry Spans
```

### The Hash Chaining Structure ([`trail.py`](file:///d:/_try2/app/modules/audit/trail.py))

```json
{
  "timestamp": 1741164800.12,
  "iso_time": "2026-09-04 11:06:40",
  "objective_id": "obj_sneakers_01",
  "event_type": "POLICY_EVALUATED",
  "level": "INFO",
  "details": {
    "item_name": "Nike Air Zoom Pegasus",
    "item_price": 4899.0,
    "user_max_budget": 5000.0,
    "allowed": true
  },
  "prev_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "event_hash": "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
}
```

### Core Logged Events

| Event Type | What It Proves |
| :--- | :--- |
| **`INTENT_RECEIVED`** | The raw user query and parsed bounds (budget, size, delivery). |
| **`MERCHANT_PROPOSAL_RECEIVED`** | The exact price and delivery timelines quoted by each merchant. |
| **`POLICY_EVALUATED`** | The deterministic safety verification and any violations detected. |
| **`MANDATE_CREATED`** | The AP2 open or closed cryptographic mandate generation. |
| **`RAZORPAY_ORDER_CREATE_INITIATED`** | The order creation request sent to Razorpay test mode. |
| **`PAYMENT_COMPLETED`** | The verifiable settlement, payout ID, and receipt hash. |

### ADK Plugin Hooks ([`adk_plugin.py`](file:///d:/_try2/app/modules/audit/adk_plugin.py))
Attaches as a lifecycle plugin to Google ADK agents:
- `on_agent_turn_start`: Logs prompt receipt and objective activation.
- `on_tool_call_start`: Captures tool arguments before execution.
- `on_tool_call_finish`: Records tool outputs, execution durations, and errors.

---

## Invariants & Guardrails

- **Append-Only Persistence**: The file `.logs/audit_trail.jsonl` is strictly append-only; entries cannot be altered or overwritten.
- **Fail-Open Logging**: Log errors do not crash payment execution; they fall back safely to standard logging to ensure transaction stability.
- **Tamper Evident**: Modifying a historical line invalidates all subsequent `event_hash`es in the chain.

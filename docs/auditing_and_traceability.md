# Multi-Agent Auditing, Traceability & Evals with Google ADK

This document defines the architectural blueprint and operational guide for implementing **auditing, distributed traceability, and deterministic evaluation** across multi-agent commerce workflows using the **Google Agent Development Kit (ADK)**.

---

## 1. Architectural Overview

Autonomous commerce requires zero-trust verification. When the **Buyer Agent** discovers independent **Merchant Agents**, solicits structured proposals over **A2A**, negotiates pricing, enforces deterministic safety policies, and triggers **Razorpay** payments, every hop must be cryptographically auditable, traceable, and verifiable against regressions.

```text
                      ┌──────────────────────────────────────────────────────────┐
                      │                     ADK Runtime                          │
                      │                                                          │
  User / Intent ────► │  [Buyer Agent] ─── (A2A Client) ───► [Merchant Agents]   │
                      └─────┬───────────────────┬───────────────────┬────────────┘
                            │                   │                   │
                            ▼                   ▼                   ▼
                     1. ADK TRACE        2. ADK STATE        3. ADK EVALS
                   (OpenTelemetry)     (Sessions & DB)    (EvalSet & Trajectory)
                            │                   │                   │
                  • Distributed Spans • Scoped Namespaces • Tool Call Checks
                  • W3C tracecontext  • .adk/session.db   • State Invariant Tests
                  • GenAI SemConv     • Immutable Events  • Policy Regressions
                            ▲                   ▲                   ▲
                            └───────────────────┴───────────────────┘
                                                │
                                    ADK Plugin System (`BasePlugin`)
                                   (Non-invasive lifecycle hooks)
```

---

## 2. ADK Trace: Distributed Tracing & OpenTelemetry (`google.adk.telemetry`)

ADK integrates directly with **OpenTelemetry (OTel)**, implementing the GenAI Semantic Conventions (`GEN_AI_AGENT_NAME`, `GEN_AI_TOOL_NAME`, `GEN_AI_CONVERSATION_ID`).

### 2.1 Cross-Agent A2A Telemetry Instrumentation
A2A message exchanges (proposal requests, negotiations, and ACP checkouts) are instrumented using ADK's native `tracer` to generate parent-child span hierarchies across agent boundaries.

```python
# app/modules/a2a/client.py
from google.adk.telemetry import tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

class A2AClient:
    def negotiate(
        self,
        merchant_id: str,
        proposal: MerchantProposal,
        competing_price: float,
        objective_id: str = "obj_default"
    ) -> Optional[MerchantProposal]:
        """Conducts an A2A negotiation round wrapped in an OpenTelemetry trace span."""
        
        with tracer.start_as_current_span("a2a.negotiate") as span:
            span.set_attribute("a2a.protocol", "A2A/1.0")
            span.set_attribute("a2a.objective_id", objective_id)
            span.set_attribute("a2a.merchant_id", merchant_id)
            span.set_attribute("a2a.initial_price", proposal.proposed_price)
            span.set_attribute("a2a.competing_price", competing_price)

            # Inject W3C traceparent headers to propagate context across network boundaries
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)

            merchant = self.registry.get_merchant(merchant_id)
            if not merchant:
                span.set_attribute("a2a.status", "MERCHANT_NOT_FOUND")
                return None

            counter_proposal = merchant.negotiate(proposal, competing_price=competing_price)

            if counter_proposal and counter_proposal.proposed_price < proposal.proposed_price:
                savings = proposal.proposed_price - counter_proposal.proposed_price
                span.set_attribute("a2a.agreed_price", counter_proposal.proposed_price)
                span.set_attribute("a2a.savings", savings)
                span.set_attribute("a2a.status", "ACCEPTED")
                return counter_proposal

            span.set_attribute("a2a.status", "DECLINED")
            return None
```

### 2.2 Trace Export Modes
Traces can be exported locally for debugging or streamed directly to enterprise observability platforms:

1. **Local Console Exporter**:
   ```bash
   export OTEL_TRACES_EXPORTER=console
   adk web adk_agents/shopping_agent
   ```
2. **Google Cloud Trace**:
   ```bash
   adk web --trace_to_cloud --otel_to_cloud adk_agents/shopping_agent
   ```
3. **OTLP / Jaeger / Collector**:
   ```bash
   export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
   adk web adk_agents/shopping_agent
   ```

---

## 3. ADK State & Session Storage (`google.adk.sessions`)

ADK provides persistent state management with scoped namespaces and an immutable append-only event log.

### 3.1 State Scoping Namespaces

| Scope | Prefix Syntax | Lifecycle & Storage | Usage in Autonomous Commerce |
|---|---|---|---|
| **Session State** | `state["key"]` | Bound to active conversation | Active `objective_id`, candidate proposals, negotiation rounds. |
| **User State** | `state["user:key"]` | Persisted across sessions per user | Buyer wallet balance, max per-transaction limits, authorized mandates. |
| **App State** | `state["app:key"]` | Global across all users and sessions | Registered merchant registry, catalog cache, active flash sales. |
| **Temp State** | `state["temp:key"]` | Current turn / execution only | Intermediate calculation artifacts, uncommitted proposal drafts. |

### 3.2 Accessing & Mutating State in Tools via `ToolContext`
ADK automatically injects `ToolContext` into agent tools. This allows tools to enforce spending authority and persist audit updates directly into the session state:

```python
# adk_agents/shopping_agent/buyer_agent.py
from google.adk.tools import ToolContext

def run_autonomous_purchase(
    query: str = "shoes",
    brand: Optional[str] = None,
    size: Optional[int] = 10,
    color: Optional[str] = "blue",
    max_budget: float = 5000.0,
    tool_context: Optional[ToolContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """Executes purchase with state reading and writing via ToolContext."""
    
    # 1. Read persistent user spending authority from ADK State
    user_balance = 10000.0
    if tool_context:
        user_balance = tool_context.state.get("user:balance", 10000.0)
        tool_context.state["session:current_intent"] = query

    # 2. Execute bounded orchestrator
    result = shopping_orchestrator.execute_intent(
        intent={
            "query": query,
            "brand": brand,
            "size": size,
            "color": color,
            "max_price": min(max_budget, user_balance),
        }
    )

    # 3. Commit state updates upon verified execution
    if tool_context and result.get("success"):
        tool_context.state["user:balance"] = result["remaining_balance"]
        tool_context.state["session:last_order_id"] = result["order_id"]
        tool_context.state["session:last_payment_id"] = result["payment_id"]

    return result
```

### 3.3 The `.adk/session.db` Event Schema
ADK uses SQLite by default (or Cloud SQL / Postgres in production) located at `.adk/session.db`. The core schema guarantees full auditability:

```text
  ┌─────────────────────────────────────────────────────────────┐
  │                           sessions                          │
  ├─────────────────────────────────────────────────────────────┤
  │ app_name | user_id | id (session_id) | state | update_time  │
  └──────────────────────────────┬──────────────────────────────┘
                                 │ 1:N
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                            events                           │
  ├─────────────────────────────────────────────────────────────┤
  │ id | app_name | user_id | session_id | invocation_id        │
  │ timestamp | event_data (User message, LLM thought,          │
  │                         Tool Call, Tool Output)             │
  └─────────────────────────────────────────────────────────────┘
```

#### Auditing the Event Stream:
You can reconstruct any transaction by querying the event log:
```sql
SELECT timestamp, invocation_id, json_extract(event_data, '$.content') 
FROM events 
WHERE session_id = 'your_session_id'
ORDER BY timestamp ASC;
```

---

## 4. ADK Evals: Trajectory & Policy Verification (`google.adk.evaluation`)

ADK Evals evaluate the **multi-step execution trajectory**, **tool arguments**, and **final session state invariants**.

### 4.1 Defining an Eval Set (`tests/evals/commerce_eval_set.json`)
This evaluation ensures the Buyer Agent calls `run_autonomous_purchase` with strictly validated parameters and verifies that rejected transactions do not alter the user's balance:

```json
{
  "eval_set_id": "eval_agentic_commerce",
  "name": "Autonomous Commerce Policy & Audit Verification",
  "eval_cases": [
    {
      "eval_id": "test_overbudget_policy_rejection",
      "conversation_scenario": {
        "scenario": [
          {
            "user_input": "Buy me Nike running shoes size 10 under Rs. 1,500",
            "expected_tool_calls": [
              {
                "tool_name": "run_autonomous_purchase",
                "tool_args": {
                  "query": "shoes",
                  "brand": "Nike",
                  "size": 10,
                  "max_budget": 1500.0
                }
              }
            ]
          }
        ]
      },
      "final_session_state": {
        "user:balance": 10000.0
      }
    }
  ]
}
```

### 4.2 Executing Evals via ADK CLI
Run deterministic evaluations against the Buyer Agent module:
```bash
adk eval adk_agents/shopping_agent tests/evals/commerce_eval_set.json --print_detailed_results
```

---

## 5. Non-Invasive Auditing via ADK Plugins (`BasePlugin`)

The recommended pattern to decouple auditing and tracing from core agent logic is an **ADK Plugin**. A custom plugin hooks into the agent lifecycle:

```python
# app/modules/audit/adk_plugin.py
"""ADK Lifecycle Plugin for Commerce Audit Logging and Tracing."""

from typing import Any, Dict, Optional
from google.adk.plugins.base_plugin import BasePlugin
from app.modules.audit.trail import audit_trail


class A2AAuditTracePlugin(BasePlugin):
    """Hooks into ADK tool invocations and agent events to stream audit trails."""

    def __init__(self):
        super().__init__(name="a2a_audit_trace_plugin")

    def before_tool_callback(self, *, tool, tool_args: Dict[str, Any], tool_context) -> Optional[Dict[str, Any]]:
        """Invoked immediately prior to tool execution."""
        audit_trail.log_event(
            event_type="ADK_TOOL_CALL_STARTED",
            objective_id=getattr(tool_context, "invocation_id", "session_root"),
            details={
                "tool_name": tool.name,
                "arguments": tool_args,
                "agent_name": getattr(tool_context, "agent_name", "buyer_agent"),
            },
        )
        return None

    def after_tool_callback(
        self, *, tool, tool_args: Dict[str, Any], tool_context, result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Invoked immediately after tool execution returns."""
        audit_trail.log_event(
            event_type="ADK_TOOL_CALL_COMPLETED",
            objective_id=getattr(tool_context, "invocation_id", "session_root"),
            details={
                "tool_name": tool.name,
                "success": result.get("success", True) if isinstance(result, dict) else True,
                "status": result.get("status") if isinstance(result, dict) else "DONE",
            },
        )
        return None

    def on_event_callback(self, *, invocation_context, event):
        """Catches streaming events, user turns, and agent responses."""
        return None
```

### 5.1 Registering the Plugin with `adk web`
```bash
adk web --extra_plugins=app.modules.audit.adk_plugin.A2AAuditTracePlugin adk_agents/shopping_agent
```

Or programmatically in a custom runner:
```python
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from app.modules.audit.adk_plugin import A2AAuditTracePlugin

runner = Runner(
    agent=buyer_agent,
    session_service=InMemorySessionService(),
    plugins=[A2AAuditTracePlugin()],
)
```

---

## 6. Architecture & Implementation Matrix

| Requirement | ADK Primitive | Implementation Pattern |
|---|---|---|
| **A2A Cross-Agent Traceability** | `google.adk.telemetry.tracer` | Start OTel spans for proposal requests and negotiations; propagate W3C `traceparent`. |
| **Telemetry Ingestion** | OpenTelemetry Exporters | Run `adk web --trace_to_cloud --otel_to_cloud` or export to OTLP collector. |
| **Persistent User Wallet / Limits** | `google.adk.sessions.State` | Store cross-session limits under `state["user:balance"]` accessed via `ToolContext`. |
| **Transaction State Isolation** | `state["key"]` (Session) | Keep active order/proposal metadata isolated per shopping conversation. |
| **Immutable Decision Log** | SQLite `.adk/session.db` | Every turn, thought, and tool result is appended to the `events` table. |
| **Deterministic Policy Invariants** | `google.adk.evaluation` | Define `EvalCase` scenarios with expected tool calls and `final_session_state` checks. |
| **Decoupled Interception** | `google.adk.plugins.BasePlugin` | Capture `before_tool_callback` and `after_tool_callback` to write to `audit_trail`. |

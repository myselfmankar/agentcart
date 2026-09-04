# A2A Protocol: Agent-to-Agent (`app/modules/a2a`)
### *Decentralized Merchant Discovery & Autonomous Inter-Agent RPC Communication*

---

## Why This Module Exists

In multi-agent systems, agents cannot simply reach into each other's memory or database tables. Doing so violates encapsulation, breaks security, and creates brittle cross-dependencies.

The **Agent-to-Agent (A2A) Protocol** establishes a clean, decoupled network boundary:
- **Zero Tight-Coupling**: The Buyer Agent does not know or care how a merchant stores products or manages inventory.
- **Dynamic Discovery via AgentCards**: Instead of hardcoding merchant names or URLs into the buyer code, merchants publish standardized **AgentCards** that advertise their capabilities.
- **Structured Inter-Agent Messaging**: Standardizes catalog queries, dynamic 1-to-1 negotiations, and checkout creation over RPC.

---

## How It Works: The A2A Discovery & Communication Flow

```
[Buyer Agent / Shopping Coordinator]
                 │
                 ├── 1. discover_merchants()
                 ▼
       [Merchant Registry]
        ├── UrbanKicks AgentCard (skills: request_proposal, create_checkout)
        ├── ShoeKart AgentCard   (skills: request_proposal, create_checkout)
        └── FastFeet AgentCard   (skills: request_proposal, negotiate_proposal)
                 │
                 ├── 2. request_proposals(query, filters)
                 ▼
       [Merchant Agents A, B, C]
                 │
                 ├── 3. Dynamic Counter-Negotiation (if negotiable)
                 ▼
       [Winning Merchant Agent]
                 │
                 └── 4. create_checkout() & complete_checkout()
```

### 1. The AgentCard Schema ([`app/modules/a2a/agent_card.py`](file:///d:/_try2/app/modules/a2a/agent_card.py))
An `AgentCard` is an agent's digital business card, advertising:
- **`name`**: Merchant brand name (e.g. `UrbanKicks`).
- **`description`**: Store objective, specialty, and delivery expectations.
- **`url`**: Agent network endpoint.
- **`protocols`**: Supported interaction protocols (`["a2a", "acp", "ap2"]`).
- **`skills`**: Callable agent capabilities with expected input/output schemas:
  - `request_proposal`: Formulates a binding commercial quote.
  - `negotiate_proposal`: Dynamic 1-to-1 counter-negotiation.
  - `create_checkout`: Initiates ACP checkout session.
  - `complete_checkout`: Finalizes settlement upon payment capture.
- **`provider`**: Merchant identifier, currency, and negotiation flags.

### 2. A2A Client ([`app/modules/a2a/client.py`](file:///d:/_try2/app/modules/a2a/client.py))
The single point of contact used by the Buyer Agent to communicate across the network:
- `discover_merchants()`: Scans the registry and returns all active `AgentCard`s.
- `request_proposals()`: Broadcasts a structured query or targets a specific merchant to solicit proposals.
- `negotiate()`: Executes a multi-round negotiation dialogue with a merchant agent.
- `create_checkout()` & `complete_checkout()`: Invokes merchant checkout endpoints over the protocol boundary.

### 3. Registry & Adapter ([`app/modules/a2a/discovery.py`](file:///d:/_try2/app/modules/a2a/discovery.py))
Maintains the in-memory or networked directory of registered merchant agents and bridges protocol requests to concrete merchant instances.

---

## Invariants & Guardrails

- **Protocol Boundary Isolation**: The Buyer Agent NEVER calls merchant private methods or reads merchant database files directly; every interaction traverses `A2AClient`.
- **OpenTelemetry Tracing**: Every A2A call automatically injects and propagates trace contexts (`TraceContextTextMapPropagator`) to track inter-agent latency and audit events.
- **Decoupled Identity**: Merchants are referenced by portable `merchant_id` slugs, allowing arbitrary new stores to be plugged into the network without modifying buyer logic.

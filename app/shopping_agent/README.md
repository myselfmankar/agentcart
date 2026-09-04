# Autonomous Shopping Agent & Orchestrator (`app/shopping_agent`)
### *Multi-Agent Shopping Intelligence, Trade-Off Negotiation & End-to-End Orchestration*

---

## Why This Module Exists

In complex autonomous commerce, an agent cannot simply run a single prompt and hope for the best. 

A real buyer representative must:
1. **Coordinate Distributed Agents**: Discover multiple merchant stores over A2A without knowing their URLs or names in advance.
2. **Conduct Multi-Attribute Trade-Off Analysis**: Weigh a Rs. 4,800 shoe delivered in 4 days vs. a Rs. 5,000 shoe delivered in 2 days.
3. **Execute Dynamic Counter-Negotiations**: Pit competing quotes against each other to achieve the lowest price for the user.
4. **Enforce a 16-Step Verification Pipeline**: Coordinate the Policy Engine, AP2 Verifier, Buyer Ledger, and Razorpay Sandbox so that every single penny spent is safe and explainable.

The **Shopping Agent & Orchestrator Module** is the cognitive center that drives this entire autonomous loop.

---

## How It Works: The Multi-Agent Pipeline

```
[User Natural Language Prompt]
             │
             ▼
      [Buyer Agent] ────────► Google ADK Root Agent
             │
             ├── delegates via delegate_to_shopping_coordinator()
             ▼
   [Shopping Coordinator] ───► Discovers merchants over A2A
             │
             ├── AIBuyerAgent.evaluate_and_negotiate()
             │    ├── Solicits MerchantProposals over A2A
             │    ├── Analyzes multi-attribute trade-offs (Price vs Delivery)
             │    └── Initiates counter-negotiations to beat competing quotes
             │
             └── transfers back to Buyer Agent with winning proposal
             │
             ▼
[Autonomous Checkout Execution]
 ├── Step 1-8:  Policy Engine verification (Budget, SKU, Merchant Whitelist, Delivery)
 ├── Step 9-10: Buyer Ledger check (Available Balance, Per-Transaction Limit)
 ├── Step 11-14: AP2 Mandate generation & ES256 signature verification
 ├── Step 15-16: Razorpay Order creation & Payout settlement
 └── Step 17:    Atomic ledger debit reconciliation & minimal 2-sentence user confirmation
```

---

## System Architecture Diagrams

### 1. Full Engineering Architecture
Below is the developer-level multi-tier component stack:

![Engineering Architecture](assests/engineering_architecutre.png)

### 2. Internal Service Diagram
The internal service coordination and event bus wiring:

![Internal Service Diagram](assests/internal_service_diagram.png)

---

## Key Components

### 1. `AIBuyerAgent` ([`ai_buyer.py`](file:///d:/_try2/app/shopping_agent/ai_buyer.py))
- **`evaluate_and_negotiate(user_intent)`**:
  Dispatches queries to all candidate merchants, collects structured `MerchantProposal` objects, and filters out non-qualifying offers.
- **Dynamic 1-to-1 Negotiation Loop**:
  If multiple merchants qualify, it identifies the lowest price and challenges competing negotiable merchants:
  *"ShoeKart offered Rs. 4,700 with 4-day delivery. Can you beat this price?"*
  Records every round into `negotiation_rounds` for complete audit transparency.
- **LLM Trade-Off Reasoning**:
  Formulates an explainable recommendation balancing budget savings against delivery speed.

### 2. `ShoppingAgentOrchestrator` ([`orchestrator.py`](file:///d:/_try2/app/shopping_agent/orchestrator.py))
- Implements the complete **16-step deterministic safety gate**.
- Transitions `ShoppingObjective` through `INITIAL` -> `SEARCHING` -> `EVALUATING` -> `CHECKING_OUT` -> `COMPLETED` (or `WATCHING`).
- Coordinates AP2 cryptographic key signing, mandate verification, and ledger debit recording.

### 3. Google ADK Agent Bindings ([`adk_agents/`](file:///d:/_try2/adk_agents))
- **`buyer_agent`** ([`adk_agents/shopping_agent/buyer_agent.py`](file:///d:/_try2/adk_agents/shopping_agent/buyer_agent.py)):
  Acts as the primary conversational interface in `adk web`. Enforces **minimalist 2-sentence human output** (never dumps confusing JSON, token IDs, or mandate keys to the user).
- **`shopping_coordinator`** ([`adk_agents/shopping_coordinator/agent.py`](file:///d:/_try2/adk_agents/shopping_coordinator/agent.py)):
  Sub-agent handling the distributed merchant coordination and price comparison tools.

---

## Invariants & Guardrails

- **Minimalist User Communication**: The buyer agent outputs a concise, human-friendly 2-sentence confirmation upon purchase:
  > *"I have purchased the Nike Air Zoom Pegasus from FastFeet for Rs. 4,899. Delivery is scheduled within 3 days."*
- **Strict Separation of Concerns**: AI never touches money directly; all settlement must pass through `execute_autonomous_checkout()` and `policy_engine.evaluate_offer()`.
- **Zero Hallucinated Products**: The buyer agent only purchases verified SKUs returned by merchant catalog queries.

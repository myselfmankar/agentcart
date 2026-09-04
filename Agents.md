# Engineering Guardrails & Architecture Directives

## 1. Core Principles & Philosophy
- **Do not invent protocol functionality from scratch**: Reuse/adapt official and reference AP2, A2A, and ACP implementations.
- **Standalone & Self-Contained**: Code copied from reference samples must be organized into clean, local modules (`modules/`, `apps/`, `merchants/`) without brittle cross-repository path dependencies.
- **Dependency Discipline**: Do not add unnecessary frameworks or dependencies unless they solve a concrete requirement.
- **UI is Secondary**: The primary testing and interaction runtime is `adk web` (and CLI test scripts). Focus engineering effort on backend agent autonomy, policy safety, and payment execution.

## 2. Primary Engineering Focus Areas
1. **Shopping Agent (Buyer)**: Intent extraction, merchant discovery, offer evaluation, and autonomous purchase execution.
2. **Merchant Agent (Seller)**: Agent-readable catalog, inventory management, dynamic cart assembly, and ES256-signed checkout creation.
3. **Autonomous Decision Making**: Intelligent candidate selection and trade-off analysis by the LLM.
4. **Policy Enforcement (Deterministic Safety Gate)**:
   - **Never allow an LLM-generated decision to directly bypass deterministic purchase constraints.**
   - All money-moving operations must pass through the policy/authorization layer (checking price <= max budget, whitelisted merchant, authorized item SKU).
5. **WATCH / Re-Evaluation State Machine**:
   - Maintain active shopping objectives when no qualifying offers currently exist (`SEARCHING` -> `WATCHING` -> `RE_EVALUATING` -> `CHECKOUT`).
   - Event/trigger-driven state transitions on price drops, restocks, and flash sales.
6. **Razorpay Integration (Test Mode)**:
   - Order creation (`razorpay.Order.create`).
   - Autonomous payment execution & capture against tokenized credentials / pre-authorized mandates.
   - Verifiable cryptographic payment receipts.
7. **Graceful Failure Handling & Explainable Audit Trail**:
   - Provide an immutable, step-by-step trace of every money-related decision.
   - Deterministically block over-budget purchases (`POLICY_REJECTED`) and handle out-of-stock or payment errors gracefully without halting system stability.

## 3. Layer Boundaries & Dependency Direction
```text
Business Logic (Shopping Agent / Policy / Watch)
       ↓
Protocol Adapters (A2A / ACP / AP2 / Razorpay)
       ↓
External Systems (Merchants, Razorpay Sandbox, Webhooks)
```
- **Never allow protocol adapters or payment modules to make business or purchase decisions.**
- The Shopping Agent coordinates; the Policy Engine validates; Protocol Adapters transmit; Razorpay executes.
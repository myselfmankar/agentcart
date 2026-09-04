You are building the core demo for a Razorpay AI Buildathon project.

STARTING POINT
----------------
The repository currently contains the AP2 Human-Not-Present sample code.

Treat that sample as the foundation for:
- AP2 implementation
- A2A agent communication
- agent runtime/orchestration
- ADK integration
- ADK Web UI / playground
- mandate/signing infrastructure
- relevant authentication/verification primitives

Do NOT carry over unnecessary application/business logic from the sample.
Do NOT build a React frontend.
Do NOT introduce Kafka, Redis, Kubernetes, vector DB, or other infrastructure unless absolutely required.

The goal is to build a clean, working agentic-commerce simulation on top of the sample.

==================================================
PRODUCT
==================================================

Build an autonomous multi-merchant marketplace with:

1. ONE SHOPPING AGENT (SA)
2. THREE MERCHANT AGENTS (MA-A, MA-B, MA-C)

Total: 4 agents.

The user interacts ONLY with the Shopping Agent through the ADK Web UI.

The Shopping Agent discovers and communicates with Merchant Agents.

Merchant Agents represent independent merchants with their own:
- catalogs
- inventory
- pricing
- discount policies
- fulfillment policies
- negotiation policies
- merchant objectives

The Shopping Agent represents the BUYER and has:
- user intent
- spending constraints
- purchase authorization
- product constraints
- autonomous purchase permission

The core demo is:

USER
  ↓
SHOPPING AGENT
  ↓
A2A
  ├── MERCHANT AGENT A
  ├── MERCHANT AGENT B
  └── MERCHANT AGENT C
  ↓
ACP COMMERCE / CHECKOUT
  ↓
AP2 AUTHORIZATION
  ↓
RAZORPAY MCP
  ↓
RAZORPAY TEST MODE
  ↓
WEBHOOK / PAYMENT STATE
  ↓
SHOPPING AGENT
  ↓
USER

==================================================
CORE USER EXPERIENCE
==================================================

The user should be able to open the ADK Web UI and type something like:

"Buy me Adidas blue sneakers, size 10, under ₹5,000.
Purchase automatically if you find a good deal."

Or:

"Find the best deal on blue Adidas sneakers, size 10.
I need them tomorrow and I'm willing to spend up to ₹5,000."

The user should NOT have to manually choose a merchant.

The Shopping Agent should autonomously:

1. Parse the request.
2. Create a structured shopping objective.
3. Create/verify the buyer's spending policy.
4. Discover Merchant Agents using A2A.
5. Query merchants for matching products.
6. Receive offers.
7. Compare offers.
8. Negotiate where appropriate.
9. Select the best qualifying offer.
10. Initiate ACP checkout.
11. Verify the finalized checkout.
12. Apply AP2 authorization.
13. Execute payment through Razorpay MCP.
14. Verify the actual Razorpay payment/order state.
15. Return the result and receipt to the user.

==================================================
AGENT 1 — SHOPPING AGENT
==================================================

The Shopping Agent is the buyer-side autonomous agent.

Responsibilities:

- understand natural-language purchase intent
- maintain shopping objective
- discover merchant agents
- request offers
- compare offers
- negotiate with merchants
- enforce buyer constraints
- choose the best qualifying offer
- initiate checkout
- coordinate AP2 authorization
- invoke Razorpay MCP for payment
- process payment state/webhooks
- explain decisions to the user
- maintain audit trail
- support WATCHING state

The Shopping Agent MUST NOT directly read merchant JSON files.

It must communicate with merchants through the agent/protocol boundary.

==================================================
AGENT 2/3/4 — MERCHANT AGENTS
==================================================

Create three independent Merchant Agents:

Merchant A = UrbanKicks
Merchant B = ShoeKart
Merchant C = FastFeet

Each Merchant Agent must have its own state.

The merchant agent owns:

- catalog
- inventory
- price
- discounts
- fulfillment
- negotiation policy
- merchant objectives

The merchant agents should NOT all behave identically.

Example:

URBANKICKS:
- competitive pricing
- moderate discounts
- normal delivery

SHOEKART:
- lowest base prices
- volatile inventory
- less negotiation flexibility
- slower delivery

FASTFEET:
- higher base prices
- strong inventory
- fast/free delivery
- aggressive negotiation
- willing to trade price for conversion

==================================================
MERCHANT CATALOG
==================================================

Use JSON files as merchant-owned source-of-truth state.

Suggested structure:

merchants/
  merchant_a/
    catalog.json
    policy.json
  merchant_b/
    catalog.json
    policy.json
  merchant_c/
    catalog.json
    policy.json

Catalog must support:

- product_id
- brand
- product name
- category
- color
- size
- price
- stock
- discount rules
- delivery options
- delivery fee
- delivery estimate

Have several shoe products across:
- Adidas
- Nike
- Puma

Have multiple:
- colors
- sizes
- prices
- inventory levels

Some products should have discounts.

Some should have negotiable discounts.

Some should have better delivery.

Make the catalogs intentionally asymmetric so the Shopping Agent has to reason.

Example:

Merchant A:
Adidas blue size 10 = ₹5,299
stock = 5
discount = ₹400 if eligible

Merchant B:
Adidas blue size 10 = ₹4,799
stock = 0

Merchant C:
Adidas blue size 10 = ₹5,099
stock = 8
negotiable discount
free next-day delivery

This should create interesting agent behavior.

==================================================
MERCHANT NEGOTIATION
==================================================

This is a key part of the project.

Merchant Agents should NOT simply return static catalog data.

They should be able to reason within merchant-defined constraints.

For example:

Merchant C:

base_price = ₹5,099
minimum_price = ₹4,650
maximum_discount = ₹450
inventory = 8
free_express_threshold = ₹4,800

Buyer Agent:

"Can you offer ₹4,700?"

Merchant C:

"₹4,700 is acceptable, but I can only offer free next-day delivery above ₹4,800."

Buyer Agent:

"Can you do ₹4,800 with free next-day delivery?"

Merchant C:

"Accepted."

The merchant agent must NEVER violate its merchant policy.

If the requested price is below its minimum acceptable price, reject it.

The negotiation must be bounded:
- maximum negotiation rounds
- minimum acceptable price
- maximum discount
- merchant-specific rules

Do not allow the LLM to bypass these constraints.

Use deterministic policy checks around agent decisions.

==================================================
OFFER MODEL
==================================================

Create a structured offer object.

It should contain at minimum:

- merchant_id
- product_id
- variant
- base_price
- discount
- final_price
- currency
- stock
- delivery_option
- delivery_days
- delivery_fee
- offer_expiry
- negotiation_id
- terms

The Shopping Agent should rank offers using BOTH:

BUYER CONSTRAINTS

and

TOTAL COMMERCIAL VALUE

Do not blindly choose lowest product price.

For example:

₹4,750 tomorrow

may beat

₹4,600 in 7 days

if the user requested delivery tomorrow.

==================================================
BUYER SPENDING AUTHORITY
==================================================

Create a buyer-side spending policy.

This is application-level authorization.

Do NOT pretend this is a Razorpay merchant wallet.

Example:

buyer spending authority:
₹6,000

maximum single transaction:
₹5,000

autonomous purchase:
true

currency:
INR

The Shopping Agent must verify:

- product constraints
- price constraint
- delivery constraint
- autonomous purchase permission
- per-transaction spending limit
- remaining buyer spending authority

BEFORE payment.

If the final checkout is ₹5,100 and max is ₹5,000:

PAYMENT MUST NOT HAPPEN.

If available buyer authority is ₹3,000 and checkout is ₹4,800:

PAYMENT MUST NOT HAPPEN.

==================================================
AP2
==================================================

Use the ACTUAL AP2 mechanisms from the Human-Not-Present sample wherever applicable.

Do NOT create a fake "AP2-like" JSON format.

The flow should distinguish:

OPEN CHECKOUT MANDATE
OPEN PAYMENT MANDATE
CLOSED CHECKOUT MANDATE
CLOSED PAYMENT MANDATE

The conceptual lifecycle is:

USER INTENT
  ↓
OPEN CHECKOUT MANDATE
  ↓
OPEN PAYMENT MANDATE
  ↓
MERCHANT DISCOVERY / NEGOTIATION
  ↓
ACP FINAL CHECKOUT
  ↓
CLOSED CHECKOUT MANDATE
  ↓
VERIFY
  ↓
CLOSED PAYMENT MANDATE
  ↓
VERIFY
  ↓
PAYMENT

The OPEN mandates represent the user's bounded authorization.

The CLOSED mandates authorize the specific finalized transaction.

CRITICAL:

If price, merchant, checkout, quantity, fulfillment, or any transaction-relevant detail changes materially, DO NOT reuse an old CLOSED mandate.

Generate a new closed mandate for the new finalized checkout.

Implement:
- mandate IDs
- expiry
- signatures
- verification
- hashes
- binding between open and closed mandates
- replay protection
- consumption state
- receipt references

Use the AP2 sample's real implementation rather than inventing replacements.

==================================================
ACP
==================================================

Use ACP as the commerce/checkout boundary.

Merchant Agent owns the authoritative checkout state.

The Shopping Agent should NOT directly manipulate merchant catalog JSON.

The flow should be conceptually:

Shopping Agent
  ↓
Merchant Agent
  ↓
ACP checkout session
  ↓
Merchant returns authoritative checkout
  ↓
final amount
  ↓
Shopping Agent re-validates buyer policy
  ↓
AP2 closed mandates
  ↓
payment

The merchant remains authoritative for:
- final price
- inventory
- fulfillment
- shipping
- checkout state

If checkout changes the total:
RE-RUN POLICY CHECKS.

Never authorize payment based only on an earlier catalog price.

==================================================
RAZORPAY MCP
==================================================

PAYMENTS MUST BE EXECUTED USING RAZORPAY MCP.

Do not create a fake payment processor.

Do not implement a mock payment-success path.

Use Razorpay MCP for actual Razorpay TEST MODE operations.

Configure the official Razorpay MCP integration appropriately.

The Shopping Agent/payment component should use MCP tools for:
- creating/retrieving relevant payment/order state
- executing the payment flow supported by the test environment
- checking payment status
- checking order status
- refunds if needed later

Keep Razorpay credentials/secrets in environment variables.

NEVER commit credentials.

IMPORTANT:

Do not treat:
"Razorpay order created"

as:

"Payment successful."

Only report payment success after verifying the actual Razorpay payment/order state.

Handle:
- created
- authorized
- captured
- failed
- delayed
- duplicate events

according to actual Razorpay state.

==================================================
WEBHOOKS
==================================================

Implement a webhook/event processing boundary.

The application must be able to receive payment state changes.

Webhook processing must be idempotent.

If the same event arrives twice:
DO NOT double-process it.

The audit trail should record:
- Razorpay order ID
- payment ID
- event ID
- status
- timestamp
- processing result

==================================================
WATCHING / AUTONOMOUS OBJECTIVES
==================================================

Support a persistent WATCHING state.

Example:

User:
"Buy Adidas blue size 10 below ₹5,000 automatically."

If no merchant currently satisfies the constraints:

Shopping Objective:
WATCHING

Later a merchant changes:
stock
price
discount
delivery

The objective should be re-evaluated.

Example:

Initially:

Merchant A = ₹5,299
Merchant B = OUT OF STOCK
Merchant C = ₹5,099

No qualifying offer.

Objective:
WATCHING

Then Merchant B inventory changes:

stock = 3

Trigger an inventory-change event.

Shopping Agent:
- discovers/rechecks merchant
- gets fresh offer
- evaluates it
- negotiates if appropriate
- creates a NEW ACP checkout
- creates NEW CLOSED AP2 mandates
- verifies authorization
- executes Razorpay payment

Do NOT reuse stale checkout or closed mandates.

==================================================
INTERACTIVE ADK WEB UI
==================================================

Use the ADK Web UI/playground supplied by the sample.

The user should be able to interact naturally with the Shopping Agent.

The UI should expose enough information to make the demo understandable.

For example:

USER:
Buy Adidas blue sneakers, size 10, under ₹5,000.
Purchase automatically.

SHOPPING AGENT:
Searching merchant agents...

Merchant A:
₹5,299
Stock: 5
Possible discount: ₹400

Merchant B:
₹4,799
OUT OF STOCK

Merchant C:
₹5,099
Stock: 8
Negotiable
Next-day delivery available

SHOPPING AGENT:
Negotiating with Merchant A...
Merchant A final offer: ₹4,899

Negotiating with Merchant C...
Merchant C final offer: ₹4,800 + free next-day delivery

SHOPPING AGENT:
Selected Merchant C.

Open Checkout Mandate: VERIFIED
Open Payment Mandate: VERIFIED

ACP Checkout:
Final total ₹4,800

Closed Checkout Mandate: VERIFIED
Closed Payment Mandate: VERIFIED

Razorpay:
Order created
Payment captured

AP2 Payment Receipt:
...

Purchase completed.

The UI does NOT need to be visually fancy.

The agent trace and reasoning/state transitions are more important than frontend design.

==================================================
AUDIT TRAIL
==================================================

Implement structured events.

At minimum:

intent.created
buyer.policy.created
merchant.discovered
offer.received
negotiation.started
negotiation.completed
offer.rejected
offer.selected
checkout.created
checkout.updated
mandate.open.checkout.created
mandate.open.payment.created
mandate.closed.checkout.created
mandate.closed.checkout.verified
mandate.closed.payment.created
mandate.closed.payment.verified
payment.requested
payment.authorized
payment.captured
payment.failed
webhook.received
receipt.created
objective.watching
objective.re_evaluated
objective.completed

Make it possible to explain:

WHY was Merchant A rejected?
WHY did Merchant C win?
WHY was a discount offered?
WHY was payment authorized?
WHY would payment have been rejected?

==================================================
IMPORTANT SECURITY / ARCHITECTURE RULE
==================================================

LLMs can:
- understand intent
- search
- negotiate
- compare
- reason
- rank

LLMs CANNOT:
- override spending limits
- override merchant minimum prices
- bypass AP2 verification
- declare a payment successful
- alter inventory
- directly access another merchant's private state
- reuse expired/consumed mandates
- bypass checkout verification

Money movement must be gated by deterministic code.

==================================================
TEST SCENARIOS
==================================================

Build automated tests for at least:

1. Cheapest merchant wins.

2. Cheapest merchant is out of stock.

3. More expensive merchant wins because of delivery requirement.

4. Merchant negotiates discount.

5. Merchant refuses price below minimum.

6. Final negotiated price exceeds buyer limit.

7. Buyer spending authority insufficient.

8. Checkout price changes after offer.

9. Open mandate expired.

10. Closed mandate verification fails.

11. Checkout hash mismatch.

12. Duplicate webhook.

13. Razorpay payment failure.

14. WATCHING → merchant restocks → autonomous purchase.

15. WATCHING → price changes but still exceeds budget.

16. Merchant changes checkout after closed mandate creation.

The last case MUST require creation of a new closed mandate.

==================================================
IMPLEMENTATION STRATEGY
==================================================

Before modifying code:

1. Inspect the AP2 Human-Not-Present sample.
2. Map its existing:
   - agents
   - roles
   - A2A communication
   - ADK configuration
   - AP2 mandate implementation
   - authentication
   - UI/runtime
   - payment processor
3. Produce a concise:
   KEEP / MODIFY / REMOVE / ADD
   table.

Then implement incrementally.

PHASE 1:
Get 4 agents running through ADK/A2A.

PHASE 2:
Add merchant JSON catalogs and merchant policies.

PHASE 3:
Implement offer discovery and negotiation.

PHASE 4:
Implement buyer spending authority.

PHASE 5:
Implement ACP checkout.

PHASE 6:
Implement complete AP2 open → closed mandate lifecycle.

PHASE 7:
Connect Razorpay MCP and perform an actual TEST MODE payment.

PHASE 8:
Add webhook verification and receipts.

PHASE 9:
Add WATCHING/re-evaluation.

PHASE 10:
Add failure tests and clean ADK demo experience.

==================================================
FINAL ACCEPTANCE TEST
==================================================

This must work end-to-end from the ADK Web UI:

User:
"Buy Adidas blue sneakers, size 10, under ₹5,000.
Purchase automatically."

↓

Shopping Agent

↓

A2A discovery

↓

Merchant A/B/C

↓

Negotiation

↓

Best qualifying offer

↓

ACP checkout

↓

Open Checkout Mandate
+
Open Payment Mandate

↓

Final merchant-authoritative checkout

↓

Closed Checkout Mandate

↓

Closed Payment Mandate

↓

Deterministic AP2 verification

↓

Razorpay MCP

↓

REAL RAZORPAY TEST MODE PAYMENT

↓

Actual Razorpay payment/order verification

↓

Webhook

↓

AP2 receipt

↓

Audit trail

↓

User sees successful purchase.

Then demonstrate WATCHING:

No merchant qualifies
→ WATCHING
→ merchant JSON changes
→ event
→ re-evaluation
→ new offer
→ new ACP checkout
→ NEW closed mandates
→ Razorpay MCP
→ verified payment.

The final project should feel like a real two-sided agentic marketplace, not a collection of mocked API calls.

The central demo story is:

"An AI buyer autonomously negotiates with AI merchants, while both buyer and merchant agents operate within bounded economic policies. AP2 authorizes the autonomous transaction, ACP handles commerce/checkout, A2A connects the agents, and Razorpay MCP executes the payment."

Do not optimize for maximum code.
Optimize for a small, protocol-faithful, fully working end-to-end system.


# Architecture & Scalability Backlog (Future Scoping)

## 1. Out-of-Domain Broadcast Token Waste
- **Current Behavior**:
  - When a user submits an intent outside the known merchant network domains (e.g., *"Get me a 65-inch OLED TV"*), the shopping coordinator broadcasts the request across all registered merchant agents.
  - Every merchant agent runs an LLM evaluation over its catalog only to determine that it does not carry electronics (`has_match: false`).
  - While fine for 3 merchants, this wastes tokens, latency, and network bandwidth when no merchant in the network supports the requested category.
- **Future Scope / Solution**:
  - **Network-Level Category Pre-Gate**: The Buyer Agent/Coordinator inspects the published capabilities on A2A Agent Cards (`capabilities.categories: ["footwear", "apparel"]`). If no registered merchant advertises `"electronics"`, the request immediately fails fast or prompts the user without dispatching merchant LLM inferences.

---

## 2. $O(N)$ Scalability Bottleneck with 10,000+ Merchant Agents
- **Current Behavior**:
  - The coordinator broadcasts to $N$ merchants ($N=3$), gathers all $N$ proposals synchronously, and evaluates the best trade-off.
  - This $O(N)$ linear fan-out is completely intractable at scale ($10,000+$ independent merchant agents):
    - $10,000$ concurrent network requests and LLM evaluations per user search.
    - Massive tail latencies waiting for the slowest merchant response.
- **Future Scope / Architectural Solutions**:
  1. **A2A Capability Registry & Vector Pre-Routing**:
     - Centralized or DHT-based A2A registry indexing merchant Agent Cards by domain, brand, geography, and category vectors.
     - Fast vector/inverted index filters 10,000+ merchants down to Top-$K$ ($K=3\text{--}5$) relevant stores in $<10\text{ms}$ *before* dispatching any agent messages.
  2. **Bloom Filters / Category Bitmaps**:
     - Fast probabilistic checks in the merchant registry to deterministically eliminate non-matching stores without network calls.
  3. **Quorum & Top-K Auctions (Early-Stopping)**:
     - Coordinator solicits proposals with a tight deadline window (e.g., 800ms) or stops once a quorum of competitive quotes (e.g., first 3 valid quotes) is received, avoiding waiting on all merchants.
  4. **Federated Domain Gateways**:
     - Specialized aggregator agents (e.g., Electronics Gateway, Fashion Gateway, Logistics Gateway) that group merchant sub-clusters hierarchically.


3. Why Orders were stuck in Created / ₹0.00 Collected:
Order creation (create_order) was reaching the live Razorpay API, which is why orders appeared on the dashboard with status Created.
However, execute_test_payment in app/modules/razorpay/client.py was generating a mock pay_<uuid> dictionary in memory rather than calling the Razorpay test payment gateway.
As a result, attempts were 0, no payment was ever captured on Razorpay, and the dashboard displayed Collected Amount: ₹0.00 from 0 captured payments.
The 3-Merchant / Single-Account Challenge:
Platforms with multiple merchants cannot create 3 separate master accounts.
In Razorpay, the solution is Razorpay Route (Marketplace & Split Payments).
On standard test API keys, the Route Linked Account creation endpoint (POST /v2/accounts) returns "Route feature not enabled for the merchant".
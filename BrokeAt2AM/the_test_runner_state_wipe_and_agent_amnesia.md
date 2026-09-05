# The Test Runner State Wipe & The Agent's "Amnesia"

## 1. Problem
During end-to-end live testing of the **AP2 Watch & Restock Engine**, a bewildering desynchronization occurred:
1. The user prompted the Shopping Agent: *"Buy me a Adidas shoes under 4k size any"*.
2. ShoeKart was out of stock at Rs. 3,800, so the agent placed the objective into `WATCHING` under an AP2 Intent Mandate.
3. The user switched to the **Merchant Portal** (`http://127.0.0.1:8001`), increased ShoeKart's stock, and clicked Update.
4. The background engine fired:
   - Woke up objective `obj_3c0073b1`.
   - Executed the autonomous purchase from ShoeKart for Rs. 3,550.
   - Settled payment on Razorpay (`order_TY2yXDh39KVDwq`) and issued a payout (`pout_TY2ydw4If5BazM`).
   - The Merchant Portal Live Objectives card updated to: **`COMPLETED (Purchased from ShoeKart for Rs. 3,550)`**.
5. Satisfied, the user switched back to the Google ADK chat tab and asked:
   > *"Any update for my order?"*
6. But instead of confirming the purchase, the Agent replied:
   > *"Your request is currently being monitored as ShoeKart remains out of stock for the Adidas Runfalcon 3 at Rs. 3,800. I am actively tracking merchant stock levels and price drops to execute the purchase automatically for you as soon as an item becomes available within budget."*

Why did the Agent act as if it had complete amnesia when the transaction had already completed and settled on Razorpay?

---

## 2. Root Cause Analysis

Tracing the logs across both servers (`:8000` and `:8001`) and the file system revealed a subtle multi-process collision:

```text
[Merchant Portal :8001]
  Restock Event ──► Orchestrator executes purchase
               ──► Stores COMPLETED objective in memory + writes .temp-db/shopping_objectives.json

[Background Terminal]
  Developer / CI runs: uv run pytest
               ──► tests/conftest.py autouse fixture triggers:
               ──► objective_store.clear()
               ──► 🔥 WIPES .temp-db/shopping_objectives.json to "{}"!

[ADK Web :8000]
  User asks: "Any update for my order?"
               ──► check_order_or_watch_status() reads .temp-db/shopping_objectives.json
               ──► Reads "{}" (0 objectives found)
               ──► Returns {"status": "NO_OBJECTIVES"}
               ──► LLM falls back to turn #1 chat history: "ShoeKart is still out of stock"!
```

### 1. The Shared State Collision
In `tests/conftest.py`, the test harness had an `autouse=True` fixture intended to ensure regression tests don't leak state:
```python
@pytest.fixture(autouse=True)
def reset_test_state():
    ...
    # Clear objective store cache
    objective_store.clear()
```
Because the test runner and the live dev server were pointing to the exact same default path (`.temp-db/shopping_objectives.json`), running `pytest` in the background wiped out the active live objectives right from under the running application!

### 2. Divergent In-Memory State
- The **Merchant Portal process** had already loaded the completed objective into its local memory dictionary (`_cache`), so its frontend UI continued to display `COMPLETED`.
- But the **ADK Web server process** reloaded from disk on demand. When disk had `{}` (empty), it returned `NO_OBJECTIVES`.

### 3. The LLM's Conversational Hallucination Fallback
When a tool returns `NO_OBJECTIVES` in the middle of an existing conversation where the agent had previously promised to watch ShoeKart, the LLM does not say "Error, database was wiped." Instead, it looks at its past turn history (Turn #6: *"ShoeKart is out of stock, placed on WATCH"*), assumes nothing has changed, and generates a plausible-sounding status: *"Your request is currently being monitored as ShoeKart remains out of stock..."*.

---

## 3. The Resolution

### 1. Strict Test Database Isolation
In `tests/conftest.py`, we isolated the test runner to an independent test database directory:
```python
# Isolate tests to a sandbox test database so running pytest never wipes live session data
_TEST_DB = Path(".temp-test-db")
_TEST_DB.mkdir(parents=True, exist_ok=True)
objective_store.file_path = _TEST_DB / "test_shopping_objectives.json"
```
Now, automated regression runs (`uv run pytest`) only modify and clear `.temp-test-db/test_shopping_objectives.json`. The live application's `.temp-db/shopping_objectives.json` remains completely untouched.

### 2. Precision Objective Resolution in `check_order_or_watch_status`
Updated [`adk_agents/shopping_agent/buyer_agent.py`](file:///d:/_try2/adk_agents/shopping_agent/buyer_agent.py) so that `check_order_or_watch_status`:
1. **Prioritizes the exact session objective**: Queries `tool_context.state.get("session:watching_objective_id")` first rather than blindly relying on `objs[-1]`.
2. **Prioritizes `COMPLETED` objectives**: If multiple objectives exist, any completed purchase is surfaced immediately.
3. **Explicit Structured Summaries**: Returns an unambiguous `summary: "PURCHASE_COMPLETED: ShoeKart restocked Adidas Runfalcon 3. Autonomously purchased for Rs. 3,550 under AP2 Intent Mandate."` so the model never has to guess or fall back to past conversational turns.

---

## 4. Verification

1. **Test Suite Isolation Verified**:
   Running `uv run pytest` creates `.temp-test-db/test_shopping_objectives.json`. The live file `.temp-db/shopping_objectives.json` is preserved with active objectives intact.
2. **Consistent Session Recovery**:
   When the user asks *"Any update for my order?"*, the agent correctly resolves the completed objective and confirms:
   > *"ShoeKart restocked the Adidas Runfalcon 3! Since your Intent Mandate authorized it under Rs. 4,000, I completed the purchase for Rs. 3,550. Delivery is scheduled within 5 days."*
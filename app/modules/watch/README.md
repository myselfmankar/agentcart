# WATCH State Machine & Event Bus (`app/modules/watch`)
### *Persistent Shopping Objectives & Event-Driven Autonomous Re-Evaluation*

---

## Why This Module Exists

In conventional shopping assistants, if a desired product is out of stock or priced above the user's budget ceiling, the execution terminates immediately with a dead end: *"Sorry, no items match your search"*.

In **autonomous commerce**, the user does not want to keep asking the bot every 4 hours. They want to set an **autonomous shopping objective** that stays alive until fulfilled:
> *"Buy Nike Air Zoom size 10 when price drops under Rs. 5,000 or when restocked."*

The **WATCH Module** implements an asynchronous, event-driven state machine:
- It maintains the persistent objective across process restarts.
- Instead of burning CPU and network tokens with busy `while True: sleep()` polling loops, it registers listeners on an **Event Bus**.
- The moment a merchant emits a `PRICE_CHANGED` or `INVENTORY_RESTOCKED` event, the system transitions to `RE_EVALUATING` and executes the purchase.

---

## How It Works: The State Machine Lifecycle

```
[User Intent] ───► INITIAL ───► SEARCHING ───► EVALUATING
                                                  │
                      ┌───────────────────────────┴───────────────────────────┐
                      ▼                                                       ▼
            [Valid Offer Exists]                                    [No Qualifying Offer]
                      │                                                       │
                      ▼                                                       ▼
                CHECKING_OUT                                               WATCHING
                      │                                                       │
                      ▼                                                       ▼
                  COMPLETED                                    [Merchant Restock / Price Drop Event]
                                                                              │
                                                                              ▼
                                                                        RE_EVALUATING
```

### The Formal State Machine Diagram

![WATCH State Machine](assests/watch_state_mc.png)

### Core States ([`objective.py`](file:///d:/_try2/app/modules/watch/objective.py))

| State | Description | Next Trigger / Transition |
| :--- | :--- | :--- |
| **`INITIAL`** | Objective registered, bounds parsed. | Transitions immediately to `SEARCHING`. |
| **`SEARCHING`** | Polling live catalogs across merchants over A2A. | Transitions to `EVALUATING` once proposals arrive. |
| **`EVALUATING`** | Running multi-attribute trade-off analysis. | Transitions to `CHECKING_OUT` if qualified, or `WATCHING` if none qualify. |
| **`WATCHING`** | Objective dormant, waiting for store updates. | Transitions to `RE_EVALUATING` upon an `EventBus` signal. |
| **`RE_EVALUATING`** | Triggered by price drop or restock. | Re-runs proposal evaluation; if qualified, proceeds to `CHECKING_OUT`. |
| **`AWAITING_FUNDS`**| Paused if buyer balance is temporarily exhausted. | Transitions back to `SEARCHING` when buyer treasury is refilled. |
| **`CHECKING_OUT`** | Mandates assembled; Policy Gate evaluated; Razorpay payment initiated. | Transitions to `COMPLETED` on capture, or `FAILED`. |
| **`COMPLETED`** | Payment verified; inventory decremented; receipt generated. | Terminal state. |

---

## Event Bus Architecture ([`event_bus.py`](file:///d:/_try2/app/modules/watch/event_bus.py))

The `EventBus` provides a decoupled pub/sub channel within the application runtime:

```python
# Event payload emitted by a merchant when replenishing inventory
event_bus.publish(
    event_type="INVENTORY_RESTOCKED",
    payload={"merchant_id": "merchant_a", "sku": "uk_sneaker_01", "new_stock": 5}
)
```

Registered watch listeners catch the event, match it to dormant objectives interested in that category/SKU, and re-invoke the shopping orchestrator.

---

## Invariants & Guardrails

- **Disk Persistence**: Objectives are written to `.temp-db/shopping_objectives.json` with thread-safe file locks, ensuring active watches survive system reboots.
- **Zero Tight Polling**: Does not hammer merchant servers on a cron or fixed interval; execution is strictly event-driven.
- **Strict Policy Gating**: Re-evaluated offers must pass the full deterministic policy engine before proceeding to `CHECKING_OUT`.

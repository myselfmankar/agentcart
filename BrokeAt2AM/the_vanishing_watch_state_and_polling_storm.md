# The Vanishing WATCH State & The Polling Storm

## 1. Problem
When a buyer requested an item that was out of stock (such as ShoeKart blue sneakers size 10):
- The agent simply replied "Item is out of stock" and terminated. The buyer's purchase intent vanished into thin air.
- When the merchant later restocked the item on the Merchant Portal, nothing happened—no autonomous purchase occurred.
- Furthermore, our server logs were overwhelmed by thousands of continuous requests hitting `GET /api/objectives` every minute, causing unnecessary CPU and network load.



## What I Did to Fix
1. **Persistent WATCH State Machine (`app/modules/watch/objective.py`)**:
   - When no qualifying offer exists, the agent persists a `ShoppingObjective` to `data/objectives.json` with status `ObjectiveStatus.WATCHING`.
   - The intent remains active and waiting for market signals.
2. **EventBus Bridge on the Merchant Portal (`app/merchant_portal/server.py`)**:
   - Connected the Merchant Portal to the internal event bus.
   - When a merchant updates inventory (e.g., resets stock from 0 to 5) and clicks **Update**, the server emits an `INVENTORY_RESTOCKED` event to `shopping_orchestrator.handle_merchant_event`.
3. **Autonomous Background Fulfillment**:
   - The event immediately triggers the agent's re-evaluation loop (`WATCHING ➔ RE_EVALUATING ➔ CHECKOUT`).
   - The agent buys the product, signs the AP2 mandate, and settles via Razorpay autonomously without user re-prompting.
4. **Eliminated Runaway Polling**:
   - Removed the aggressive interval timer in the frontend, switching to event-driven UI updates on user interaction.

## Why
In traditional commerce, out-of-stock items lead to high Customer Acquisition Cost (CAC) churn—customers leave and never return. In agentic commerce, demand does not expire. By keeping unsatisfied intents alive in an event-driven state machine, merchants liquidate new inventory the moment it arrives in the warehouse with **Zero Customer Acquisition Cost (Zero-CAC)**.

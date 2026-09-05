"""Autonomous Shopping Buyer Agent for Razorpay Autonomous Commerce.

The Buyer Agent is the user's autonomous purchasing representative.
Operates under the Agentic Commerce Protocol (ACP) and Agent Payments Protocol (AP2)
to discover merchants, solicit proposals over A2A, negotiate trade-offs, and complete
verified test payments via Razorpay MCP.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure project root is in sys.path
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

load_dotenv()

# Ensure console stdout/stderr does not fail on Windows charmap encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure Gemini / Google API key is available
if not os.getenv("GEMINI_API_KEY") and os.getenv("GOOGLE_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.getenv("GOOGLE_API_KEY", "")

from google.adk.agents.llm_agent import Agent
from google.adk.tools import ToolContext

from adk_agents.shopping_coordinator.agent import shopping_coordinator
from app.modules.acp.models import Item
from app.modules.buyer.ledger import buyer_ledger
from app.shopping_agent.orchestrator import shopping_orchestrator


def _extract_budget(text: str) -> float | None:
    t = text.lower()
    m_k_range = re.search(r"(\d+(?:\.\d+)?)\s*(?:k)?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*k\b", t)
    if m_k_range:
        return float(m_k_range.group(2)) * 1000.0
    m_num_range = re.search(r"(\d+)\s*(?:to|-)\s*(\d+)", t)
    if m_num_range and float(m_num_range.group(2)) > 100:
        return float(m_num_range.group(2))
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k\b", t)
    if m_k:
        return float(m_k.group(1)) * 1000.0
    b_match = re.search(r"(?:under|below|less than|max|budget of|around|approx|upto|up to)?\s*(?:rs\.?|inr)?\s*(\d+(?:,\d+)*(?:\.\d+)?)", t)
    if b_match:
        try:
            val = float(b_match.group(1).replace(",", ""))
            if val > 50:
                return val
        except Exception:
            pass
    return None


def _extract_delivery_days(text: str) -> int | None:
    m = re.search(r"(?:within|in|max|under)?\s*(\d+)\s*days?", text.lower())
    if m:
        return int(m.group(1))
    return None


def _extract_size(text: str) -> int | None:
    m = re.search(r"\bsize\s*[:=]?\s*(\d+)\b", text.lower())
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None


def _extract_color(text: str) -> str | None:
    for c in ["blue", "black", "white", "red", "green", "grey", "gray", "navy"]:
        if re.search(rf"\b{c}\b", text.lower()):
            return c
    return None


def _extract_brand(text: str) -> str | None:
    for b in ["adidas", "nike", "puma", "asics", "reebok"]:
        if re.search(rf"\b{b}\b", text.lower()):
            return b
    return None


def check_order_or_watch_status(tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Checks the live status of any active or completed shopping/watch objectives."""
    from app.modules.watch.objective import objective_store

    target_obj = None
    if tool_context and hasattr(tool_context, "state") and tool_context.state:
        watching_id = tool_context.state.get("session:watching_objective_id")
        if watching_id:
            target_obj = objective_store.get_objective(watching_id)

    if not target_obj:
        objs = objective_store.get_all_objectives()
        if objs:
            completed_objs = [o for o in objs if o.status.value == "COMPLETED"]
            if completed_objs:
                target_obj = completed_objs[-1]
            else:
                target_obj = objs[-1]

    if not target_obj:
        return {"status": "NO_OBJECTIVES", "message": "No active or past shopping objectives found."}

    latest = target_obj

    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["session:watch_status"] = latest.status.value
            if latest.purchase_result:
                tool_context.state["session:winning_merchant"] = latest.purchase_result.get("merchant")
                tool_context.state["session:item_purchased"] = latest.purchase_result.get("item_purchased")
                tool_context.state["session:amount_paid_inr"] = latest.purchase_result.get("amount_paid_inr")
        except Exception:
            pass

    is_completed = latest.status.value == "COMPLETED"
    summary_msg = ""
    if is_completed and latest.purchase_result:
        m_name = latest.purchase_result.get("merchant", "the store")
        item_name = latest.purchase_result.get("item_purchased", "item")
        price = latest.purchase_result.get("amount_paid_inr", 0)
        summary_msg = f"PURCHASE_COMPLETED: {m_name} restocked {item_name}. Autonomously purchased for Rs. {price:,.2f} under AP2 Intent Mandate."
    elif latest.status.value == "WATCHING":
        summary_msg = f"WATCHING: Actively tracking merchants for restocks or price drops. {latest.watch_reason or ''}"

    return {
        "status": latest.status.value,
        "is_completed": is_completed,
        "summary": summary_msg,
        "objective_id": latest.objective_id,
        "intent_mandate_id": latest.intent_mandate_id,
        "modality": latest.modality,
        "intent": latest.user_intent,
        "reason": latest.watch_reason,
        "purchase_result": latest.purchase_result,
    }


def check_buyer_balance(tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Returns the current buyer spending authority, available balance, and per-transaction limit."""
    buyer_ledger._load()
    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["user:balance"] = buyer_ledger.available_balance
            tool_context.state["user:per_transaction_limit"] = buyer_ledger.per_transaction_limit
        except Exception:
            pass
    return {
        "available_balance": buyer_ledger.available_balance,
        "per_transaction_limit": buyer_ledger.per_transaction_limit,
        "currency": buyer_ledger.currency,
    }


def run_autonomous_purchase(
    query: str,
    brand: str | None = None,
    category: str | None = "footwear",
    size: int | None = None,
    color: str | None = None,
    max_budget: float | None = None,
    max_delivery_days: int | None = None,
    auto_purchase: bool = True,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Executes the complete end-to-end autonomous purchasing loop as the buyer's representative."""
    if max_delivery_days is None:
        max_delivery_days = _extract_delivery_days(query)

    if max_budget is None:
        max_budget = _extract_budget(query) or 6000.0

    intent = {
        "description": f"Buy {brand or ''} {color or ''} {query} size {size or 'any'}",
        "query": query,
        "brand": brand,
        "category": category or "footwear",
        "max_price": float(max_budget),
        "size": size,
        "color": color,
        "max_delivery_days": max_delivery_days,
        "quantity": 1,
        "auto_purchase": auto_purchase,
    }
    result = shopping_orchestrator.execute_intent(intent=intent, enable_watching=True)

    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["session:current_intent"] = query
            if result.get("success"):
                tool_context.state["session:winning_merchant"] = result.get("merchant", "")
                tool_context.state["session:item_purchased"] = result.get("item_purchased", "")
                tool_context.state["session:amount_paid_inr"] = result.get("amount_paid_inr", 0.0)
                tool_context.state["session:last_order_id"] = result.get("order_id", "")
                tool_context.state["session:last_payment_id"] = result.get("payment_id", "")
                tool_context.state["user:balance"] = result.get("remaining_balance_inr", 0.0)
                tool_context.state["session:ai_reasoning"] = result.get("ai_reasoning", "")
                tool_context.state["session:proposals"] = result.get("proposals", [])
                tool_context.state["session:negotiation_rounds"] = result.get("negotiation_rounds", [])
        except Exception:
            pass

    return result


def delegate_to_shopping_coordinator(
    query: str,
    brand: str | None = None,
    category: str | None = "footwear",
    size: int | None = None,
    color: str | None = None,
    max_budget: float | None = None,
    max_delivery_days: int | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Transfers the shopping search and A2A merchant negotiation task to the Shopping Coordinator."""
    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        if tool_context.state.get("session:winning_proposal"):
            return {
                "status": "ALREADY_COORDINATED",
                "message": "Winning proposal has already been negotiated and selected. Call execute_autonomous_checkout to finalize payment.",
                "winning_proposal": tool_context.state.get("session:winning_proposal"),
            }

    if max_delivery_days is None:
        max_delivery_days = _extract_delivery_days(query)

    if max_budget is None:
        max_budget = _extract_budget(query) or 6000.0

    if size is None:
        size = _extract_size(query)

    if color is None:
        color = _extract_color(query)

    if brand is None:
        brand = _extract_brand(query)

    intent = {
        "description": f"Buy {brand or ''} {color or ''} {query} size {size or 'any'}",
        "query": query,
        "brand": brand,
        "category": category or "footwear",
        "max_price": float(max_budget),
        "size": size,
        "color": color,
        "max_delivery_days": max_delivery_days,
        "quantity": 1,
        "auto_purchase": True,
    }

    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["session:pending_intent"] = intent
            tool_context.state["session:current_intent"] = query
            tool_context.actions.transfer_to_agent = "shopping_coordinator"
        except Exception:
            pass

    return {
        "status": "DELEGATED_TO_COORDINATOR",
        "target_agent": "shopping_coordinator",
        "query": query,
        "brand": brand,
        "size": size,
        "color": color,
        "max_budget": max_budget,
    }


def execute_autonomous_checkout(
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Executes deterministic safety policy verification and Razorpay checkout for the winning proposal."""
    from app.modules.a2a.client import a2a_client
    from app.modules.policy.engine import policy_engine
    from app.modules.razorpay.client import razorpay_client

    if not tool_context or not hasattr(tool_context, "state") or tool_context.state is None:
        return {"success": False, "status": "NO_STATE_CONTEXT", "reason": "No session state available for checkout"}

    winning = tool_context.state.get("session:winning_proposal")
    if not winning:
        return {"success": False, "status": "NO_WINNING_PROPOSAL", "reason": "No winning merchant proposal found to checkout"}

    merchant = winning.get("winning_merchant", "Unknown Merchant")
    merchant_id = winning.get("winning_merchant_id", f"merchant_{merchant.lower()[:1]}")
    item_title = winning.get("winning_item", "Product")
    amount = float(winning.get("final_price_inr", 0.0))
    sku = winning.get("winning_sku", "sku_default")
    intent = dict(tool_context.state.get("session:pending_intent") or {})
    max_budget = float(intent.get("max_price", amount))

    # 1. Resolve authentic Item model from winning proposal
    item_dict = winning.get("item")
    if item_dict and isinstance(item_dict, dict):
        purchased_item = Item(**item_dict)
    else:
        from app.modules.a2a.discovery import merchant_registry
        m_agent = merchant_registry.get_merchant(merchant_id)
        purchased_item = m_agent.get_item(sku) if m_agent else None

    if not purchased_item:
        purchased_item = Item(
            id=sku,
            name=item_title,
            brand=intent.get("brand", "Unknown"),
            category=intent.get("category", "footwear"),
            price=amount,
            currency="INR",
            stock=1,
            attributes={"size": intent.get("size"), "color": intent.get("color")},
        )

    # Allowed merchants from dynamic discovery (both names and IDs)
    cards = a2a_client.discover_merchants()
    allowed_merchants = []
    for c in cards:
        if c.name:
            allowed_merchants.append(c.name)
        if c.provider and c.provider.get("id"):
            allowed_merchants.append(c.provider.get("id"))
    if not allowed_merchants:
        allowed_merchants = ["UrbanKicks", "ShoeKart", "FastFeet", "merchant_a", "merchant_b", "merchant_c"]

    user_intent = {
        "max_price": max_budget,
        "quantity": 1,
        "brand": intent.get("brand") or purchased_item.brand,
        "size": intent.get("size"),
        "color": intent.get("color"),
        "allowed_merchants": allowed_merchants,
    }
    policy_res = policy_engine.evaluate_offer(purchased_item, user_intent=user_intent)
    if not policy_res.allowed:
        return {"success": False, "status": "POLICY_REJECTED", "violations": policy_res.violations}

    if amount > buyer_ledger.available_balance:
        return {"success": False, "status": "POLICY_REJECTED", "violations": ["INSUFFICIENT_BALANCE"]}

    # 2. Execute Razorpay test payment / payout with Route attribution
    order = razorpay_client.create_order(
        amount_inr=amount,
        currency="INR",
        receipt=f"rcpt_{merchant.lower().replace(' ', '_')}",
        notes={"merchant": merchant, "item": item_title, "sku": sku},
        merchant_id=merchant_id,
        merchant_name=merchant,
    )
    payment = razorpay_client.execute_test_payment(
        order_id=order["id"],
        amount_inr=amount,
        merchant_id=merchant_id,
        merchant_name=merchant,
    )
    payment_id = payment.get("id", f"pay_{order['id'][6:]}")
    payout = razorpay_client.execute_payout(
        merchant_id=merchant_id,
        amount_inr=amount,
        merchant_name=merchant,
        narration=f"Autonomous purchase {item_title}",
    )
    payout_id = payout["id"] if payout else f"pout_mock_{order['id'][-8:]}"
    buyer_ledger.record_debit(
        transaction_id=payout_id,
        amount=amount,
        currency="INR",
        merchant_id=merchant_id,
        razorpay_order_id=order["id"],
        razorpay_payment_id=payment_id,
    )

    # Decrement merchant inventory for the purchased item
    try:
        from app.modules.a2a.discovery import merchant_registry
        m_agent = merchant_registry.get_merchant(merchant_id)
        if m_agent:
            curr = m_agent.get_item(sku)
            if curr:
                m_agent.set_stock(sku, max(0, curr.stock - 1))
    except Exception:
        pass

    receipt = {
        "success": True,
        "store": merchant,
        "item": item_title,
        "price_paid_inr": amount,
        "delivery": f"{winning.get('delivery_days', 1)}-day delivery",
        "message": f"Successfully purchased {item_title} from {merchant} for Rs. {amount:,.2f}.",
    }

    try:
        tool_context.state["session:winning_merchant"] = merchant
        tool_context.state["session:item_purchased"] = item_title
        tool_context.state["session:amount_paid_inr"] = amount
    except Exception:
        pass

    return receipt


_model = os.getenv("AGENT_MODEL", "gemini-3.5-flash")
if not _model:
    _model = "gemini-3.5-flash"

buyer_agent = Agent(
    name="buyer_agent",
    model=_model,
    description="Autonomous Buyer Representative & Treasury: Manages intent, policy validation, and Razorpay checkout.",
    instruction="""You are the Autonomous Buyer Agent, representing the user in autonomous e-commerce.

Core Behavior & Minimalist Output:
- Act as a smart personal shopping assistant.
- Your response must be MINIMALISTIC, CLEAN, and NATURAL: 2 to 3 sentences maximum.
- When a purchase succeeds, respond with a concise human confirmation:
  "I have purchased the [Item Name] from [Store Name] for Rs. [Price]. Delivery is scheduled within [X] days."

STRICT NEGATIVE CONSTRAINTS:
- NEVER output markdown headings like "### Autonomous Purchase Summary" or numbered multi-section reports.
- NEVER output AP2 Mandate IDs, closed mandate IDs, Razorpay Order IDs, Payment IDs, or Payout IDs.
- NEVER output or mention user balance, buyer balance, or bank account balance.
- Keep the confirmation completely human, short, and conversational.

Execution Flow:
1. When the user asks to buy or find an item:
   Call `delegate_to_shopping_coordinator` passing query, brand, category, size, color, budget, and delivery deadline.
2. When transferred back from shopping_coordinator:
   - If a winning proposal was negotiated (status: NEGOTIATION_COMPLETE):
     Call `execute_autonomous_checkout` to execute payment.
     Immediately reply to the user with the 2-sentence confirmation. DO NOT call any other tool.
   - If placed in WATCHING state (status: WATCHING):
     Reply cleanly to the user in 2 sentences explaining that no store currently meets their price or stock requirement (mention which store is out of stock or above budget), and confirm that you have placed the request on WATCH under an AP2 Intent Mandate and will automatically buy it when stock arrives or the price drops. DO NOT call checkout.
3. If the user asks about the status of an order or watch (e.g. "Did you buy it?", "Any updates?"), OR asks any follow-up question:
   Call `check_order_or_watch_status`.
   - If the status is COMPLETED and was purchased in the background via restock, confirm naturally in 2 sentences:
     "ShoeKart restocked the Adidas Runfalcon 3! Since your Intent Mandate authorized it under Rs. 4,000, I completed the purchase for Rs. 3,550. Delivery is scheduled within 5 days."
   - If still WATCHING, confirm that you are actively monitoring for restocks or price drops to execute automatically.
4. On follow-up questions asking "Why this only?" or "Why did you choose this store?":
   Briefly explain why this store was selected over competitors using the session proposals and negotiation.
5. If payment fails, report the natural explanation in 1-2 sentences.""",
    sub_agents=[shopping_coordinator],
    tools=[
        delegate_to_shopping_coordinator,
        execute_autonomous_checkout,
        run_autonomous_purchase,
        check_order_or_watch_status,
    ],
)

# Canonical aliases
root_agent = buyer_agent
shopping_agent = buyer_agent
shopping_coordinator_agent = shopping_coordinator



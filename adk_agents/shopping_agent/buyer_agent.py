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
from typing import Any, Dict, Optional
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
from app.modules.audit.adk_plugin import a2a_audit_plugin, A2AAuditTracePlugin
from app.modules.buyer.ledger import buyer_ledger
from app.shopping_agent.orchestrator import shopping_orchestrator


def check_buyer_balance(tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """Returns the current buyer spending authority, available balance, and per-transaction limit."""
    buyer_ledger._load()
    info = {
        "available_balance": buyer_ledger.available_balance,
        "per_transaction_limit": buyer_ledger.per_transaction_limit,
        "currency": buyer_ledger.currency,
    }
    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["user:balance"] = buyer_ledger.available_balance
            tool_context.state["user:per_transaction_limit"] = buyer_ledger.per_transaction_limit
        except Exception:
            pass
    return info


def run_autonomous_purchase(
    query: str = "shoes",
    brand: Optional[str] = None,
    category: str = "footwear",
    size: Optional[int] = 10,
    color: Optional[str] = "blue",
    max_budget: float = 5000.0,
    max_delivery_days: Optional[int] = None,
    auto_purchase: bool = True,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Executes the complete end-to-end autonomous purchasing loop as the buyer's representative.

    Args:
        query: Product or model keywords (e.g. 'shoes', 'sneakers', 'Runfalcon 3').
        brand: Specific brand constraint if requested (e.g. 'Adidas', 'Nike', 'Puma').
        category: Broad product category (default 'footwear').
        size: Shoe size (e.g. 9, 10).
        color: Color preference (e.g. 'blue', 'black', 'white').
        max_budget: Maximum price ceiling in INR.
        max_delivery_days: Delivery deadline in days (e.g. 2 for 'within 2 days' or 'deliver in 2 days').
        auto_purchase: True to proceed with autonomous checkout and payment upon selection.
        tool_context: ADK ToolContext injected by the ADK runtime.
    """
    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["session:current_intent"] = query
            tool_context.state["user:balance"] = buyer_ledger.available_balance
        except Exception:
            pass

    q_lower = query.lower()
    if not brand:
        for b in ["adidas", "nike", "puma"]:
            if b in q_lower:
                brand = b.capitalize()
                break
    if not color:
        for c in ["blue", "black", "white", "red"]:
            if c in q_lower:
                color = c
                break
    if max_delivery_days is None:
        m = re.search(r"(\d+)\s*days?", q_lower)
        if m:
            max_delivery_days = int(m.group(1))

    intent = {
        "description": f"Buy {brand or ''} {color or ''} {query} size {size or 'any'}",
        "query": query,
        "brand": brand,
        "category": category,
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
            tool_context.state["user:balance"] = buyer_ledger.available_balance
            if result.get("success"):
                tool_context.state["user:balance"] = result.get("remaining_balance_inr", buyer_ledger.available_balance)
                tool_context.state["session:last_order_id"] = result.get("order_id", "")
                tool_context.state["session:last_payment_id"] = result.get("payment_id", "")
                tool_context.state["session:last_payout_id"] = result.get("razorpayx_payout_id", "")
                tool_context.state["session:winning_merchant"] = result.get("merchant", "")
                tool_context.state["session:item_purchased"] = result.get("item_purchased", "")
                tool_context.state["session:amount_paid_inr"] = result.get("amount_paid_inr", 0.0)
                tool_context.state["session:ai_reasoning"] = result.get("ai_reasoning", "")
                tool_context.state["session:proposals"] = result.get("proposals", [])
                tool_context.state["session:negotiation_rounds"] = result.get("negotiation_rounds", [])
        except Exception:
            pass

    return result


_model = os.getenv("AGENT_MODEL", "gemini-3.5-flash-lite")
if _model in ["gemini-3.6-flash", ""] or not _model:
    _model = "gemini-3.5-flash-lite"

buyer_agent = Agent(
    name="buyer_agent",
    model=_model,
    description="The user's autonomous purchasing representative in the multi-merchant A2A network.",
    instruction="""You are the Autonomous Buyer Agent, representing the user in autonomous e-commerce.

Core Philosophy & Tone:
- You act as a smart, capable personal shopping assistant.
- Keep default purchase confirmations simple, clean, and natural for a typical human user.
- Focus on what the user cares about: the product bought, the store, the price paid, and delivery time.
- Avoid internal developer jargon (do NOT output "Winning merchant", "AP2 Open/Closed Mandates", "Razorpay Order ID", "Payout ID", "pout_...", "pay_...", or internal balance/ledger amounts) in the default confirmation.

Execution Behavior:
1. When the user asks to buy an item (e.g. "Buy me shoes under 5000, deliver in 2 days" or "Buy Adidas blue sneakers, size 10, under Rs. 5,000"):
   Extract the user's constraints and execute the purchase autonomously using `run_autonomous_purchase`.
   Upon completion, return a natural, concise confirmation message:
   - What was ordered: Brand, item name, variant (color and size).
   - Where it was bought from: Store/merchant name.
   - Price paid: Total price in Rs.
   - Delivery: Expected delivery time (e.g. express 1-day delivery).
   - Confirmation that payment has been successfully completed.

2. On follow-up questions asking for reasoning (e.g. "Why this only?", "Why did you choose FastFeet?", "Why not other stores?", "Did you negotiate?"):
   Explain your autonomous multi-merchant decision process and A2A negotiation transparently:
   - Detail the merchants discovered (e.g. ShoeKart, UrbanKicks, FastFeet).
   - Explain competitor evaluation (e.g. UrbanKicks had no stock; ShoeKart offered Rs. 4,899 with 3-day delivery).
   - Detail the A2A negotiation: FastFeet was originally listed at Rs. 5,099 (above budget), but you countered using competing market prices to negotiate them down to Rs. 4,650 (saving Rs. 449).
   - Summarize why the final decision won: Lowest price AND fastest delivery.

3. Payment Failures & Safety Policy Blocks:
   - If payment fails or is blocked by policy, explain the plain-English reason (e.g. "The item is currently out of stock across all stores" or "The purchase was declined because the price exceeds your spending limit").
   - Do NOT dump internal ledger calculations, balance math, or technical stack traces.

4. Formatting:
   - Format all currency figures using 'Rs.' rather than Unicode symbols, and avoid emoji icons.""",
    tools=[
        run_autonomous_purchase,
        check_buyer_balance,
    ],
)

# Canonical aliases
shopping_agent = buyer_agent
root_agent = buyer_agent

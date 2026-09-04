"""ADK Entry point for ShoeKart Merchant Agent (Merchant B)."""

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv()

if not os.getenv("GEMINI_API_KEY") and os.getenv("GOOGLE_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.getenv("GOOGLE_API_KEY", "")

from google.adk.agents.llm_agent import Agent
from google.adk.tools import ToolContext

from app.merchants import merchant_b

_model = os.getenv("AGENT_MODEL", "gemini-3.5-flash")
if not _model:
    _model = "gemini-3.5-flash"


def search_shoekart_catalog(
    query: str = "shoes",
    size: int | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Queries ShoeKart clearance catalog and discount stock."""
    items = merchant_b.search_catalog(query=query, filters={"size": size, "color": color})
    return {"merchant": "ShoeKart", "items": [it.model_dump() for it in items], "count": len(items)}


def negotiate_shoekart_price(
    sku: str,
    counter_price: float,
) -> dict[str, Any]:
    """Evaluates clearance discounts for a specific SKU with ShoeKart."""
    item = merchant_b.get_item(sku)
    if not item:
        return {"merchant": "ShoeKart", "accepted": False, "reason": f"SKU '{sku}' not found in catalog"}
    prop = merchant_b.create_proposal(query=item.brand, filters={"size": item.attributes.get("size"), "color": item.attributes.get("color")})
    if not prop:
        return {"merchant": "ShoeKart", "accepted": False, "reason": "Unable to generate baseline proposal"}
    counter = merchant_b.negotiate(prop, competing_price=float(counter_price))
    if counter:
        return {
            "merchant": "ShoeKart",
            "accepted": True,
            "proposed_price": counter.proposed_price,
            "savings": round(prop.proposed_price - counter.proposed_price, 2),
            "commercial_pitch": counter.commercial_pitch,
        }
    return {
        "merchant": "ShoeKart",
        "accepted": False,
        "price": prop.proposed_price,
        "reason": f"Counter price Rs. {counter_price:,.2f} is below clearance margin floor",
    }


def get_shoekart_info() -> dict[str, Any]:
    """Returns ShoeKart outlet info, clearance policies, and 3-to-6 day delivery."""
    return {
        "store": "ShoeKart",
        "merchant_id": "merchant_b",
        "standard_delivery_days": 6,
        "specialty": "Clearance footwear and discount warehouse",
        "accepted_currencies": ["INR"],
    }


def transfer_to_buyer_agent(
    confirmation: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Confirms store availability or proposal and transfers control to buyer_agent."""
    if tool_context and hasattr(tool_context, "actions") and tool_context.actions is not None:
        try:
            tool_context.actions.transfer_to_agent = "buyer_agent"
        except Exception:
            pass
    return {
        "status": "TRANSFERRED_TO_BUYER",
        "merchant": "ShoeKart",
        "confirmation": confirmation,
    }


shoekart_merchant = Agent(
    name="shoekart_merchant",
    model=_model,
    description="Merchant B (ShoeKart): Clearance footwear outlet agent with low-stock discount pricing and 6-day delivery.",
    instruction="""You are the autonomous sales agent for ShoeKart.
Your catalog offers footwear deals with 3-to-6-day delivery.
Respond to customer and agent inquiries regarding clearance stock and discount pricing.
When transferred to by the shopping coordinator:
Call `transfer_to_buyer_agent` with a concise store confirmation (e.g. "ShoeKart confirms Adidas Runfalcon 3 Blue Size 10 terms" or "ShoeKart confirms item is currently out of stock") so the buyer agent can finalize checkout or initiate WATCH mode.""",
    tools=[search_shoekart_catalog, negotiate_shoekart_price, get_shoekart_info, transfer_to_buyer_agent],
)

root_agent = shoekart_merchant
__all__ = ["get_shoekart_info", "negotiate_shoekart_price", "root_agent", "search_shoekart_catalog", "shoekart_merchant", "transfer_to_buyer_agent"]

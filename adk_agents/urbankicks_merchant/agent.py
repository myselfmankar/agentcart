"""ADK Entry point for UrbanKicks Merchant Agent (Merchant A)."""

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

from app.merchants import merchant_a

_model = os.getenv("AGENT_MODEL", "gemini-3.5-flash")
if not _model:
    _model = "gemini-3.5-flash"


def search_urbankicks_catalog(
    query: str = "shoes",
    size: int | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Queries UrbanKicks live inventory, available sizes, and standard pricing."""
    items = merchant_a.search_catalog(query=query, filters={"size": size, "color": color})
    return {"merchant": "UrbanKicks", "items": [it.model_dump() for it in items], "count": len(items)}


def negotiate_urbankicks_price(
    sku: str,
    counter_price: float,
) -> dict[str, Any]:
    """Evaluates a buyer counter-offer for a specific SKU against UrbanKicks commercial policy."""
    item = merchant_a.get_item(sku)
    if not item:
        return {"merchant": "UrbanKicks", "accepted": False, "reason": f"SKU '{sku}' not found in catalog"}
    prop = merchant_a.create_proposal(query=item.brand, filters={"size": item.attributes.get("size"), "color": item.attributes.get("color")})
    if not prop:
        return {"merchant": "UrbanKicks", "accepted": False, "reason": "Unable to generate baseline proposal"}
    counter = merchant_a.negotiate(prop, competing_price=float(counter_price))
    if counter:
        return {
            "merchant": "UrbanKicks",
            "accepted": True,
            "proposed_price": counter.proposed_price,
            "savings": round(prop.proposed_price - counter.proposed_price, 2),
            "commercial_pitch": counter.commercial_pitch,
        }
    return {
        "merchant": "UrbanKicks",
        "accepted": False,
        "price": prop.proposed_price,
        "reason": f"Counter price Rs. {counter_price:,.2f} is below merchant margin floor",
    }


def get_urbankicks_info() -> dict[str, Any]:
    """Returns store metadata, standard delivery speed (4 days), and terms."""
    return {
        "store": "UrbanKicks",
        "merchant_id": "merchant_a",
        "standard_delivery_days": 4,
        "specialty": "Urban sneakers and streetwear",
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
        "merchant": "UrbanKicks",
        "confirmation": confirmation,
    }


urbankicks_merchant = Agent(
    name="urbankicks_merchant",
    model=_model,
    description="Merchant A (UrbanKicks): Urban sneakers and streetwear seller agent with volume discount policies and 4-day delivery.",
    instruction="""You are the autonomous sales agent for UrbanKicks.
Your catalog offers urban sneakers and streetwear with standard 4-day delivery.
Respond to customer and agent inquiries regarding catalog items, stock, and volume discounts.
When transferred to by the shopping coordinator:
Call `transfer_to_buyer_agent` with a concise store confirmation (e.g. "UrbanKicks confirms terms" or "UrbanKicks confirms inventory status") so the buyer agent can finalize checkout or initiate WATCH mode.""",
    tools=[search_urbankicks_catalog, negotiate_urbankicks_price, get_urbankicks_info, transfer_to_buyer_agent],
)

root_agent = urbankicks_merchant
__all__ = ["get_urbankicks_info", "negotiate_urbankicks_price", "root_agent", "search_urbankicks_catalog", "urbankicks_merchant", "transfer_to_buyer_agent"]

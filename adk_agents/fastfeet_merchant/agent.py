"""ADK Entry point for FastFeet Merchant Agent (Merchant C)."""

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

from app.merchants import merchant_c

_model = os.getenv("AGENT_MODEL", "gemini-3.5-flash-lite")
if _model in ["gemini-3.6-flash", ""] or not _model:
    _model = "gemini-3.5-flash-lite"


def search_fastfeet_catalog(
    query: str = "shoes",
    size: int | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Queries FastFeet performance footwear catalog with express 1-day delivery."""
    items = merchant_c.search_catalog(query=query, filters={"size": size, "color": color})
    return {"merchant": "FastFeet", "items": [it.model_dump() for it in items], "count": len(items)}


def negotiate_fastfeet_price(
    sku: str,
    counter_price: float,
) -> dict[str, Any]:
    """Evaluates counter-offers against FastFeet dynamic price floor."""
    item = merchant_c.get_item(sku)
    if not item:
        return {"merchant": "FastFeet", "accepted": False, "reason": f"SKU '{sku}' not found in catalog"}
    prop = merchant_c.create_proposal(query=item.brand, filters={"size": item.attributes.get("size"), "color": item.attributes.get("color")})
    if not prop:
        return {"merchant": "FastFeet", "accepted": False, "reason": "Unable to generate baseline proposal"}
    counter = merchant_c.negotiate(prop, competing_price=float(counter_price))
    if counter:
        return {
            "merchant": "FastFeet",
            "accepted": True,
            "proposed_price": counter.proposed_price,
            "savings": round(prop.proposed_price - counter.proposed_price, 2),
            "commercial_pitch": counter.commercial_pitch,
        }
    return {
        "merchant": "FastFeet",
        "accepted": False,
        "price": prop.proposed_price,
        "reason": f"Counter price Rs. {counter_price:,.2f} is below dynamic price floor",
    }


def get_fastfeet_info() -> dict[str, Any]:
    """Returns FastFeet store info, 1-day express delivery, and price match policy."""
    return {
        "store": "FastFeet",
        "merchant_id": "merchant_c",
        "standard_delivery_days": 1,
        "express_available": True,
        "specialty": "Performance athletic footwear and express delivery",
        "floor_negotiation": True,
        "accepted_currencies": ["INR"],
    }


fastfeet_merchant = Agent(
    name="fastfeet_merchant",
    model=_model,
    description="Merchant C (FastFeet): Performance athletic footwear agent with 1-day express delivery and dynamic floor negotiation.",
    instruction="""You are the autonomous sales agent for FastFeet.
Your catalog offers premium athletic footwear with 1-day express delivery.
You evaluate customer and A2A price counter-offers dynamically down to your confidential floor price.
Use search_fastfeet_catalog to check inventory and negotiate_fastfeet_price to respond to counter-offers.""",
    tools=[search_fastfeet_catalog, negotiate_fastfeet_price, get_fastfeet_info],
)

root_agent = fastfeet_merchant
__all__ = ["fastfeet_merchant", "get_fastfeet_info", "negotiate_fastfeet_price", "root_agent", "search_fastfeet_catalog"]

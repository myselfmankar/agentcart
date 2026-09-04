"""ADK Entry point for A2A Shopping Coordinator Agent."""

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

from adk_agents.fastfeet_merchant.agent import fastfeet_merchant
from adk_agents.shoekart_merchant.agent import shoekart_merchant
from adk_agents.urbankicks_merchant.agent import urbankicks_merchant
from app.merchants import merchant_a, merchant_b, merchant_c
from app.modules.a2a.client import a2a_client

_model = os.getenv("AGENT_MODEL", "gemini-3.5-flash")
if not _model:
    _model = "gemini-3.5-flash"


def discover_a2a_merchants() -> list[dict[str, Any]]:
    """Discovers all registered merchant agents dynamically on the A2A network."""
    cards = a2a_client.discover_merchants()
    return [
        {
            "merchant_id": card.provider.get("id"),
            "name": card.name,
            "url": card.url,
            "protocols": card.protocols,
            "negotiable": card.provider.get("negotiable", False),
        }
        for card in cards
    ]


def compare_merchant_offers(category: str = "footwear") -> dict[str, Any]:
    """Scans and ranks current merchant offers by price, stock availability, and delivery speed."""
    cards = a2a_client.discover_merchants()
    merchant_names = [c.name for c in cards]
    return {
        "status": "COMPARISON_ACTIVE",
        "merchants_evaluated": merchant_names,
        "criteria": ["price", "delivery_days", "stock", "margin_floor_discount"],
    }


def query_all_merchants_catalog(
    query: str = "shoes",
    size: int | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Polls all merchant agents for live inventory, available sizes, and standard prices."""
    filters = {}
    if size is not None:
        filters["size"] = size
    if color:
        filters["color"] = color

    res_a = merchant_a.search_catalog(query=query, filters=filters)
    res_b = merchant_b.search_catalog(query=query, filters=filters)
    res_c = merchant_c.search_catalog(query=query, filters=filters)
    return {
        "UrbanKicks": {"items": [it.model_dump() for it in res_a], "count": len(res_a), "delivery_days": 4},
        "ShoeKart": {"items": [it.model_dump() for it in res_b], "count": len(res_b), "delivery_days": 6},
        "FastFeet": {"items": [it.model_dump() for it in res_c], "count": len(res_c), "delivery_days": 1},
    }


def coordinate_merchant_proposals_and_negotiate(
    query: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Coordinates with registered merchant agents over A2A.

    Evaluates live inventory, solicits proposals, negotiates discounts dynamically,
    and transfers back to buyer_agent with the winning proposal.
    """
    from app.shopping_agent.ai_buyer import ai_buyer_agent

    intent = {}
    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        intent = dict(tool_context.state.get("session:pending_intent") or {})

    if query:
        intent["query"] = query

    decision = ai_buyer_agent.evaluate_and_negotiate(user_intent=intent)

    if not decision.is_successful:
        import time
        import uuid
        from app.modules.watch.objective import ObjectiveStatus, ShoppingObjective, objective_store

        obj_id = f"obj_{uuid.uuid4().hex[:8]}"
        objective = ShoppingObjective(
            objective_id=obj_id,
            user_intent=intent,
            status=ObjectiveStatus.WATCHING,
            watch_reason=decision.reasoning or "No qualifying offers currently exist within budget/stock. Placed in WATCHING mode.",
            created_at=time.time(),
            updated_at=time.time(),
        )
        objective_store.save_objective(objective)

        if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
            try:
                tool_context.state["session:watching_objective_id"] = obj_id
                tool_context.state["session:watch_status"] = "WATCHING"
                tool_context.state["session:watch_reason"] = decision.reasoning
                tool_context.actions.transfer_to_agent = "buyer_agent"
            except Exception:
                pass

        return {
            "status": "WATCHING",
            "objective_id": obj_id,
            "message": "No qualifying offer currently exists within budget or stock. Shopping objective placed in WATCHING state.",
            "reasoning": decision.reasoning,
            "proposals": [p.to_dict() for p in decision.all_proposals],
        }

    winning = decision.winning_proposal
    winning_dict = winning.to_dict()
    winner_merchant = winning.merchant_name
    winner_merchant_id = winning.merchant_id
    winner_sku = winning.item.id
    winner_item = winning.item.name
    winner_price = winning.proposed_price
    delivery_days = min(winning.standard_delivery_days, winning.express_delivery_days)

    summary = {
        "status": "NEGOTIATION_COMPLETE",
        "winning_merchant": winner_merchant,
        "winning_merchant_id": winner_merchant_id,
        "winning_sku": winner_sku,
        "winning_item": winner_item,
        "final_price_inr": winner_price,
        "delivery_days": delivery_days,
        "reasoning": decision.reasoning,
        "proposals": [p.to_dict() for p in decision.all_proposals],
        "negotiation_rounds": decision.negotiation_rounds,
        "item": winning_dict["item"],
    }

    if tool_context and hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["session:winning_merchant"] = winner_merchant
            tool_context.state["session:winning_merchant_id"] = winner_merchant_id
            tool_context.state["session:item_purchased"] = winner_item
            tool_context.state["session:amount_paid_inr"] = winner_price
            tool_context.state["session:winning_sku"] = winner_sku
            tool_context.state["session:winning_proposal"] = summary
            tool_context.state["session:ai_reasoning"] = decision.reasoning
            tool_context.state["session:proposals"] = summary["proposals"]
            tool_context.state["session:negotiation_rounds"] = decision.negotiation_rounds
            tool_context.actions.transfer_to_agent = "buyer_agent"
        except Exception:
            pass

    return summary


shopping_coordinator = Agent(
    name="shopping_coordinator",
    model=_model,
    description="A2A Shopping Coordinator: Discovers merchants, gathers proposals, and coordinates price negotiations across stores.",
    instruction="""You are the A2A Shopping Coordinator.
You coordinate between the buyer representative and multiple merchant agents (UrbanKicks, ShoeKart, FastFeet).
Your role is to discover active stores, solicit proposals over A2A, and conduct price/delivery comparisons and counter-negotiations.

Execution:
When delegated a shopping search from the buyer agent, call `coordinate_merchant_proposals_and_negotiate` to query live merchant catalogs, evaluate trade-offs, conduct A2A negotiations to achieve the best price and fastest delivery, and transfer control back to `buyer_agent` with the winning proposal.""",
    sub_agents=[shoekart_merchant, urbankicks_merchant, fastfeet_merchant],
    tools=[
        discover_a2a_merchants,
        compare_merchant_offers,
        query_all_merchants_catalog,
        coordinate_merchant_proposals_and_negotiate,
    ],
)

root_agent = shopping_coordinator
__all__ = [
    "compare_merchant_offers",
    "coordinate_merchant_proposals_and_negotiate",
    "discover_a2a_merchants",
    "query_all_merchants_catalog",
    "root_agent",
    "shopping_coordinator",
]

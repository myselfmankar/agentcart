"""Shopping Agent alias entrypoint for Google ADK CLI."""

from adk_agents.shopping_agent.buyer_agent import (
    buyer_agent,
    check_buyer_balance,
    root_agent,
    run_autonomous_purchase,
    shopping_agent,
)

execute_autonomous_shopping_intent = run_autonomous_purchase

__all__ = [
    "buyer_agent",
    "check_buyer_balance",
    "execute_autonomous_shopping_intent",
    "root_agent",
    "run_autonomous_purchase",
    "shopping_agent",
]

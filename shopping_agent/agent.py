"""Shopping Agent alias entrypoint for Google ADK CLI."""

from adk_agents.shopping_agent.buyer_agent import (
    buyer_agent,
    shopping_agent,
    root_agent,
    run_autonomous_purchase,
    check_buyer_balance,
)

execute_autonomous_shopping_intent = run_autonomous_purchase

__all__ = [
    "buyer_agent",
    "shopping_agent",
    "root_agent",
    "run_autonomous_purchase",
    "execute_autonomous_shopping_intent",
    "check_buyer_balance",
]

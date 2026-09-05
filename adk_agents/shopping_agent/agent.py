"""ADK Entry point for Autonomous Buyer Agent."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from .buyer_agent import (
    buyer_agent,
    check_buyer_balance,
    check_order_or_watch_status,
    delegate_to_shopping_coordinator,
    execute_autonomous_checkout,
    root_agent,
    run_autonomous_purchase,
    shopping_agent,
    shopping_coordinator,
)

from google.adk.apps.app import App, ContextCacheConfig

app = App(
    name="shopping_agent",
    root_agent=root_agent,
    context_cache_config=ContextCacheConfig(),
)

execute_autonomous_shopping_intent = run_autonomous_purchase

__all__ = [
    "app",
    "buyer_agent",
    "check_buyer_balance",
    "check_order_or_watch_status",
    "delegate_to_shopping_coordinator",
    "execute_autonomous_checkout",
    "execute_autonomous_shopping_intent",
    "root_agent",
    "run_autonomous_purchase",
    "shopping_agent",
    "shopping_coordinator",
]

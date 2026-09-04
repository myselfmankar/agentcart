"""ADK Entry point for Autonomous Buyer Agent."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from .buyer_agent import (
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

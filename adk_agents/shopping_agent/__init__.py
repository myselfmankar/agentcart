"""Google ADK Shopping Agent package."""

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

__all__ = [
    "buyer_agent",
    "shopping_agent",
    "root_agent",
    "run_autonomous_purchase",
    "check_buyer_balance",
]

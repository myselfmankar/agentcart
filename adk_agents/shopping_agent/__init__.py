"""Google ADK Shopping Agent package."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from .buyer_agent import (
    buyer_agent,
    check_buyer_balance,
    root_agent,
    run_autonomous_purchase,
    shopping_agent,
)

__all__ = [
    "buyer_agent",
    "check_buyer_balance",
    "root_agent",
    "run_autonomous_purchase",
    "shopping_agent",
]

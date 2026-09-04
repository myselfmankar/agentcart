"""Merchant Agent B: ShoeKart Autonomous Sales Agent.

Acts as the commercial representative for ShoeKart:
- Clearance and value outlet.
- Strictly enforces tight margins, no negotiation on clearance stock.
- Serves A2A requests (proposals, checkout creation, checkout completion).
"""

from pathlib import Path

from app.merchants.base_merchant_agent import BaseMerchantAgent


class MerchantAgentB(BaseMerchantAgent):
    """Autonomous Merchant Agent for ShoeKart."""

    def __init__(self, base_dir: Path | None = None, base_url: str | None = None):
        merchant_dir = base_dir or Path(__file__).resolve().parent.parent
        super().__init__(
            merchant_id="merchant_b",
            base_dir=merchant_dir,
            catalog_filename="catalog.json",
            policy_filename="policy.json",
            base_url=base_url or "http://localhost:8000/a2a/merchant_b",
        )


# Singleton agent instance
merchant_agent_b = MerchantAgentB()

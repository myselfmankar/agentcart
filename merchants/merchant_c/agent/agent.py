"""Merchant Agent C: FastFeet Autonomous Sales Agent.

Acts as the commercial representative for FastFeet:
- Maximize inventory turnover.
- Dynamic pricing, aggressive counter-negotiation to undercut competitors.
- Guarantees FREE 1-day express delivery.
- Serves A2A requests (proposals, negotiation, checkout creation, checkout completion).
"""

from pathlib import Path

from app.merchants.base_merchant_agent import BaseMerchantAgent


class MerchantAgentC(BaseMerchantAgent):
    """Autonomous Merchant Agent for FastFeet."""

    def __init__(self, base_dir: Path | None = None, base_url: str | None = None):
        merchant_dir = base_dir or Path(__file__).resolve().parent.parent
        super().__init__(
            merchant_id="merchant_c",
            base_dir=merchant_dir,
            catalog_filename="catalog.json",
            policy_filename="policy.json",
            base_url=base_url or "http://localhost:8000/a2a/merchant_c",
        )


# Singleton agent instance
merchant_agent_c = MerchantAgentC()

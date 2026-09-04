"""Merchant Agent A: UrbanKicks Autonomous Sales Agent.

Acts as the commercial representative for UrbanKicks:
- Maximize conversion with volume discounts.
- Enforces deterministic pricing, discount, and fulfillment policies.
- Serves A2A requests (proposals, checkout creation, checkout completion).
"""

from pathlib import Path

from app.merchants.base_merchant_agent import BaseMerchantAgent


class MerchantAgentA(BaseMerchantAgent):
    """Autonomous Merchant Agent for UrbanKicks."""

    def __init__(self, base_dir: Path | None = None, base_url: str | None = None):
        merchant_dir = base_dir or Path(__file__).resolve().parent.parent
        super().__init__(
            merchant_id="merchant_a",
            base_dir=merchant_dir,
            catalog_filename="catalog.json",
            policy_filename="policy.json",
            base_url=base_url or "http://localhost:8000/a2a/merchant_a",
        )


# Singleton agent instance
merchant_agent_a = MerchantAgentA()

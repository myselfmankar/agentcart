"""Unified Autonomous Merchant Agents for Agentic Commerce.

Exports the independent merchant agents:
- merchant_a: UrbanKicks (Volume discounts, 4-day delivery)
- merchant_b: ShoeKart (Clearance outlet, low stock, 6-day delivery)
- merchant_c: FastFeet (Dynamic counter-negotiation, 1-day express delivery)
"""

from app.merchants.base_merchant_agent import BaseMerchantAgent as Merchant
from merchants.merchant_a.agent.agent import merchant_agent_a as merchant_a
from merchants.merchant_b.agent.agent import merchant_agent_b as merchant_b
from merchants.merchant_c.agent.agent import merchant_agent_c as merchant_c

__all__ = [
    "Merchant",
    "merchant_a",
    "merchant_b",
    "merchant_c",
]

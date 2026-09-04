"""A2A Merchant Discovery and Protocol Communication Adapter.

Discovers and indexes available Merchant Agents in the commerce network.
Provides a protocol-faithful A2A boundary interface between the Shopping Agent
and registered Merchant Agents.
"""

from typing import Any, Dict, List, Optional
from app.modules.a2a.agent_card import AgentCard, make_merchant_agent_card
from app.modules.acp.models import AuthoritativeCheckoutToken, CheckoutSession, Item
from app.modules.audit.trail import audit_trail


class MerchantRegistry:
    """Registry for discovering merchant agents and their capabilities."""

    def __init__(self):
        self._merchants: Dict[str, Any] = {}
        self._cards: Dict[str, AgentCard] = {}
        self._bootstrap_default_merchants()

    def _bootstrap_default_merchants(self):
        try:
            from merchants.merchant_a.agent.agent import merchant_agent_a
            from merchants.merchant_b.agent.agent import merchant_agent_b
            from merchants.merchant_c.agent.agent import merchant_agent_c

            for agent in [merchant_agent_a, merchant_agent_b, merchant_agent_c]:
                self.register_merchant(agent, agent.get_agent_card())
        except Exception as e:
            # Fallback for dynamic / test environments
            pass

    def register_merchant(self, merchant_agent: Any, card: Optional[AgentCard] = None):
        merchant_id = getattr(merchant_agent, "merchant_id", None)
        if not merchant_id and hasattr(card, "provider"):
            merchant_id = card.provider.get("id")

        if card is None and hasattr(merchant_agent, "get_agent_card"):
            card = merchant_agent.get_agent_card()
        elif card is None:
            name = getattr(merchant_agent, "merchant_name", merchant_id)
            card = make_merchant_agent_card(merchant_id, name, f"{name} Commerce Agent")

        self._merchants[merchant_id] = merchant_agent
        self._cards[merchant_id] = card

    def get_merchant(self, merchant_id: str) -> Optional[Any]:
        return self._merchants.get(merchant_id)

    def list_merchants(self) -> List[Any]:
        return list(self._merchants.values())

    def get_agent_cards(self) -> List[AgentCard]:
        return list(self._cards.values())

    def get_card(self, merchant_id: str) -> Optional[AgentCard]:
        return self._cards.get(merchant_id)


merchant_registry = MerchantRegistry()


class A2AMerchantAdapter:
    """Dispatches requests across the A2A protocol boundary to merchant agents."""

    def __init__(self, registry: Optional[MerchantRegistry] = None):
        self.registry = registry or merchant_registry

    def discover_merchants(self, objective_id: str = "obj_default") -> List[AgentCard]:
        cards = self.registry.get_agent_cards()
        for card in cards:
            audit_trail.log_event(
                event_type="merchant.discovered",
                objective_id=objective_id,
                details={"merchant_id": card.provider.get("id"), "merchant_name": card.name},
            )
        return cards

    def search_catalog(
        self,
        merchant_id: str,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
        objective_id: str = "obj_default",
    ) -> List[Item]:
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            raise ValueError(f"A2A: Merchant {merchant_id} not discovered in network")
        items = merchant.search_catalog(query=query, filters=filters)
        return items

    def create_checkout(
        self,
        merchant_id: str,
        item_id: str,
        quantity: int = 1,
        agreed_price: Optional[float] = None,
        objective_id: str = "obj_default",
    ) -> CheckoutSession:
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            raise ValueError(f"A2A: Merchant {merchant_id} not found")
        session = merchant.create_checkout(item_id, quantity, agreed_price=agreed_price)
        audit_trail.log_event(
            event_type="checkout.created",
            objective_id=objective_id,
            details={
                "merchant_id": merchant_id,
                "session_id": session.id,
                "total_amount": session.total_amount,
                "currency": session.currency,
            },
        )
        return session

    def sign_authoritative_checkout(
        self,
        merchant_id: str,
        session_id: str,
        objective_id: str = "obj_default",
    ) -> AuthoritativeCheckoutToken:
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            raise ValueError(f"A2A: Merchant {merchant_id} not found")
        token = merchant.sign_authoritative_checkout(session_id)
        audit_trail.log_event(
            event_type="checkout.updated",
            objective_id=objective_id,
            details={
                "merchant_id": merchant_id,
                "session_id": session_id,
                "checkout_hash": token.checkout_hash,
                "authoritative_total": token.total_amount,
            },
        )
        return token

    def complete_checkout(
        self,
        merchant_id: str,
        session_id: str,
        payment_id: str,
        objective_id: str = "obj_default",
    ) -> CheckoutSession:
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            raise ValueError(f"A2A: Merchant {merchant_id} not found")
        return merchant.complete_checkout(session_id, payment_id)


a2a_merchant_adapter = A2AMerchantAdapter()
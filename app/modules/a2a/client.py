"""A2A (Agent-to-Agent) Protocol Client for Buyer Agent.

Implements the protocol-faithful communication boundary between the Buyer Agent
and independent Merchant Agents.

The Buyer Agent communicates exclusively through this client:
- Merchant discovery via A2A Agent Cards
- Proposal solicitation over A2A
- Dynamic 1-to-1 negotiation dialogues over A2A
- Authoritative ACP checkout session creation and completion
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.modules.a2a.agent_card import AgentCard
from app.modules.a2a.discovery import merchant_registry
from app.modules.acp.models import (
    AuthoritativeCheckoutToken,
    CheckoutSession,
    Item,
    MerchantProposal,
)
from app.modules.audit.trail import audit_trail

logger = logging.getLogger("a2a.client")


class A2AClient:
    """Client used by the Buyer Agent to communicate with independent Merchant Agents."""

    def __init__(self, registry=None):
        self.registry = registry or merchant_registry

    def discover_merchants(self, objective_id: str = "obj_default") -> List[AgentCard]:
        """Discovers active merchant agents and retrieves their A2A Agent Cards."""
        cards = self.registry.get_agent_cards()
        for card in cards:
            audit_trail.log_event(
                event_type="merchant.discovered",
                objective_id=objective_id,
                details={
                    "merchant_id": card.provider.get("id"),
                    "merchant_name": card.name,
                    "url": card.url,
                    "protocols": card.protocols,
                    "negotiable": card.provider.get("negotiable", False),
                },
            )
        return cards

    def request_proposals(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        target_merchant_id: Optional[str] = None,
        objective_id: str = "obj_default",
    ) -> List[MerchantProposal]:
        """Broadcasts a shopping request across A2A to merchant agents and gathers structured proposals."""
        filters = filters or {}
        audit_trail.log_event(
            event_type="AI_BUYER_SOLICITING_PROPOSALS",
            objective_id=objective_id,
            details={"query": query, "filters": filters, "target_merchant": target_merchant_id},
        )

        merchants = (
            [self.registry.get_merchant(target_merchant_id)]
            if target_merchant_id
            else self.registry.list_merchants()
        )

        proposals: List[MerchantProposal] = []
        for merchant in merchants:
            if not merchant:
                continue
            try:
                # Dispatched over A2A interface
                prop = merchant.create_proposal(query=query, filters=filters)
                if prop:
                    proposals.append(prop)
                    audit_trail.log_event(
                        event_type="MERCHANT_PROPOSAL_RECEIVED",
                        objective_id=objective_id,
                        details=prop.to_dict(),
                    )
            except Exception as e:
                logger.error("Failed to fetch proposal from merchant %s: %s", getattr(merchant, "merchant_id", "unknown"), e)

        return proposals

    def negotiate(
        self,
        merchant_id: str,
        proposal: MerchantProposal,
        competing_price: float,
        objective_id: str = "obj_default",
    ) -> Optional[MerchantProposal]:
        """Conducts an A2A 1-to-1 negotiation round with a merchant agent."""
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            logger.warning("Negotiation target %s not found in A2A registry", merchant_id)
            return None

        counter_ask = f"Competitor offers Rs. {competing_price:,.2f}. Can you improve your offer?"
        audit_trail.log_event(
            event_type="A2A_NEGOTIATION_COUNTER_SENT",
            objective_id=objective_id,
            details={
                "merchant_id": merchant_id,
                "current_price": proposal.proposed_price,
                "competing_price": competing_price,
                "counter_ask": counter_ask,
            },
        )

        # Dispatched over A2A interface
        counter_proposal = merchant.negotiate(proposal, competing_price=competing_price)

        if counter_proposal and counter_proposal.proposed_price < proposal.proposed_price:
            savings = proposal.proposed_price - counter_proposal.proposed_price
            audit_trail.log_event(
                event_type="BUYER_NEGOTIATION_ACCEPTED",
                objective_id=objective_id,
                details={
                    "merchant_id": merchant_id,
                    "initial_price": proposal.proposed_price,
                    "agreed_price": counter_proposal.proposed_price,
                    "savings": savings,
                    "message": counter_proposal.commercial_pitch,
                },
            )
            return counter_proposal

        audit_trail.log_event(
            event_type="A2A_NEGOTIATION_DECLINED",
            objective_id=objective_id,
            details={
                "merchant_id": merchant_id,
                "minimum_floor": proposal.minimum_price_floor,
                "competing_price": competing_price,
            },
        )
        return None

    def create_checkout(
        self,
        merchant_id: str,
        item_id: str,
        quantity: int = 1,
        agreed_price: Optional[float] = None,
        objective_id: str = "obj_default",
    ) -> Tuple[CheckoutSession, AuthoritativeCheckoutToken]:
        """Requests an authoritative ACP checkout session from the merchant over A2A."""
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            raise ValueError(f"A2A: Merchant {merchant_id} not registered")

        # Dispatched over A2A interface
        session = merchant.create_checkout(item_id=item_id, quantity=quantity, agreed_price=agreed_price)
        auth_token = merchant.sign_authoritative_checkout(session.id)

        audit_trail.log_event(
            event_type="checkout.created",
            objective_id=objective_id,
            details={
                "merchant_id": merchant_id,
                "session_id": session.id,
                "total_amount": session.total_amount,
                "currency": session.currency,
                "checkout_hash": auth_token.checkout_hash,
            },
        )
        return session, auth_token

    def complete_checkout(
        self,
        merchant_id: str,
        session_id: str,
        payment_id: str,
        objective_id: str = "obj_default",
    ) -> CheckoutSession:
        """Notifies the merchant agent that payment has succeeded, finalizing ACP checkout."""
        merchant = self.registry.get_merchant(merchant_id)
        if not merchant:
            raise ValueError(f"A2A: Merchant {merchant_id} not registered")

        session = merchant.complete_checkout(session_id, payment_id)
        audit_trail.log_event(
            event_type="checkout.completed",
            objective_id=objective_id,
            details={
                "merchant_id": merchant_id,
                "session_id": session_id,
                "payment_id": payment_id,
            },
        )
        return session


# Global singleton client
a2a_client = A2AClient()

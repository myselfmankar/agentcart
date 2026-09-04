"""AI Shopping Buyer Agent with Multi-Merchant Proposal Reasoning and Negotiation.

The Buyer Agent represents the user in commercial transactions:
1. Discovers merchant agents via A2A Agent Cards.
2. Broadcasts user criteria to all registered merchant agents via A2A.
3. Collects structured commercial proposals.
4. Evaluates trade-offs (price, delivery speed, stock reliability).
5. Conducts 1-to-1 strategic counter-negotiation with negotiable merchants over A2A.
6. Produces human-readable, transparent decision reasoning.
"""

from typing import Any

from app.modules.a2a.client import a2a_client
from app.modules.acp.models import MerchantProposal
from app.modules.audit.trail import audit_trail


class BuyerDecision:
    """Outcome of AI Buyer evaluation and negotiation."""

    def __init__(
        self,
        winner_merchant: Any | None,
        winning_proposal: MerchantProposal | None,
        all_proposals: list[MerchantProposal],
        reasoning: str,
        negotiation_rounds: list[dict[str, Any]],
    ):
        self.winner_merchant = winner_merchant
        self.winning_proposal = winning_proposal
        self.all_proposals = all_proposals
        self.reasoning = reasoning
        self.negotiation_rounds = negotiation_rounds

    @property
    def is_successful(self) -> bool:
        return self.winning_proposal is not None and self.winner_merchant is not None


class AIBuyerAgent:
    """Autonomous shopping agent reasoning across multi-merchant proposals."""

    def evaluate_and_negotiate(
        self,
        user_intent: dict[str, Any],
        objective_id: str = "obj_default",
    ) -> BuyerDecision:
        """Discovers merchants, solicits proposals over A2A, reasons over tradeoffs, negotiates, and selects best offer."""
        # 1. Discover Merchants via A2A Agent Cards
        a2a_client.discover_merchants(objective_id=objective_id)

        query = user_intent.get("query", "")
        brand = user_intent.get("brand")
        category = user_intent.get("category", "footwear")
        size = user_intent.get("size")
        color = user_intent.get("color")
        max_budget = float(user_intent.get("max_price", float("inf")))
        required_qty = int(user_intent.get("quantity", 1))
        max_delivery_days = user_intent.get("max_delivery_days")
        if max_delivery_days is not None:
            try:
                max_delivery_days = int(max_delivery_days)
            except (ValueError, TypeError):
                max_delivery_days = None

        filters = {
            "size": size,
            "color": color,
            "brand": brand,
            "category": category,
            "max_delivery_days": max_delivery_days,
        }

        # 2. Solicit proposals over A2A
        proposals: list[MerchantProposal] = a2a_client.request_proposals(
            query=query,
            filters=filters,
            objective_id=objective_id,
        )

        if not proposals:
            return BuyerDecision(
                winner_merchant=None,
                winning_proposal=None,
                all_proposals=[],
                reasoning="No merchant had items matching the requested criteria.",
                negotiation_rounds=[],
            )

        # 3. Evaluate each merchant proposal and log structured audit event
        qualified_proposals: list[MerchantProposal] = []

        for p in proposals:
            reasons = []
            if not (p.is_in_stock and p.stock >= required_qty):
                reasons.append("OUT_OF_STOCK")
            if p.proposed_price > max_budget:
                reasons.append(f"PRICE_EXCEEDED (proposed Rs. {p.proposed_price:,.0f} > budget Rs. {max_budget:,.0f})")

            fastest_deliv = min(p.standard_delivery_days, p.express_delivery_days)
            if max_delivery_days is not None and fastest_deliv > max_delivery_days:
                reasons.append(f"DELIVERY_TOO_SLOW (fastest {fastest_deliv} days > requested {max_delivery_days} days)")

            is_qualified = len(reasons) == 0
            rejection_reason = "; ".join(reasons) if not is_qualified else None

            audit_trail.log_event(
                event_type="MERCHANT_PROPOSAL_EVALUATED",
                objective_id=objective_id,
                details={
                    "merchant_id": p.merchant_id,
                    "merchant_name": p.merchant_name,
                    "base_price": p.base_price,
                    "discount_amount": p.discount_amount,
                    "final_price": p.proposed_price,
                    "stock": p.stock,
                    "delivery_days": fastest_deliv,
                    "status": "QUALIFIED" if is_qualified else "REJECTED",
                    "rejection_reason": rejection_reason,
                },
            )

            if is_qualified:
                qualified_proposals.append(p)

        if not qualified_proposals:
            reasons = []
            for p in proposals:
                fastest_deliv = min(p.standard_delivery_days, p.express_delivery_days)
                if not p.is_in_stock:
                    reasons.append(f"{p.merchant_name}: Out of stock (0 units)")
                elif p.proposed_price > max_budget:
                    reasons.append(f"{p.merchant_name}: Price Rs. {p.proposed_price:,.2f} exceeds user budget Rs. {max_budget:,.2f}")
                elif max_delivery_days is not None and fastest_deliv > max_delivery_days:
                    reasons.append(f"{p.merchant_name}: Delivery {fastest_deliv} days exceeds deadline of {max_delivery_days} days")

            reasoning_summary = "No qualifying proposals found. " + "; ".join(reasons)
            return BuyerDecision(
                winner_merchant=None,
                winning_proposal=None,
                all_proposals=proposals,
                reasoning=reasoning_summary,
                negotiation_rounds=[],
            )

        # 4. Strategic Counter-Negotiation over A2A
        negotiation_rounds = []
        best_firm_candidate = min(qualified_proposals, key=lambda p: p.proposed_price)

        for p in list(qualified_proposals):
            if p.is_negotiable and p.minimum_price_floor:
                competing_price = best_firm_candidate.proposed_price
                if p.merchant_id == best_firm_candidate.merchant_id:
                    other_proposals = [x for x in qualified_proposals if x.merchant_id != p.merchant_id]
                    if other_proposals:
                        competing_price = min(x.proposed_price for x in other_proposals)

                counter_proposal = a2a_client.negotiate(
                    merchant_id=p.merchant_id,
                    proposal=p,
                    competing_price=competing_price,
                    objective_id=objective_id,
                )

                if counter_proposal and counter_proposal.proposed_price < p.proposed_price:
                    savings = p.proposed_price - counter_proposal.proposed_price
                    negotiation_rounds.append({
                        "merchant_id": p.merchant_id,
                        "merchant_name": p.merchant_name,
                        "initial_price": p.proposed_price,
                        "counter_ask": f"Competitor offers Rs. {competing_price:,.2f}. Can you improve your offer?",
                        "agreed_price": counter_proposal.proposed_price,
                        "savings": savings,
                        "message": counter_proposal.commercial_pitch,
                    })
                    idx = proposals.index(p)
                    proposals[idx] = counter_proposal
                    qualified_proposals[qualified_proposals.index(p)] = counter_proposal

        # 5. Final Selection & Tradeoff Reasoning
        def score_proposal(prop: MerchantProposal) -> float:
            score = prop.proposed_price
            # Advantage for faster delivery
            deliv_days = min(prop.standard_delivery_days, prop.express_delivery_days)
            if deliv_days <= 1:
                score -= 100.0
            elif deliv_days <= 2:
                score -= 50.0
            return score

        winning_proposal = min(qualified_proposals, key=score_proposal)
        winner_merchant = a2a_client.registry.get_merchant(winning_proposal.merchant_id)

        # Build Explainable Reasoning
        reasoning_lines = ["Autonomous AI Buyer Evaluation & Decision:"]
        for p in proposals:
            deliv_days = min(p.standard_delivery_days, p.express_delivery_days)
            if not p.is_in_stock:
                reasoning_lines.append(f"  - {p.merchant_name}: DISQUALIFIED -- Currently out of stock.")
            elif p.proposed_price > max_budget:
                reasoning_lines.append(f"  - {p.merchant_name}: DISQUALIFIED -- Price Rs. {p.proposed_price:,.2f} exceeds user budget.")
            elif max_delivery_days is not None and deliv_days > max_delivery_days:
                reasoning_lines.append(f"  - {p.merchant_name}: DISQUALIFIED -- Delivery time ({deliv_days} days) exceeds requested {max_delivery_days} days.")
            elif p.merchant_id == winning_proposal.merchant_id:
                reasoning_lines.append(
                    f"  - {p.merchant_name}: WINNER -- Final price Rs. {p.proposed_price:,.2f} "
                    f"with {p.express_delivery_days}-day express delivery (Rs. {p.express_delivery_fee:,.0f} fee). "
                    f"Best overall value and delivery speed."
                )
            else:
                reasoning_lines.append(
                    f"  - {p.merchant_name}: CONSIDERED -- Proposed Rs. {p.proposed_price:,.2f} ({p.standard_delivery_days}-day delivery), "
                    f"beaten by {winning_proposal.merchant_name} on price/speed."
                )

        reasoning_text = "\n".join(reasoning_lines)

        audit_trail.log_event(
            event_type="AI_BUYER_DECISION_FINALIZED",
            objective_id=objective_id,
            details={
                "winner_merchant": winning_proposal.merchant_name,
                "winner_price": winning_proposal.proposed_price,
                "reasoning": reasoning_text,
            },
        )

        return BuyerDecision(
            winner_merchant=winner_merchant,
            winning_proposal=winning_proposal,
            all_proposals=proposals,
            reasoning=reasoning_text,
            negotiation_rounds=negotiation_rounds,
        )


ai_buyer_agent = AIBuyerAgent()

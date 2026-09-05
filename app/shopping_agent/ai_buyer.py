"""AI Shopping Buyer Agent with Multi-Merchant Proposal Reasoning and Negotiation.

The Buyer Agent represents the user in commercial transactions:
1. Discovers merchant agents via A2A Agent Cards.
2. Broadcasts user criteria to all registered merchant agents via A2A.
3. Collects structured commercial proposals.
4. Evaluates trade-offs (price, delivery speed, stock reliability).
5. Conducts 1-to-1 strategic counter-negotiation with negotiable merchants over A2A.
6. Produces human-readable, transparent decision reasoning.
"""

import json
import logging
import os
from typing import Any

from app.modules.a2a.client import a2a_client
from app.modules.acp.models import MerchantProposal
from app.modules.audit.trail import audit_trail

logger = logging.getLogger(__name__)


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

        # In automated test suites, preserve deterministic reasoning to prevent burning API rate limits
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            llm_eval = self._evaluate_tradeoffs_with_simple_llm(
                user_intent=user_intent,
                proposals=proposals,
            )
            if llm_eval and llm_eval.get("winner_merchant_id"):
                cand = next((p for p in qualified_proposals if p.merchant_id == llm_eval["winner_merchant_id"]), None)
                if cand:
                    winning_proposal = cand
                    winner_merchant = a2a_client.registry.get_merchant(winning_proposal.merchant_id)
                if llm_eval.get("reasoning"):
                    reasoning_text = llm_eval["reasoning"]

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

    def _evaluate_tradeoffs_with_simple_llm(
        self,
        user_intent: dict[str, Any],
        proposals: list[MerchantProposal],
    ) -> dict[str, Any] | None:
        """Single, compact prompt to evaluate marketplace proposals with minimal token usage."""
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        # Build ultra-compact prompt (<120 tokens)
        query = user_intent.get("query", "")
        max_budget = user_intent.get("max_price", 6000.0)
        max_deliv = user_intent.get("max_delivery_days", 5)

        store_lines = []
        for p in proposals:
            stock_info = f"Stock: {p.stock}" if p.is_in_stock else "OUT OF STOCK"
            deliv = min(p.standard_delivery_days, p.express_delivery_days)
            neg = f"Floor: Rs. {p.minimum_price_floor:,.0f}" if p.is_negotiable and p.minimum_price_floor else "Firm"
            store_lines.append(
                f"- {p.merchant_name} (ID: {p.merchant_id}): {p.item.name} | Price: Rs. {p.proposed_price:,.0f} | {stock_info} | Deliv: {deliv}d | Policy: {neg}"
            )

        prompt = (
            f"Customer Request: \"{query}\" (Budget: Rs. {max_budget:,.0f}, Max Delivery: {max_deliv} days)\n\n"
            "Store Offers:\n"
            + "\n".join(store_lines) + "\n\n"
            "Pick the single winning store considering stock availability, price, and delivery speed.\n"
            "Respond in JSON with this exact structure:\n"
            "{\"winner_merchant_id\": \"<merchant_id>\", \"reasoning\": \"<2 concise sentences explaining the winning trade-off>\"}"
        )

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            model_name = os.getenv("AGENT_MODEL", "gemini-3.6-flash")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            if response and response.text:
                return json.loads(response.text)
        except Exception as e:
            logger.warning("Simple marketplace LLM evaluation skipped/fallback: %s", e)
            return None
        return None


ai_buyer_agent = AIBuyerAgent()

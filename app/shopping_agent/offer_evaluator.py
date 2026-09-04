"""Multi-Merchant Offer Evaluator and Autonomous Decision Engine.

Queries all discovered merchants through the A2A adapter, compares competing offers,
disqualifies invalid offers with explicit explanations,
and ranks qualifying candidates autonomously.
"""

from typing import Any, Dict, List, Optional, Tuple
from app.modules.acp.models import Item
from app.modules.a2a.discovery import merchant_registry, a2a_merchant_adapter
from app.modules.audit.trail import audit_trail


class OfferEvaluationResult:
    """Evaluation result for a single merchant offer."""

    def __init__(
        self,
        merchant_id: str,
        merchant_name: str,
        item: Item,
        is_qualified: bool,
        rejection_reason: Optional[str] = None,
    ):
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.item = item
        self.is_qualified = is_qualified
        self.rejection_reason = rejection_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "merchant_id": self.merchant_id,
            "merchant_name": self.merchant_name,
            "item_id": self.item.id,
            "item_name": self.item.name,
            "price": self.item.price,
            "stock": self.item.stock,
            "is_qualified": self.is_qualified,
            "rejection_reason": self.rejection_reason,
        }


class MultiMerchantOfferEvaluator:
    """Evaluates and compares offers across multiple merchants."""

    def evaluate_all_merchants(
        self,
        user_intent: Dict[str, Any],
        objective_id: str = "obj_default",
    ) -> Tuple[Optional[Tuple[Any, Item]], List[OfferEvaluationResult]]:
        """Queries all merchants in registry, evaluates offers, and selects best qualifying candidate.
        
        Returns:
            (winner_tuple (merchant_agent, item), list_of_all_evaluations)
        """
        merchants = merchant_registry.list_merchants()
        query = user_intent.get("query", "")
        filters = {}
        if "size" in user_intent:
            filters["size"] = user_intent["size"]
        if "color" in user_intent:
            filters["color"] = user_intent["color"]

        max_budget = float(user_intent.get("max_price", float("inf")))
        required_qty = int(user_intent.get("quantity", 1))

        evaluations: List[OfferEvaluationResult] = []
        qualifying_candidates: List[Tuple[Any, Item]] = []

        audit_trail.log_event(
            event_type="MULTI_MERCHANT_QUERY_STARTED",
            objective_id=objective_id,
            details={"merchant_count": len(merchants), "query": query, "filters": filters, "budget": max_budget},
        )

        for merchant in merchants:
            matching_items = a2a_merchant_adapter.search_catalog(
                merchant_id=merchant.merchant_id,
                query=query,
                filters=filters,
                objective_id=objective_id,
            )
            if not matching_items:
                evaluations.append(
                    OfferEvaluationResult(
                        merchant_id=merchant.merchant_id,
                        merchant_name=merchant.merchant_name,
                        item=Item(id="none", name="N/A", brand="N/A", price=0.0, stock=0),
                        is_qualified=False,
                        rejection_reason="NO_MATCHING_ITEM_FOUND",
                    )
                )
                continue

            for item in matching_items:
                audit_trail.log_event(
                    event_type="offer.received",
                    objective_id=objective_id,
                    details={"merchant_id": merchant.merchant_id, "item_id": item.id, "price": item.price, "stock": item.stock},
                )
                reasons = []

                # Price ceiling check
                if item.price > max_budget:
                    reasons.append(
                        f"PRICE_EXCEEDED: ₹{item.price:,.2f} exceeds max budget ₹{max_budget:,.2f}"
                    )

                # Stock check
                if item.stock < required_qty:
                    reasons.append(
                        f"OUT_OF_STOCK: Current stock {item.stock} < requested {required_qty}"
                    )

                is_qualified = len(reasons) == 0
                eval_res = OfferEvaluationResult(
                    merchant_id=merchant.merchant_id,
                    merchant_name=merchant.merchant_name,
                    item=item,
                    is_qualified=is_qualified,
                    rejection_reason="; ".join(reasons) if not is_qualified else None,
                )
                evaluations.append(eval_res)

                if is_qualified:
                    qualifying_candidates.append((merchant, item))
                else:
                    audit_trail.log_event(
                        event_type="offer.rejected",
                        objective_id=objective_id,
                        details={"merchant_id": merchant.merchant_id, "item_id": item.id, "reason": eval_res.rejection_reason},
                    )

        # Log comparison matrix
        audit_trail.log_event(
            event_type="OFFERS_EVALUATION_COMPLETED",
            objective_id=objective_id,
            details={
                "total_offers_evaluated": len(evaluations),
                "qualifying_count": len(qualifying_candidates),
                "offers": [e.to_dict() for e in evaluations],
            },
        )

        if not qualifying_candidates:
            audit_trail.log_event(
                event_type="NO_QUALIFYING_OFFERS",
                objective_id=objective_id,
                details={"reason": "All discovered merchant offers were disqualified."},
                level="WARNING",
            )
            return None, evaluations

        # Autonomous Selection Rule: Best (lowest) price among qualifying offers
        qualifying_candidates.sort(key=lambda pair: pair[1].price)
        winner_merchant, winner_item = qualifying_candidates[0]

        audit_trail.log_event(
            event_type="offer.selected",
            objective_id=objective_id,
            details={
                "winner_merchant": winner_merchant.merchant_name,
                "winner_item": winner_item.name,
                "price": winner_item.price,
                "stock": winner_item.stock,
                "competing_offers_considered": len(evaluations),
            },
        )
        audit_trail.log_event(
            event_type="OFFER_SELECTED",
            objective_id=objective_id,
            details={
                "winner_merchant": winner_merchant.merchant_name,
                "winner_item": winner_item.name,
                "price": winner_item.price,
                "stock": winner_item.stock,
                "competing_offers_considered": len(evaluations),
            },
        )

        return (winner_merchant, winner_item), evaluations


offer_evaluator = MultiMerchantOfferEvaluator()
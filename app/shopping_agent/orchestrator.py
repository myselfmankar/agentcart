"""Autonomous Shopping Agent Orchestrator.

Implements the complete AI Buyer Agent pipeline with deterministic 16-step safety gates:
1. User Product Constraints
2. Product Variant (Size, Color, Brand)
3. Inventory Availability
4. Merchant Offer Validity
5. Final ACP Checkout Total
6. User Maximum Price (Budget)
7. Delivery Constraints
8. Autonomous Purchase Consent
9. Buyer Per-Transaction Limit
10. Buyer Available Balance
11. Open AP2 Checkout Mandate
12. Open AP2 Payment Mandate
13. Closed Checkout Mandate & Verification
14. Closed Payment Mandate & Verification
15. Payment Credential / Allowance
16. Razorpay Test Mode Order Creation & Payment Execution
17. Buyer Ledger Debit Reconciled upon verified payment
"""

import uuid
from typing import Any, Dict, List, Optional
from app.modules.audit.trail import audit_trail
from app.modules.ap2.mandates import (
    authorize_user_mandates,
    create_closed_checkout_mandate,
    create_closed_payment_mandate,
    create_checkout_receipt,
    create_payment_receipt,
)
from app.modules.ap2.verifier import deterministic_verifier
from app.modules.policy.engine import policy_engine
from app.modules.buyer.ledger import buyer_ledger
from app.modules.a2a.client import a2a_client
from app.modules.razorpay.client import razorpay_client
from app.shopping_agent.ai_buyer import ai_buyer_agent
from app.modules.watch.objective import (
    ObjectiveStatus,
    ObjectiveStore,
    ShoppingObjective,
    objective_store,
)
from app.modules.watch.event_bus import event_bus


class ShoppingAgentOrchestrator:
    """Coordinates autonomous shopping across merchants, policy, AP2, ACP, Buyer Ledger, and Razorpay."""

    def __init__(self, store: Optional[ObjectiveStore] = None):
        self.objective_store = store or objective_store
        event_bus.subscribe(self.handle_merchant_event)

    def execute_intent(
        self,
        intent: Dict[str, Any],
        merchant = None,
        simulate_payment_failure: bool = False,
        enable_watching: bool = False,
        objective_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes a bounded autonomous shopping intent."""
        objective_id = objective_id or f"obj_{uuid.uuid4().hex[:10]}"
        objective = ShoppingObjective(objective_id=objective_id, user_intent=intent)
        objective.transition_to(ObjectiveStatus.SEARCHING, "Initiating merchant discovery")
        self.objective_store.save_objective(objective)

        # 1. Log Intent
        audit_trail.log_event(event_type="INTENT_RECEIVED", objective_id=objective_id, details=intent)

        # 2. Authorize Open Mandates (bounds max spending)
        open_checkout, open_payment = authorize_user_mandates(intent)

        # 3. Discover, Solicit Proposals & AI Reasoning over A2A
        ai_reasoning = ""
        negotiation_rounds = []
        all_proposals = []
        agreed_price = None

        if merchant is None:
            a2a_client.discover_merchants(objective_id=objective_id)
            decision = ai_buyer_agent.evaluate_and_negotiate(user_intent=intent, objective_id=objective_id)

            if not decision.is_successful:
                if enable_watching:
                    objective.transition_to(
                        ObjectiveStatus.WATCHING,
                        "No qualifying merchant proposals. Placed in WATCHING state."
                    )
                    self.objective_store.save_objective(objective)
                    return {
                        "success": False,
                        "status": "WATCHING",
                        "objective_id": objective_id,
                        "proposals": [p.to_dict() for p in decision.all_proposals],
                        "evaluations": [p.to_dict() for p in decision.all_proposals],
                        "reasoning": decision.reasoning,
                        "open_checkout_mandate_id": open_checkout["mandate_id"],
                        "open_payment_mandate_id": open_payment["mandate_id"],
                        "message": "No qualifying offer currently exists. Placed shopping objective in WATCHING state.",
                    }
                else:
                    objective.transition_to(ObjectiveStatus.FAILED, "No qualifying proposals found")
                    self.objective_store.save_objective(objective)
                    return {
                        "success": False,
                        "status": "NO_OFFER_FOUND",
                        "objective_id": objective_id,
                        "proposals": [p.to_dict() for p in decision.all_proposals],
                        "evaluations": [p.to_dict() for p in decision.all_proposals],
                        "reasoning": decision.reasoning,
                        "message": "No merchant offers satisfied the constraints.",
                    }

            selected_merchant = decision.winner_merchant
            winning_proposal = decision.winning_proposal
            candidate_item = winning_proposal.item
            agreed_price = winning_proposal.proposed_price
            ai_reasoning = decision.reasoning
            negotiation_rounds = decision.negotiation_rounds
            all_proposals = [p.to_dict() for p in decision.all_proposals]
        else:
            # Single merchant targeted via A2A
            target_merchant_id = getattr(merchant, "merchant_id", str(merchant))
            selected_merchant = a2a_client.registry.get_merchant(target_merchant_id) or merchant
            proposals = a2a_client.request_proposals(
                query=intent.get("query", ""),
                filters={"size": intent.get("size"), "color": intent.get("color")},
                target_merchant_id=target_merchant_id,
                objective_id=objective_id,
            )

            if not proposals:
                merchant_name = getattr(selected_merchant, "merchant_name", target_merchant_id)
                if enable_watching:
                    objective.transition_to(ObjectiveStatus.WATCHING, "Item unavailable at merchant")
                    self.objective_store.save_objective(objective)
                    return {
                        "success": False,
                        "status": "WATCHING",
                        "objective_id": objective_id,
                        "message": f"Product unavailable at {merchant_name}. Entering WATCHING.",
                    }
                else:
                    objective.transition_to(ObjectiveStatus.FAILED, "No matching items at merchant")
                    self.objective_store.save_objective(objective)
                    return {
                        "success": False,
                        "status": "NO_OFFER_FOUND",
                        "objective_id": objective_id,
                        "message": f"No matching products found at {merchant_name}",
                    }

            winning_proposal = proposals[0]
            candidate_item = winning_proposal.item
            agreed_price = float(intent.get("agreed_price")) if intent.get("agreed_price") is not None else winning_proposal.proposed_price
            all_proposals = [p.to_dict() for p in proposals]

        return self._complete_purchase(
            objective=objective,
            intent=intent,
            open_checkout=open_checkout,
            open_payment=open_payment,
            selected_merchant=selected_merchant,
            candidate_item=candidate_item,
            agreed_price=agreed_price,
            ai_reasoning=ai_reasoning,
            negotiation_rounds=negotiation_rounds,
            all_proposals=all_proposals,
            simulate_payment_failure=simulate_payment_failure,
            enable_watching=enable_watching,
        )

    def _complete_purchase(
        self,
        objective: ShoppingObjective,
        intent: Dict[str, Any],
        open_checkout: Dict[str, Any],
        open_payment: Dict[str, Any],
        selected_merchant: Any,
        candidate_item: Any,
        agreed_price: Optional[float] = None,
        ai_reasoning: str = "",
        negotiation_rounds: Optional[List[Dict[str, Any]]] = None,
        all_proposals: Optional[List[Dict[str, Any]]] = None,
        simulate_payment_failure: bool = False,
        enable_watching: bool = False,
    ) -> Dict[str, Any]:
        """Executes policy checks, buyer limit checks, ACP checkout, and payment rail."""
        objective_id = objective.objective_id
        merchant_id = getattr(selected_merchant, "merchant_id", "merchant_unknown")
        merchant_name = getattr(selected_merchant, "merchant_name", merchant_id)

        final_check_item = candidate_item.model_copy()
        if agreed_price is not None:
            final_check_item.price = agreed_price

        # 1-8. Deterministic Policy Gate (Product, Variant, Stock, Validity, User Price, Delivery, Auto Purchase)
        policy_decision = policy_engine.evaluate_offer(
            item=final_check_item,
            user_intent=intent,
            objective_id=objective_id
        )
        if not policy_decision.allowed:
            objective.transition_to(ObjectiveStatus.FAILED, f"Policy rejected: {policy_decision.violations}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "POLICY_REJECTED",
                "objective_id": objective_id,
                "violations": policy_decision.violations,
                "details": policy_decision.details,
                "money_moved_inr": 0.0,
                "message": f"Autonomous purchase blocked by deterministic policy: {policy_decision.violations}",
            }

        # ACP Authoritative Checkout Session & Signing via A2A
        try:
            checkout_session, auth_token = a2a_client.create_checkout(
                merchant_id=merchant_id,
                item_id=candidate_item.id,
                quantity=int(intent.get("quantity", 1)),
                agreed_price=agreed_price,
                objective_id=objective_id,
            )
        except Exception as e:
            objective.transition_to(ObjectiveStatus.FAILED, f"ACP checkout creation failed: {e}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "CHECKOUT_CREATION_FAILED",
                "objective_id": objective_id,
                "error": str(e),
                "money_moved_inr": 0.0,
            }

        amount = checkout_session.total_amount

        # 9-10. Buyer Spending Authority & Balance Checks
        buyer_limits = buyer_ledger.check_buyer_limits(
            amount=amount,
            currency=checkout_session.currency,
            objective_id=objective_id,
            merchant_id=merchant_id,
            checkout_id=checkout_session.id,
        )
        if not buyer_limits.allowed:
            if buyer_limits.reason == "INSUFFICIENT_BUYER_BALANCE" and enable_watching:
                objective.transition_to(
                    ObjectiveStatus.AWAITING_FUNDS,
                    f"Insufficient buyer balance (available: Rs. {buyer_limits.available_balance:,.0f}, required: Rs. {amount:,.0f}). Placed in AWAITING_FUNDS state."
                )
                self.objective_store.save_objective(objective)
                return {
                    "success": False,
                    "status": "AWAITING_FUNDS",
                    "reason": "INSUFFICIENT_BUYER_BALANCE",
                    "required_amount": amount,
                    "available_balance": buyer_limits.available_balance,
                    "shortfall": buyer_limits.shortfall,
                    "currency": checkout_session.currency,
                    "razorpay_called": False,
                    "objective_id": objective_id,
                    "message": (
                        f"I found a qualifying offer at Rs. {amount:,.0f}, but your AI buyer spending balance is Rs. {buyer_limits.available_balance:,.0f}. "
                        f"The purchase is paused in AWAITING_FUNDS waiting for a RazorpayX balance top-up. You are short by Rs. {buyer_limits.shortfall:,.0f}."
                    ),
                }

            objective.transition_to(ObjectiveStatus.FAILED, f"Buyer limit rejected: {buyer_limits.reason}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "rejected",
                "reason": buyer_limits.reason,
                "violations": buyer_limits.violations,
                "required_amount": amount,
                "available_balance": buyer_limits.available_balance,
                "per_transaction_limit": buyer_limits.per_transaction_limit,
                "shortfall": buyer_limits.shortfall,
                "currency": checkout_session.currency,
                "razorpay_called": False,
                "objective_id": objective_id,
                "money_moved_inr": 0.0,
                "message": (
                    f"I found a qualifying offer at Rs. {amount:,.0f}, but your AI buyer spending balance is Rs. {buyer_limits.available_balance:,.0f}. "
                    f"The purchase was not authorized and no Razorpay payment was attempted. You are short by Rs. {buyer_limits.shortfall:,.0f}."
                    if buyer_limits.reason == "INSUFFICIENT_BUYER_BALANCE"
                    else f"Purchase rejected by buyer limit: {buyer_limits.violations}"
                ),
            }

        # 11-13. AP2 Closed Checkout Mandate & Verification
        closed_checkout = create_closed_checkout_mandate(
            open_checkout_mandate_id=open_checkout["mandate_id"],
            checkout_jwt=auth_token.checkout_jwt,
            checkout_hash=auth_token.checkout_hash,
            merchant_id=merchant_id,
        )
        chk_verification = deterministic_verifier.verify_closed_checkout_mandate(
            closed_checkout_token=closed_checkout["token"],
            open_checkout_claims=open_checkout["payload"],
            authoritative_checkout_jwt=auth_token.checkout_jwt,
        )
        if not chk_verification.allowed:
            objective.transition_to(ObjectiveStatus.FAILED, f"Closed checkout verification failed: {chk_verification.message}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "VERIFICATION_FAILED",
                "code": chk_verification.code,
                "objective_id": objective_id,
                "message": chk_verification.message,
                "money_moved_inr": 0.0,
            }

        checkout_receipt = create_checkout_receipt(
            mandate_id=closed_checkout["mandate_id"],
            checkout_hash=auth_token.checkout_hash,
            merchant_id=merchant_id,
        )

        # 14-15. AP2 Closed Payment Mandate & Verification
        payment_policy = policy_engine.evaluate_payment(
            amount=amount,
            authorized_max_amount=float(open_payment["payload"]["max_amount"]),
            currency=checkout_session.currency,
            payment_reference=f"payref_{objective_id}",
            objective_id=objective_id,
        )
        if not payment_policy.allowed:
            objective.transition_to(ObjectiveStatus.FAILED, f"Payment policy rejected: {payment_policy.violations}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "PAYMENT_POLICY_REJECTED",
                "objective_id": objective_id,
                "violations": payment_policy.violations,
                "money_moved_inr": 0.0,
            }

        closed_payment = create_closed_payment_mandate(
            open_payment_mandate_id=open_payment["mandate_id"],
            checkout_hash=auth_token.checkout_hash,
            amount=amount,
            payee=merchant_name,
            currency=checkout_session.currency,
            payment_reference=f"payref_{objective_id}",
        )
        pay_verification = deterministic_verifier.verify_payment_authorization(
            closed_payment_token=closed_payment["token"],
            open_payment_claims=open_payment["payload"],
            expected_amount=amount,
            expected_payee=merchant_name,
            expected_checkout_hash=auth_token.checkout_hash,
        )
        if not pay_verification.allowed:
            objective.transition_to(ObjectiveStatus.FAILED, f"Payment authorization failed: {pay_verification.message}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "PAYMENT_AUTHORIZATION_FAILED",
                "code": pay_verification.code,
                "objective_id": objective_id,
                "message": pay_verification.message,
                "money_moved_inr": 0.0,
            }

        # 16. Razorpay Rail Execution (Test Mode)
        order = razorpay_client.create_order(
            amount_inr=amount,
            currency=checkout_session.currency,
            receipt=f"rcpt_{objective_id}",
            notes={"objective_id": objective_id, "merchant": merchant_name},
            objective_id=objective_id,
        )
        payment = razorpay_client.execute_test_payment(
            order_id=order["id"],
            amount_inr=amount,
            method="card",
            simulate_failure=simulate_payment_failure,
            objective_id=objective_id,
        )

        if payment.get("status") != "captured":
            objective.transition_to(ObjectiveStatus.FAILED, f"Payment declined: {payment.get('error_description')}")
            self.objective_store.save_objective(objective)
            return {
                "success": False,
                "status": "PAYMENT_FAILED",
                "objective_id": objective_id,
                "order_id": order["id"],
                "error": payment.get("error_description", "Payment capture failed"),
                "money_moved_inr": 0.0,
            }

        # 16b. RazorpayX Direct Payout to Merchant Fund Account
        payout = razorpay_client.execute_payout(
            merchant_id=merchant_id,
            amount_inr=amount,
            currency=checkout_session.currency,
            reference_id=f"pout_{objective_id}",
            narration=f"Order {order['id']}",
            objective_id=objective_id,
        )

        # 17. Reconcile Buyer Balance Ledger upon Verified Payment
        buyer_ledger.record_debit(
            transaction_id=f"tx_{objective_id}",
            amount=amount,
            currency=checkout_session.currency,
            merchant_id=merchant_id,
            razorpay_order_id=order["id"],
            razorpay_payment_id=payment["id"],
            status="completed",
            objective_id=objective_id,
        )

        # 18. Finalize Checkout via A2A & Completion
        a2a_client.complete_checkout(
            merchant_id=merchant_id,
            session_id=checkout_session.id,
            payment_id=payment["id"],
            objective_id=objective_id,
        )
        payment_receipt = create_payment_receipt(
            closed_payment_mandate_id=closed_payment["mandate_id"],
            checkout_hash=auth_token.checkout_hash,
            order_id=order["id"],
            payment_id=payment["id"],
            amount=amount,
            currency=checkout_session.currency,
            merchant_id=merchant_id,
        )

        result_payload = {
            "success": True,
            "status": "COMPLETED",
            "objective_id": objective_id,
            "merchant": merchant_name,
            "item_purchased": candidate_item.name,
            "amount_paid_inr": amount,
            "order_id": order["id"],
            "payment_id": payment["id"],
            "razorpayx_payout_id": payout.get("id") if payout else None,
            "razorpayx_payout_status": payout.get("status") if payout else None,
            "checkout_session_id": checkout_session.id,
            "checkout_hash": auth_token.checkout_hash,
            "closed_checkout_mandate_id": closed_checkout["mandate_id"],
            "closed_payment_mandate_id": closed_payment["mandate_id"],
            "checkout_receipt_id": checkout_receipt["receipt_id"],
            "payment_receipt_id": payment_receipt["receipt_id"],
            "ai_reasoning": ai_reasoning,
            "negotiation_rounds": negotiation_rounds or [],
            "proposals": all_proposals or [],
            "remaining_balance_inr": buyer_ledger.available_balance,
            "message": f"Successfully purchased {candidate_item.name} from {merchant_name} for Rs. {amount:,.2f}",
        }

        objective.transition_to(ObjectiveStatus.COMPLETED, "Purchase finalized and verified")
        objective.purchase_result = result_payload
        self.objective_store.save_objective(objective)

        audit_trail.log_event(
            event_type="PURCHASE_COMPLETED",
            objective_id=objective_id,
            details=result_payload,
        )
        return result_payload

    def handle_merchant_event(self, event: Dict[str, Any]) -> None:
        """Processes merchant inventory/pricing/balance events and re-evaluates WATCHING objectives."""
        event_type = event.get("event_type")
        if event_type not in ["INVENTORY_CHANGED", "PRICE_CHANGED", "BALANCE_CHANGED"]:
            return

        merchant_id = event.get("merchant_id", "system")
        audit_trail.log_event(
            event_type="SYSTEM_EVENT_RECEIVED",
            objective_id=event.get("objective_id", "system"),
            details=event,
        )

        # Re-evaluate WATCHING and AWAITING_FUNDS objectives (targeted or all)
        target_obj_id = event.get("objective_id")
        if target_obj_id and target_obj_id not in ["system", "unknown"]:
            target_obj = self.objective_store.get_objective(target_obj_id)
            watching_objs = [
                target_obj
            ] if target_obj and target_obj.status in [
                ObjectiveStatus.WATCHING,
                ObjectiveStatus.AWAITING_FUNDS,
                ObjectiveStatus.EVALUATING,
            ] else []
        else:
            if event_type == "BALANCE_CHANGED":
                # Balance changes prioritize AWAITING_FUNDS objectives first, then WATCHING
                watching_objs = (
                    self.objective_store.get_awaiting_funds_objectives()
                    + self.objective_store.get_watching_objectives()
                )
            else:
                watching_objs = self.objective_store.get_watching_objectives()

        for obj in watching_objs:
            obj.transition_to(
                ObjectiveStatus.EVALUATING,
                f"Re-evaluating objective after event {event_type} from {merchant_id}"
            )
            self.objective_store.save_objective(obj)

            # Autonomous re-evaluation with fresh discovery
            res = self.execute_intent(
                intent=obj.user_intent,
                enable_watching=False,
                objective_id=obj.objective_id,
            )
            if res.get("success"):
                obj.transition_to(ObjectiveStatus.COMPLETED, "Re-evaluation purchase succeeded")
                obj.purchase_result = res
                self.objective_store.save_objective(obj)
            else:
                new_status = (
                    ObjectiveStatus.AWAITING_FUNDS
                    if res.get("reason") == "INSUFFICIENT_BUYER_BALANCE"
                    else ObjectiveStatus.WATCHING
                )
                obj.transition_to(new_status, f"Re-evaluation unresolved: {res.get('message')}")
                self.objective_store.save_objective(obj)


# Global singleton orchestrator
shopping_orchestrator = ShoppingAgentOrchestrator()
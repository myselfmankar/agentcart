"""Tests for WATCHING state and Event-Driven Autonomous Re-evaluation."""

from app.merchants import merchant_b
from app.modules.audit.trail import audit_trail
from app.modules.watch.event_bus import event_bus
from app.modules.watch.objective import ObjectiveStatus, ObjectiveStore
from app.shopping_agent.orchestrator import shopping_orchestrator


def test_watching_state_and_event_re_evaluation():
    """Verify flow: No offer under budget -> enters WATCHING -> merchant restocks with discount -> auto-evaluates & completes purchase."""
    merchant_b.set_stock("adidas-runfalcon-3_blue_10", 0)

    try:
        intent = {
            "description": "Buy me Adidas blue sneakers, size 10, under Rs. 4,600",
            "query": "adidas",
            "max_price": 4600.0,
            "size": 10,
            "color": "blue",
            "quantity": 1,
            "auto_purchase": True,
        }

        # Step 1: Initial search should enter WATCHING state (UrbanKicks is 4899, FastFeet floor is 4650, ShoeKart is out of stock)
        init_res = shopping_orchestrator.execute_intent(intent, enable_watching=True)
        assert init_res["success"] is False
        assert init_res["status"] == "WATCHING"
        obj_id = init_res["objective_id"]

        # Verify objective is persisted as WATCHING under AP2 HNP Intent Mandate
        obj = shopping_orchestrator.objective_store.get_objective(obj_id)
        assert obj is not None
        assert obj.status == ObjectiveStatus.WATCHING
        assert obj.intent_mandate_id is not None
        assert obj.modality == "HUMAN_NOT_PRESENT"
        assert obj.open_payment_mandate_id is not None

        # Step 2: Merchant B restocks
        merchant_b.set_stock("adidas-runfalcon-3_blue_10", 4)

        # Publish merchant inventory event
        event_bus.publish(
            event_type="INVENTORY_CHANGED",
            merchant_id="merchant_b",
            item_id="adidas-runfalcon-3_blue_10",
            payload={"stock": 4, "price": 4549.0},
            objective_id=obj_id,
        )

        # Step 3: Verify the objective automatically re-evaluated and completed purchase
        updated_obj = shopping_orchestrator.objective_store.get_objective(obj_id)
        assert updated_obj.status == ObjectiveStatus.COMPLETED
        assert updated_obj.purchase_result is not None
        assert updated_obj.purchase_result["success"] is True
        assert updated_obj.purchase_result["amount_paid_inr"] <= 4600.0
        assert "ShoeKart" in updated_obj.purchase_result["merchant"]

        # Verify audit trail captured the state transitions
        events = audit_trail.get_events_for_objective(obj_id)
        types = [e["event_type"] for e in events]
        assert "OBJECTIVE_STATE_TRANSITION" in types
        assert "MERCHANT_EVENT_PUBLISHED" in types
        assert "PURCHASE_COMPLETED" in types

    finally:
        merchant_b.set_stock("adidas-runfalcon-3_blue_10", 0)


def test_objective_restart_persistence(tmp_path):
    """Verify that watching objectives are persisted to disk and survive agent restart."""
    test_file = tmp_path / "test_objectives.json"
    store1 = ObjectiveStore(file_path=test_file)

    intent = {"description": "Persistent watch test", "max_price": 4000.0}

    from app.modules.watch.objective import ShoppingObjective
    obj = ShoppingObjective(objective_id="obj_persist_123", user_intent=intent)
    obj.transition_to(ObjectiveStatus.WATCHING, "Waiting for price drop")
    store1.save_objective(obj)

    # Simulate restart by creating a new ObjectiveStore reading the same file
    store2 = ObjectiveStore(file_path=test_file)
    recovered = store2.get_objective("obj_persist_123")
    assert recovered is not None
    assert recovered.objective_id == "obj_persist_123"
    assert recovered.status == ObjectiveStatus.WATCHING
    assert recovered.watch_reason == "Waiting for price drop"
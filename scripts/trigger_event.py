"""Autonomous Commerce Event Trigger & Live Watch Simulator."""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.merchants import merchant_a, merchant_b, merchant_c
from app.modules.buyer.ledger import buyer_ledger
from app.modules.watch.event_bus import event_bus
from app.modules.watch.objective import objective_store

MERCHANTS = {
    "merchant_a": merchant_a,
    "urbankicks": merchant_a,
    "merchant_b": merchant_b,
    "shoekart": merchant_b,
    "merchant_c": merchant_c,
    "fastfeet": merchant_c,
}


def restock_merchant(merchant_key: str, sku: str, stock: int):
    m = MERCHANTS.get(merchant_key.lower())
    if not m:
        print(f"[ERROR] Unknown merchant: {merchant_key}")
        return
    updated_item = m.set_stock(sku, stock)
    if updated_item:
        print(f"[SUCCESS] {m.merchant_name} restocked {sku} to {stock} units.")
        print("[EVENT BUS] Published INVENTORY_CHANGED event. Active watching objectives re-evaluated!")
    else:
        print(f"[ERROR] SKU {sku} not found in {m.merchant_name} catalog.")


def price_drop_merchant(merchant_key: str, sku: str, new_price: float):
    m = MERCHANTS.get(merchant_key.lower())
    if not m:
        print(f"[ERROR] Unknown merchant: {merchant_key}")
        return
    updated_item = m.set_price(sku, new_price)
    if updated_item:
        print(f"[SUCCESS] {m.merchant_name} updated price of {sku} to Rs. {new_price:,.2f}.")
        print("[EVENT BUS] Published PRICE_CHANGED event. Active watching objectives re-evaluated!")
    else:
        print(f"[ERROR] SKU {sku} not found in {m.merchant_name} catalog.")


def topup_buyer(amount: float):
    buyer_ledger.record_credit(amount=amount, source="razorpay_smart_collect", notes="Manual demo top-up via CLI")
    print(f"[SUCCESS] Credited Rs. {amount:,.2f} to Buyer Ledger. New balance: Rs. {buyer_ledger.available_balance:,.2f}")
    event_bus.publish(event_type="BALANCE_CHANGED", payload={"new_balance": buyer_ledger.available_balance})
    print("[EVENT BUS] Published BALANCE_CHANGED event. Active AWAITING_FUNDS objectives re-evaluated!")


def list_objectives():
    objs = objective_store.get_all_objectives()
    print(f"\n--- Tracked Shopping Objectives ({len(objs)}) ---")
    if not objs:
        print("  No active or historical shopping objectives recorded.")
    for obj in objs:
        print(f"  - ID: {obj.objective_id} | Status: {obj.status.value:<12} | Intent: '{obj.user_intent.get('query') or obj.user_intent.get('description')}'")
        if obj.watch_reason:
            print(f"    Reason: {obj.watch_reason}")
        if obj.purchase_result and obj.purchase_result.get("success"):
            pr = obj.purchase_result
            print(f"    Result: Purchased {pr.get('item_purchased')} from {pr.get('merchant')} for Rs. {pr.get('amount_paid_inr', 0):,.2f}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Commerce Event Trigger & Live Watch Simulator")
    parser.add_argument("action", choices=["restock", "price_drop", "topup", "list", "set_out_of_stock"], nargs="?", default="list")
    parser.add_argument("--merchant", default="shoekart", help="Merchant identifier (urbankicks, shoekart, fastfeet)")
    parser.add_argument("--sku", default="adidas-runfalcon-3_blue_10", help="Product variant SKU")
    parser.add_argument("--stock", type=int, default=4, help="New inventory stock quantity")
    parser.add_argument("--price", type=float, default=4200.0, help="New discounted unit price in INR")
    parser.add_argument("--amount", type=float, default=5000.0, help="Buyer treasury top-up amount in INR")

    args = parser.parse_args()

    if args.action == "restock":
        restock_merchant(args.merchant, args.sku, args.stock)
    elif args.action == "set_out_of_stock":
        restock_merchant(args.merchant, args.sku, 0)
    elif args.action == "price_drop":
        price_drop_merchant(args.merchant, args.sku, args.price)
    elif args.action == "topup":
        topup_buyer(args.amount)
    elif args.action == "list":
        list_objectives()

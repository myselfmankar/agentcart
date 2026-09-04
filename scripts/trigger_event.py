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


def restock_merchant(merchant_key: str, sku: str, stock: int):
    merchants = {'merchant_a': merchant_a, 'urbankicks': merchant_a, 'merchant_b': merchant_b, 'shoekart': merchant_b, 'merchant_c': merchant_c, 'fastfeet': merchant_c}
    m = merchants.get(merchant_key.lower())
    if not m:
        print(f'Unknown merchant: {merchant_key}')
        return
    updated_item = m.set_stock(sku, stock)
    if updated_item:
        print(f'[SUCCESS] {m.merchant_name} restocked {sku} to {stock} units.')
        print('[EVENT BUS] Published INVENTORY_CHANGED event. Active watching objectives re-evaluated!')
    else:
        print(f'[ERROR] SKU {sku} not found in {m.merchant_name} catalog.')

def topup_buyer(amount: float):
    buyer_ledger.record_credit(amount=amount, source='razorpay_smart_collect', notes='Manual demo top-up via CLI')
    print(f'[SUCCESS] Credited Rs. {amount:,-.2f} to Buyer Ledger. New balance: Rs. {buyer_ledger.available_balance:-.2f}')
    event_bus.publish(event_type='BALANCE_CHANGED', payload={'new_balance': buyer_ledger.available_balance})
    print('[ETENT BUS] Published BALANCE_CHANGED event. Active AWAITING_FUNDUL objectives re-evaluated!')

def list_objectives():
    objs = objective_store.get_all_objectives()
    print(f'Total tracked shopping objectives: {len(objs)}')
    for obj in objs:
        print(f'  - ID: {obj.objective_id} | Status: {obj.status} | Query: {obj.user_intent.get("query")} | Reason: {obj.watch_reason}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Autonomous Commerce Event Trigger')
    parser.add_argument('--action', choices=['restock', 'topup', 'list'], default='list')
    parser.add_argument('--merchant', default='shoekart')
    parser.add_argument('--sku', default='adidas-runfalcon-3_blue_10')
    parser.add_argument('--stock', type=int, default=4)
    parser.add_argument('--amount', type=float, default=5000.0)
    args = parser.parse_args()
    if args.action == 'restock':
        restock_merchant(args.merchant, args.sku, args.stock)
    elif args.action == 'topup':
        topup_buyer(args.amount)
    elif args.action == 'list':
        list_objectives()

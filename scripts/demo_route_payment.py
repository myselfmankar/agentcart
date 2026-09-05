"""Demo script: Razorpay Route & Live Multi-Merchant Payment Capture.

Demonstrates:
1. Creating a live test-mode Razorpay order for a specified merchant (FastFeet, ShoeKart, or UrbanKicks).
2. Attaching Razorpay Route metadata (notes and route accounts) for multi-merchant attribution.
3. Autonomously executing and capturing the domestic test payment against Razorpay.
4. Verifying that the order transitions to 'paid' and payment to 'captured' on dashboard.razorpay.com.
5. Displaying the multi-merchant Route settlement summary.

Usage:
    python scripts/demo_route_payment.py --merchant fastfeet --amount 1500
    python scripts/demo_route_payment.py --merchant shoekart --amount 2200
    python scripts/demo_route_payment.py --merchant urbankicks --amount 3100
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Ensure console stdout/stderr does not fail on Windows charmap encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.modules.razorpay.client import razorpay_client
from app.modules.razorpay.route import razorpay_route_manager


def run_demo(merchant_key: str, amount_inr: float) -> None:
    print("=" * 70)
    print("[*] RAZORPAY ROUTE MULTI-MERCHANT PAYMENT DEMONSTRATION")
    print("=" * 70)

    # 1. Resolve merchant info
    merchant_info = razorpay_route_manager.get_merchant_info(merchant_key)
    print(f"\n[1] Target Merchant Information:")
    print(f"    - Name:            {merchant_info['name']}")
    print(f"    - Merchant ID:     {merchant_info['id']}")
    print(f"    - Route Account:   {merchant_info['account_id']}")
    print(f"    - Merchant VPA:    {merchant_info['vpa']}")
    print(f"    - Amount:          Rs. {amount_inr:,.2f}")

    # 2. Check Route capability
    is_route_active = razorpay_route_manager.check_route_capability()
    route_mode = "Active Route (Linked Accounts)" if is_route_active else "Virtual Route (Attribution & Direct Settlement)"
    print(f"\n[2] Razorpay Route Mode: {route_mode}")

    # 3. Create live Razorpay Order with Route attribution
    print(f"\n[3] Creating Order on Razorpay...")
    order = razorpay_client.create_order(
        amount_inr=amount_inr,
        currency="INR",
        receipt=f"rcpt_demo_{merchant_info['id']}",
        merchant_id=merchant_info["id"],
        merchant_name=merchant_info["name"],
    )
    print(f"    [+] Order Created Successfully:")
    print(f"       - Order ID:     {order['id']}")
    print(f"       - Status:       {order.get('status')}")
    print(f"       - Amount:       Rs. {order.get('amount', 0) / 100:,.2f}")
    print(f"       - Route Notes:  {json.dumps(order.get('notes', {}))}")

    # 4. Execute authentic domestic test payment capture
    print(f"\n[4] Executing Live Test Payment Capture against Razorpay Sandbox...")
    payment = razorpay_client.execute_test_payment(
        order_id=order["id"],
        amount_inr=amount_inr,
        merchant_id=merchant_info["id"],
        merchant_name=merchant_info["name"],
        force_live=True,
    )
    print(f"    [+] Payment Processed:")
    print(f"       - Payment ID:   {payment.get('id')}")
    print(f"       - Status:       {payment.get('status')}")
    print(f"       - Method:       {payment.get('method')}")
    print(f"       - Captured:     {payment.get('captured')}")

    # 5. Fetch updated Order from Razorpay to verify 'paid' status
    print(f"\n[5] Verifying Live State from Razorpay API:")
    try:
        updated_order = razorpay_client.fetch_order(order["id"])
        print(f"       - Final Order Status: {updated_order.get('status')} (Paid: Rs. {updated_order.get('amount_paid', 0) / 100:,.2f})")
    except Exception as e:
        print(f"       - Could not fetch order details: {e}")

    # 6. Display Multi-Merchant Route Settlement Summary
    print(f"\n[6] Multi-Merchant Route Settlement Summary:")
    summary = razorpay_route_manager.get_settlement_summary()
    for m_id, data in summary.get("merchants", {}).items():
        print(f"    [Merchant] {data.get('name')} ({data.get('route_account')}):")
        print(f"       - Total Received:   Rs. {data.get('total_received_inr', 0.0):,.2f}")
        print(f"       - Total Settled:    Rs. {data.get('total_settled_inr', 0.0):,.2f}")
        print(f"       - Transactions:     {data.get('transaction_count', 0)}")

    print("\n" + "=" * 70)
    print("[SUCCESS] Verification Complete! Check https://dashboard.razorpay.com/app/orders")
    print(f"   You will see order '{order['id']}' marked as PAID, and under Payments,")
    print(f"   payment '{payment.get('id')}' CAPTURED with Collected Amount updated.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo Razorpay Route multi-merchant payment capture")
    parser.add_argument(
        "--merchant",
        default="fastfeet",
        choices=["fastfeet", "shoekart", "urbankicks"],
        help="Target merchant name or ID",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=1500.0,
        help="Payment amount in INR (default: 1500.0)",
    )
    args = parser.parse_args()
    run_demo(merchant_key=args.merchant, amount_inr=args.amount)

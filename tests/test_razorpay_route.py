"""Unit and integration tests for Razorpay Route & Multi-Merchant Settlement."""

import os
import tempfile
from pathlib import Path

import pytest

from app.modules.razorpay.client import RazorpayClientAdapter
from app.modules.razorpay.route import RazorpayRouteManager, razorpay_route_manager


@pytest.fixture
def temp_route_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_file = Path(tmpdir) / "test_route_ledger.json"
        mgr = RazorpayRouteManager(
            key_id="rzp_test_sample123",
            key_secret="secret123",
            ledger_path=ledger_file,
        )
        yield mgr


def test_merchant_resolution(temp_route_manager):
    """Verifies that all 3 merchants are recognized and canonicalized correctly."""
    mgr = temp_route_manager

    # UrbanKicks
    m1 = mgr.get_merchant_info("UrbanKicks")
    assert m1["id"] == "urbankicks"
    assert m1["name"] == "UrbanKicks"
    assert m1["account_id"] == "acc_urbankicks_route"

    # ShoeKart
    m2 = mgr.get_merchant_info("shoekart")
    assert m2["id"] == "shoekart"
    assert m2["name"] == "ShoeKart"
    assert m2["account_id"] == "acc_shoekart_route"

    # FastFeet
    m3 = mgr.get_merchant_info("FastFeet Store")
    assert m3["id"] == "fastfeet"
    assert m3["name"] == "FastFeet"
    assert m3["account_id"] == "acc_fastfeet_route"


def test_prepare_order_routing_virtual_mode(temp_route_manager):
    """Verifies that prepare_order_routing enriches notes with merchant route metadata."""
    mgr = temp_route_manager
    routing = mgr.prepare_order_routing(
        merchant_id_or_name="FastFeet",
        amount_inr=1500.0,
        currency="INR",
        existing_notes={"test_tag": "pytest"},
    )

    assert routing["merchant_id"] == "fastfeet"
    assert routing["merchant_name"] == "FastFeet"
    assert routing["route_account"] == "acc_fastfeet_route"
    assert "notes" in routing
    assert routing["notes"]["merchant_id"] == "fastfeet"
    assert routing["notes"]["merchant_name"] == "FastFeet"
    assert routing["notes"]["route_target"] == "acc_fastfeet_route"
    assert routing["notes"]["test_tag"] == "pytest"


def test_settlement_ledger_recording(temp_route_manager):
    """Verifies recording multi-merchant transactions in the settlement ledger."""
    mgr = temp_route_manager

    mgr.record_settlement(
        merchant_id_or_name="UrbanKicks",
        amount_inr=2000.0,
        order_id="order_test_1",
        payment_id="pay_test_1",
    )
    mgr.record_settlement(
        merchant_id_or_name="ShoeKart",
        amount_inr=3500.0,
        order_id="order_test_2",
        payment_id="pay_test_2",
    )
    mgr.record_settlement(
        merchant_id_or_name="UrbanKicks",
        amount_inr=1200.0,
        order_id="order_test_3",
        payment_id="pay_test_3",
    )

    summary = mgr.get_settlement_summary()
    assert summary["merchants"]["urbankicks"]["total_settled_inr"] == 3200.0
    assert summary["merchants"]["urbankicks"]["transaction_count"] == 2
    assert summary["merchants"]["shoekart"]["total_settled_inr"] == 3500.0
    assert summary["merchants"]["shoekart"]["transaction_count"] == 1
    assert len(summary["transactions"]) == 3


def test_client_order_creation_with_route(temp_route_manager):
    """Verifies that RazorpayClientAdapter uses Route preparation during order creation."""
    client = RazorpayClientAdapter(force_mock=True)

    order = client.create_order(
        amount_inr=2500.0,
        currency="INR",
        merchant_id="fastfeet",
        merchant_name="FastFeet",
    )

    assert order["amount"] == 250000
    assert order["status"] == "created"
    assert order["notes"]["merchant_id"] == "fastfeet"
    assert order["notes"]["merchant_name"] == "FastFeet"
    assert order["notes"]["route_target"] == "acc_fastfeet_route"


def test_client_execute_payment_and_route_settlement(temp_route_manager):
    """Verifies that executing a payment updates the Route settlement ledger."""
    client = RazorpayClientAdapter(force_mock=True)

    order = client.create_order(
        amount_inr=1800.0,
        currency="INR",
        merchant_id="shoekart",
    )

    payment = client.execute_test_payment(
        order_id=order["id"],
        amount_inr=1800.0,
        merchant_id="shoekart",
    )

    assert payment["status"] == "captured"
    assert payment["order_id"] == order["id"]

    # Verify order was marked paid
    fetched = client.fetch_order(order["id"])
    assert fetched["status"] == "paid"
    assert fetched["amount_paid"] == 180000

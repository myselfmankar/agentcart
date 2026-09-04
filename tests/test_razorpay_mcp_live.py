"""Live Integration Tests for Razorpay MCP Server (https://mcp.razorpay.com/mcp)."""

from dotenv import load_dotenv

load_dotenv()

import pytest

from app.modules.razorpay.mcp_client import razorpay_mcp_client


@pytest.mark.skipif(
    not razorpay_mcp_client.is_configured,
    reason="Razorpay live credentials not configured in environment",
)
def test_live_razorpay_mcp_create_and_fetch_order():
    """Verify real order creation and fetch on https://mcp.razorpay.com/mcp."""
    order = razorpay_mcp_client.create_order(
        amount_inr=1500.0,
        currency="INR",
        receipt="rcpt_pytest_live_mcp",
        notes={"test_runner": "pytest_live"},
    )
    assert order is not None
    assert "id" in order
    assert order["id"].startswith("order_")
    assert order["status"] == "created"
    assert order["amount"] == 150000  # 1500 INR in paise

    # Fetch using fetch_order tool
    fetched = razorpay_mcp_client.fetch_order(order["id"])
    assert fetched["id"] == order["id"]
    assert fetched["amount"] == 150000


@pytest.mark.skipif(
    not razorpay_mcp_client.is_configured,
    reason="Razorpay live credentials not configured in environment",
)
def test_live_razorpay_mcp_create_payment_link():
    """Verify real payment link creation on https://mcp.razorpay.com/mcp."""
    link = razorpay_mcp_client.create_payment_link(
        amount_inr=1500.0,
        currency="INR",
        description="Pytest Live MCP Payment Link",
        notes={"test_runner": "pytest_live"},
    )
    assert link is not None
    if "Too many requests" in str(link) or "limit of 30 reached" in str(link):
        pytest.skip("Razorpay test mode payment link quota reached")
    assert "id" in link or "short_url" in link
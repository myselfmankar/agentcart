"""Pytest test harness and fixtures.

Restores merchant state, buyer ledger, and objective store before each test to ensure test isolation across the regression suite.
"""

import pytest

from app.merchants import merchant_a, merchant_b, merchant_c
from app.merchants.repository import merchant_repository
from app.modules.buyer.ledger import buyer_ledger
from app.modules.watch.objective import objective_store


@pytest.fixture(autouse=True)
def reset_test_state():
    # Restore merchant baseline stock
    merchant_repository.update_stock("merchant_a", "adidas-runfalcon-3_blue_10", 5)
    merchant_repository.update_stock("merchant_b", "adidas-runfalcon-3_blue_10", 0)
    merchant_repository.update_stock("merchant_c", "adidas-runfalcon-3_blue_10", 8)

    merchant_a.reload_from_disk()
    merchant_b.reload_from_disk()
    merchant_c.reload_from_disk()

    # Reset buyer ledger to generous baseline
    buyer_ledger.reset(available_balance=50000.0, per_transaction_limit=50000.0)

    # Clear objective store cache
    objective_store.clear()

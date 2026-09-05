from pathlib import Path
import pytest

from app.merchants import merchant_a, merchant_b, merchant_c
from app.merchants.repository import merchant_repository
from app.modules.buyer.ledger import buyer_ledger
from app.modules.watch.objective import objective_store

# Isolate tests to a sandbox test database so running pytest never wipes live session data
_TEST_DB = Path(".temp-test-db")
_TEST_DB.mkdir(parents=True, exist_ok=True)
objective_store.file_path = _TEST_DB / "test_shopping_objectives.json"


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

    # Clear test objective store cache
    objective_store.clear()


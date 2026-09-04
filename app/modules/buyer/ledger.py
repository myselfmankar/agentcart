"""Buyer Spending Authority & Transaction Ledger.

Maintains deterministic buyer spending authority, available balance,
per-transaction limits, audit trails, and immutable debit ledger entries.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from app.modules.audit.trail import audit_trail
from app.modules.watch.event_bus import event_bus

logger = logging.getLogger("buyer_ledger")


class BuyerLimitDecision:
    """Outcome of buyer spending limit and balance evaluation."""

    def __init__(
        self,
        allowed: bool,
        reason: str | None = None,
        violations: list[str] | None = None,
        required_amount: float = 0.0,
        available_balance: float = 0.0,
        per_transaction_limit: float = 0.0,
        shortfall: float = 0.0,
        currency: str = "INR",
        details: dict[str, Any] | None = None,
    ):
        self.allowed = allowed
        self.reason = reason
        self.violations = violations or []
        self.required_amount = required_amount
        self.available_balance = available_balance
        self.per_transaction_limit = per_transaction_limit
        self.shortfall = shortfall
        self.currency = currency
        self.details = details or {}

    def __bool__(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": "approved" if self.allowed else "rejected",
            "reason": self.reason,
            "violations": self.violations,
            "required_amount": self.required_amount,
            "available_balance": self.available_balance,
            "per_transaction_limit": self.per_transaction_limit,
            "shortfall": self.shortfall,
            "currency": self.currency,
            "razorpay_called": False if not self.allowed else None,
            "details": self.details,
        }


class BuyerLedger:
    """Manages buyer balances, limits, and immutable debit entries."""

    def __init__(
        self,
        data_dir: Path | None = None,
        default_balance: float | None = None,
        default_limit: float | None = None,
        default_currency: str = "INR",
    ):
        self.data_dir = data_dir or Path("data/buyer")
        self.balance_file = self.data_dir / "balance.json"
        self.ledger_file = self.data_dir / "ledger.json"
        self.currency = default_currency

        # Load environment defaults if provided
        env_balance = os.getenv("BUYER_AVAILABLE_BALANCE")
        self.available_balance = float(env_balance) if env_balance else (default_balance if default_balance is not None else 50000.0)
        env_limit = os.getenv("BUYER_TRANSACTION_LIMIT")
        self.per_transaction_limit = float(env_limit) if env_limit else (default_limit if default_limit is not None else 10000.0)

        self._processed_payments: set = set()
        self._load()

    def _ensure_dir(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Loads balance and processed payments from disk if present."""
        try:
            if self.balance_file.exists():
                data = json.loads(self.balance_file.read_text(encoding="utf-8"))
                self.available_balance = float(data.get("available_balance", self.available_balance))
                self.per_transaction_limit = float(data.get("per_transaction_limit", self.per_transaction_limit))
                self.currency = data.get("currency", self.currency)
        except Exception as e:
            logger.warning("Could not read balance file %s: %s", self.balance_file, e)

        try:
            if self.ledger_file.exists():
                entries = json.loads(self.ledger_file.read_text(encoding="utf-8"))
                for entry in entries:
                    if "razorpay_payment_id" in entry:
                        self._processed_payments.add(entry["razorpay_payment_id"])
                    if "transaction_id" in entry:
                        self._processed_payments.add(entry["transaction_id"])
        except Exception as e:
            logger.warning("Could not read ledger file %s: %s", self.ledger_file, e)

        # Synchronize live balance from RazorpayX if configured
        self._sync_razorpayx_balance()

    def _sync_razorpayx_balance(self):
        """Fetches live balance from RazorpayX Banking API when active."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        key = os.getenv("RAZORPAY_KEY_ID")
        sec = os.getenv("RAZORPAY_KEY_SECRET")
        acc = os.getenv("RAZORPAYX_ACCOUNT_NUMBER")
        if not (key and sec and acc and not key.startswith("rzp_test_mock")):
            return
        try:
            import requests
            r = requests.get(
                "https://api.razorpay.com/v1/banking_balances",
                auth=(key, sec),
                timeout=3.0,
            )
            if r.status_code == 200:
                data = r.json()
                for item in data.get("items", []):
                    if item.get("account_number") == acc:
                        avail_paise = item.get("available_amount", item.get("amount", 0))
                        self.available_balance = float(avail_paise) / 100.0
                        self._save_balance(skip_sync=True)
                        break
        except Exception as e:
            logger.debug("Could not sync live RazorpayX balance: %s", e)

    def _save_balance(self, skip_sync: bool = False):
        """Persists current balance to disk."""
        try:
            self._ensure_dir()
            payload = {
                "currency": self.currency,
                "available_balance": self.available_balance,
                "per_transaction_limit": self.per_transaction_limit,
                "updated_at": time.time(),
            }
            self.balance_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save balance file: %s", e)

    def check_buyer_limits(
        self,
        amount: float,
        currency: str = "INR",
        objective_id: str = "obj_default",
        merchant_id: str | None = None,
        checkout_id: str | None = None,
    ) -> BuyerLimitDecision:
        """Evaluates whether the transaction satisfies per-transaction limit and available balance."""
        self._load()  # Hot-reload in case balance.json was edited externally
        timestamp = time.time()
        audit_trail.log_event(
            event_type="buyer.balance.checked",
            objective_id=objective_id,
            details={
                "required_amount": amount,
                "available_balance": self.available_balance,
                "per_transaction_limit": self.per_transaction_limit,
                "currency": currency,
                "merchant_id": merchant_id,
                "checkout_id": checkout_id,
                "timestamp": timestamp,
            },
            level="INFO",
        )

        # 1. Per-transaction limit check
        if amount > self.per_transaction_limit:
            reason = "TRANSACTION_LIMIT_EXCEEDED"
            violation = (
                f"TRANSACTION_LIMIT_EXCEEDED: Requested charge Rs. {amount:,.2f} "
                f"exceeds per-transaction limit of Rs. {self.per_transaction_limit:,.2f}"
            )
            audit_trail.log_event(
                event_type="payment.not_attempted",
                objective_id=objective_id,
                details={
                    "reason": reason,
                    "required_amount": amount,
                    "per_transaction_limit": self.per_transaction_limit,
                    "currency": currency,
                },
                level="WARNING",
            )
            return BuyerLimitDecision(
                allowed=False,
                reason=reason,
                violations=[violation],
                required_amount=amount,
                available_balance=self.available_balance,
                per_transaction_limit=self.per_transaction_limit,
                shortfall=0.0,
                currency=currency,
                details={"merchant_id": merchant_id, "checkout_id": checkout_id},
            )

        # 2. Available balance check
        if amount > self.available_balance:
            shortfall = amount - self.available_balance
            reason = "INSUFFICIENT_BUYER_BALANCE"
            violation = (
                f"INSUFFICIENT_BUYER_BALANCE: Requested charge Rs. {amount:,.2f} "
                f"exceeds buyer available balance Rs. {self.available_balance:,.2f} (shortfall Rs. {shortfall:,.2f})"
            )
            audit_trail.log_event(
                event_type="buyer.balance.insufficient",
                objective_id=objective_id,
                details={
                    "required_amount": amount,
                    "available_balance": self.available_balance,
                    "shortfall": shortfall,
                    "currency": currency,
                    "objective_id": objective_id,
                    "merchant_id": merchant_id,
                    "checkout_id": checkout_id,
                    "timestamp": timestamp,
                },
                level="ERROR",
            )
            audit_trail.log_event(
                event_type="payment.not_attempted",
                objective_id=objective_id,
                details={
                    "reason": reason,
                    "required_amount": amount,
                    "available_balance": self.available_balance,
                    "shortfall": shortfall,
                    "currency": currency,
                    "merchant_id": merchant_id,
                    "checkout_id": checkout_id,
                },
                level="WARNING",
            )
            return BuyerLimitDecision(
                allowed=False,
                reason=reason,
                violations=[violation],
                required_amount=amount,
                available_balance=self.available_balance,
                per_transaction_limit=self.per_transaction_limit,
                shortfall=shortfall,
                currency=currency,
                details={"merchant_id": merchant_id, "checkout_id": checkout_id},
            )

        return BuyerLimitDecision(
            allowed=True,
            required_amount=amount,
            available_balance=self.available_balance,
            per_transaction_limit=self.per_transaction_limit,
            shortfall=0.0,
            currency=currency,
            details={"merchant_id": merchant_id, "checkout_id": checkout_id},
        )

    def record_debit(
        self,
        transaction_id: str,
        amount: float,
        currency: str,
        merchant_id: str,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        status: str = "completed",
        objective_id: str = "obj_default",
    ) -> bool:
        """Reconciles buyer balance and appends exactly one immutable debit entry."""
        # Idempotency check: prevent duplicate debiting
        if razorpay_payment_id in self._processed_payments or transaction_id in self._processed_payments:
            logger.info("Payment %s already debited in ledger (idempotent skip)", razorpay_payment_id)
            return False

        self.available_balance -= amount
        self._processed_payments.add(razorpay_payment_id)
        self._processed_payments.add(transaction_id)
        self._save_balance()

        entry = {
            "transaction_id": transaction_id,
            "amount": amount,
            "currency": currency,
            "merchant_id": merchant_id,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "status": status,
            "timestamp": time.time(),
            "remaining_balance": self.available_balance,
        }

        try:
            self._ensure_dir()
            ledger_entries = []
            if self.ledger_file.exists():
                try:
                    ledger_entries = json.loads(self.ledger_file.read_text(encoding="utf-8"))
                except Exception:
                    ledger_entries = []
            ledger_entries.append(entry)
            self.ledger_file.write_text(json.dumps(ledger_entries, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to append to ledger file: %s", e)

        audit_trail.log_event(
            event_type="buyer.balance.debited",
            objective_id=objective_id,
            details=entry,
            level="INFO",
        )
        return True

    def deposit(self, amount: float, currency: str = "INR", objective_id: str = "system") -> float:
        """Adds funds to the buyer's available balance and publishes a BALANCE_CHANGED event."""
        self.available_balance += amount
        self._save_balance()

        event_payload = {
            "event_type": "BALANCE_CHANGED",
            "amount_added": amount,
            "new_balance": self.available_balance,
            "currency": currency,
            "timestamp": time.time(),
            "objective_id": objective_id,
        }

        audit_trail.log_event(
            event_type="buyer.balance.deposited",
            objective_id=objective_id,
            details=event_payload,
            level="INFO",
        )

        # Notify event bus for watching objectives
        event_bus.publish(event_payload)
        return self.available_balance

    def set_limits(
        self,
        available_balance: float | None = None,
        per_transaction_limit: float | None = None,
        publish_event: bool = True,
    ):
        """Sets balance or limits directly."""
        old_balance = self.available_balance
        if available_balance is not None:
            self.available_balance = float(available_balance)
        if per_transaction_limit is not None:
            self.per_transaction_limit = float(per_transaction_limit)
        self._save_balance()

        if publish_event and available_balance is not None and self.available_balance > old_balance:
            event_payload = {
                "event_type": "BALANCE_CHANGED",
                "amount_added": self.available_balance - old_balance,
                "new_balance": self.available_balance,
                "currency": self.currency,
                "timestamp": time.time(),
                "objective_id": "system",
            }
            event_bus.publish(event_payload)

    def reset(
        self,
        available_balance: float = 6000.0,
        per_transaction_limit: float = 5000.0,
        currency: str = "INR",
    ):
        """Resets the ledger and balance to clean default state for tests."""
        self.available_balance = available_balance
        self.per_transaction_limit = per_transaction_limit
        self.currency = currency
        self._processed_payments.clear()
        self._save_balance()
        if self.ledger_file.exists():
            try:
                self.ledger_file.unlink(missing_ok=True)
            except Exception:
                pass


# Global singleton
buyer_ledger = BuyerLedger()

"""Razorpay Route & Multi-Merchant Settlement Manager.

Manages payment routing, linked accounts, and settlement tracking across
multiple merchants (FastFeet, ShoeKart, UrbanKicks) using a single master
Razorpay account.

Supports:
1. Active Razorpay Route (Linked Accounts & Order Transfers) when Route feature is enabled.
2. Virtual Route Attribution (Merchant Tagging & RazorpayX Payouts) when Route is not yet enabled on the test key.
3. Persistent Multi-Merchant Settlement Ledger.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("razorpay_route")

# Merchant Registry with designated Route accounts
DEFAULT_MERCHANTS: dict[str, dict[str, Any]] = {
    "urbankicks": {
        "id": "urbankicks",
        "name": "UrbanKicks",
        "email": "vendor.urbankicks@example.com",
        "phone": "9876543211",
        "vpa": "urbankicks@razorpay",
        "account_id": "acc_urbankicks_route",
    },
    "shoekart": {
        "id": "shoekart",
        "name": "ShoeKart",
        "email": "vendor.shoekart@example.com",
        "phone": "9876543212",
        "vpa": "shoekart@razorpay",
        "account_id": "acc_shoekart_route",
    },
    "fastfeet": {
        "id": "fastfeet",
        "name": "FastFeet",
        "email": "vendor.fastfeet@example.com",
        "phone": "9876543213",
        "vpa": "fastfeet@razorpay",
        "account_id": "acc_fastfeet_route",
    },
}

_DEFAULT_LEDGER_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "adk_agents"
    / "data"
    / "merchants"
    / "route_ledger.json"
)


class RazorpayRouteManager:
    """Coordinates Razorpay Route multi-merchant payment distribution."""

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        ledger_path: Path | str | None = None,
    ):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")
        self.ledger_path = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER_PATH
        self._route_enabled: bool | None = None
        self._merchants = dict(DEFAULT_MERCHANTS)
        self._init_ledger()

    def _init_ledger(self) -> None:
        """Initializes the settlement ledger file if it does not exist."""
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.ledger_path.exists():
                initial_data = {
                    "master_account": self.key_id or "rzp_test_account",
                    "mode": "route_dual_mode",
                    "merchants": {
                        m_id: {
                            "name": m_data["name"],
                            "route_account": m_data["account_id"],
                            "total_received_inr": 0.0,
                            "total_settled_inr": 0.0,
                            "transaction_count": 0,
                        }
                        for m_id, m_data in self._merchants.items()
                    },
                    "transactions": [],
                }
                with open(self.ledger_path, "w", encoding="utf-8") as f:
                    json.dump(initial_data, f, indent=2)
        except Exception as e:
            logger.warning("Could not initialize Route ledger: %s", e)

    def normalize_merchant_id(self, merchant_id_or_name: str) -> str:
        """Normalizes merchant identifier or name to canonical key."""
        norm = re.sub(r"[^a-zA-Z0-9]", "", merchant_id_or_name or "").lower()
        for m_id, data in self._merchants.items():
            if m_id in norm or norm in m_id or data["name"].lower() in norm:
                return m_id
        return norm or "merchant_unknown"

    def get_merchant_info(self, merchant_id_or_name: str) -> dict[str, Any]:
        """Returns metadata for a given merchant."""
        canonical_id = self.normalize_merchant_id(merchant_id_or_name)
        if canonical_id in self._merchants:
            return self._merchants[canonical_id]
        clean_name = merchant_id_or_name or "Merchant"
        return {
            "id": canonical_id,
            "name": clean_name,
            "email": f"vendor.{canonical_id}@example.com",
            "phone": "9876543210",
            "vpa": f"{canonical_id}@razorpay",
            "account_id": f"acc_{canonical_id}_route",
        }

    def check_route_capability(self, force_refresh: bool = False) -> bool:
        """Checks whether the Razorpay account has the Route product feature enabled."""
        if self._route_enabled is not None and not force_refresh:
            return self._route_enabled

        if not (self.key_id and self.key_secret) or self.key_id.startswith("rzp_test_mock"):
            self._route_enabled = False
            return False

        if os.environ.get("PYTEST_CURRENT_TEST"):
            self._route_enabled = False
            return False

        try:
            import requests

            # Probe linked accounts endpoint
            resp = requests.post(
                "https://api.razorpay.com/v2/accounts",
                auth=(self.key_id, self.key_secret),
                json={"email": "probe.test@example.com", "type": "route"},
                timeout=4.0,
            )
            # If Route is not enabled, description says "Route feature not enabled for the merchant"
            if resp.status_code == 400 and "Route feature not enabled" in resp.text:
                self._route_enabled = False
            elif resp.status_code in (200, 201):
                self._route_enabled = True
            else:
                self._route_enabled = False
        except Exception:
            self._route_enabled = False

        return self._route_enabled

    def prepare_order_routing(
        self,
        merchant_id_or_name: str,
        amount_inr: float,
        currency: str = "INR",
        existing_notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepares Route parameters and notes for a Razorpay order creation.

        Returns a dictionary containing:
        - `notes`: enriched with merchant routing attribution
        - `transfers`: list of transfers if active Route is enabled, or empty list
        - `route_meta`: internal routing summary
        """
        merchant_info = self.get_merchant_info(merchant_id_or_name)
        m_id = merchant_info["id"]
        m_name = merchant_info["name"]
        m_account = merchant_info["account_id"]
        amount_paise = round(amount_inr * 100)

        notes = dict(existing_notes or {})
        notes["merchant_id"] = m_id
        notes["merchant_name"] = m_name
        notes["route_target"] = m_account
        notes["route_mode"] = "active_route" if self.check_route_capability() else "virtual_route"

        routing_payload: dict[str, Any] = {
            "notes": notes,
            "merchant_id": m_id,
            "merchant_name": m_name,
            "route_account": m_account,
        }

        # If live Route feature is enabled, attach transfer split
        if self.check_route_capability():
            routing_payload["transfers"] = [
                {
                    "account": m_account,
                    "amount": amount_paise,
                    "currency": currency,
                    "notes": {
                        "merchant_name": m_name,
                        "routing": "autonomous_marketplace",
                    },
                }
            ]

        return routing_payload

    def record_settlement(
        self,
        merchant_id_or_name: str,
        amount_inr: float,
        order_id: str,
        payment_id: str,
        currency: str = "INR",
        payout_id: str | None = None,
        status: str = "settled",
    ) -> dict[str, Any]:
        """Records a successful payment and settlement to a merchant in the Route ledger."""
        merchant_info = self.get_merchant_info(merchant_id_or_name)
        m_id = merchant_info["id"]
        m_name = merchant_info["name"]

        record = {
            "merchant_id": m_id,
            "merchant_name": m_name,
            "route_account": merchant_info["account_id"],
            "amount_inr": amount_inr,
            "currency": currency,
            "order_id": order_id,
            "payment_id": payment_id,
            "payout_id": payout_id,
            "status": status,
        }

        try:
            data = {"merchants": {}, "transactions": []}
            if self.ledger_path.exists():
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            if "merchants" not in data:
                data["merchants"] = {}
            if m_id not in data["merchants"]:
                data["merchants"][m_id] = {
                    "name": m_name,
                    "route_account": merchant_info["account_id"],
                    "total_received_inr": 0.0,
                    "total_settled_inr": 0.0,
                    "transaction_count": 0,
                }

            data["merchants"][m_id]["total_received_inr"] += amount_inr
            data["merchants"][m_id]["total_settled_inr"] += amount_inr
            data["merchants"][m_id]["transaction_count"] += 1

            if "transactions" not in data:
                data["transactions"] = []
            data["transactions"].append(record)

            with open(self.ledger_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.warning("Could not update Route settlement ledger: %s", e)

        return record

    def get_settlement_summary(self) -> dict[str, Any]:
        """Returns the current multi-merchant settlement summary."""
        try:
            if self.ledger_path.exists():
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"merchants": {}, "transactions": []}


# Global singleton route manager
razorpay_route_manager = RazorpayRouteManager()

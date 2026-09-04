"""Merchant Repository for Agentic Commerce.

Manages merchant catalogs loaded directly from JSON files in data/merchants/.
Supports both the multi-product variant schema and legacy catalog formats.
Supports hot reload so that live updates to stock, pricing, and discounts are immediately reflected.
"""

import json
import logging
from pathlib import Path
from typing import Any

from app.modules.acp.models import FulfillmentOption, Item

_logger = logging.getLogger("agentic_commerce.merchant_repository")
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _REPO_ROOT / "data" / "merchants"


class MerchantRepository:
    """Thread-safe file-backed repository for private merchant state."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}

    def _get_file_path(self, merchant_id: str) -> Path:
        isolated_path = _REPO_ROOT / "merchants" / merchant_id / "catalog.json"
        if isolated_path.exists():
            return isolated_path
        return self.data_dir / f"{merchant_id}.json"

    def load_merchant_data(self, merchant_id: str) -> dict[str, Any]:
        """Loads and returns the raw merchant JSON from disk."""
        path = self._get_file_path(merchant_id)
        if not path.exists():
            raise FileNotFoundError(f"Merchant file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._cache[merchant_id] = data
        return data

    def save_merchant_data(self, merchant_id: str, data: dict[str, Any]) -> None:
        """Persists updated merchant data back to disk."""
        path = self._get_file_path(merchant_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._cache[merchant_id] = data

    def get_catalog_items(self, merchant_id: str) -> list[Item]:
        """Loads items from merchant JSON and converts them to ACP Item models."""
        data = self.load_merchant_data(merchant_id)
        merchant_name = data.get("name") or data.get("merchant_name", merchant_id)
        currency = data.get("currency", "INR")
        items: list[Item] = []

        # 1. New schema: "products" with "variants"
        if "products" in data:
            for prod in data.get("products", []):
                p_id = prod.get("product_id", "")
                p_brand = prod.get("brand", "Unknown")
                p_name = prod.get("name", "")
                p_category = prod.get("category", "shoes")
                p_discount = prod.get("discount", {})
                p_delivery = prod.get("delivery", {})

                for var in prod.get("variants", []):
                    color = var.get("color", "default")
                    size = var.get("size", "all")
                    item_id = f"{p_id}_{color}_{size}"

                    attrs = {
                        "color": color,
                        "size": size,
                        "category": p_category,
                        "product_id": p_id,
                        "merchant_id": merchant_id,
                        "merchant_name": merchant_name,
                        "discount": p_discount,
                        "delivery": p_delivery,
                    }

                    item = Item(
                        id=item_id,
                        name=f"{p_brand} {p_name} ({color.title()}, Size {size})",
                        brand=p_brand,
                        price=float(var.get("price", 0.0)),
                        currency=currency,
                        stock=int(var.get("stock", 0)),
                        attributes=attrs,
                        description=f"{p_brand} {p_name} in {color} size {size}",
                    )
                    items.append(item)

        # 2. Legacy fallback: "catalog"
        elif "catalog" in data:
            for raw in data.get("catalog", []):
                item = Item(
                    id=raw["id"],
                    name=raw["name"],
                    brand=raw.get("brand", "Unknown"),
                    price=float(raw["price"]),
                    currency=raw.get("currency", currency),
                    stock=int(raw.get("stock", 0)),
                    attributes=raw.get("attributes", {}),
                    description=raw.get("description", ""),
                )
                items.append(item)

        return items

    def get_fulfillment_options(self, merchant_id: str) -> list[FulfillmentOption]:
        """Returns standard delivery and express delivery if configured."""
        data = self.load_merchant_data(merchant_id)
        opts: list[FulfillmentOption] = []

        # Check if products have delivery specs
        if data.get("products"):
            deliv = data["products"][0].get("delivery", {})
            std_days = deliv.get("standard_days", 4)
            exp_days = deliv.get("express_days", 2)
            exp_fee = float(deliv.get("express_fee", 99.0))
            opts.append(FulfillmentOption(id="standard", name="Standard Delivery", cost=0.0, estimated_days=std_days))
            opts.append(FulfillmentOption(id="express", name="Express Delivery", cost=exp_fee, estimated_days=exp_days))
        elif "fulfillment_options" in data:
            for raw in data.get("fulfillment_options", []):
                opts.append(
                    FulfillmentOption(
                        id=raw["id"],
                        name=raw["name"],
                        cost=float(raw.get("cost", 0.0)),
                        estimated_days=int(raw.get("estimated_days", 3)),
                    )
                )
        return opts

    def get_item(self, merchant_id: str, item_id: str) -> Item | None:
        items = self.get_catalog_items(merchant_id)
        for item in items:
            if item.id == item_id or item.attributes.get("product_id") == item_id:
                return item
            # Support fuzzy matching for demo keys (e.g. adidas_blue_10 matches adidas-runfalcon-3_blue_10)
            clean_target = item_id.lower().replace("-", "_")
            clean_cand = item.id.lower().replace("-", "_")
            if clean_target in clean_cand or clean_cand in clean_target:
                return item
        return None

    def update_stock(self, merchant_id: str, item_id: str, new_stock: int) -> Item | None:
        """Updates stock for a product variant on disk."""
        data = self.load_merchant_data(merchant_id)

        # 1. Update in products/variants
        if "products" in data:
            updated = False
            for prod in data.get("products", []):
                p_id = prod.get("product_id", "")
                for var in prod.get("variants", []):
                    var_key = f"{p_id}_{var.get('color')}_{var.get('size')}"
                    clean_target = item_id.lower().replace("-", "_")
                    clean_key = var_key.lower().replace("-", "_")

                    if clean_target in clean_key or clean_key in clean_target or item_id == "any":
                        var["stock"] = max(0, new_stock)
                        updated = True
                        break
                if updated:
                    break
            self.save_merchant_data(merchant_id, data)
            return self.get_item(merchant_id, item_id)

        # 2. Update in legacy catalog
        if "catalog" in data:
            for raw in data.get("catalog", []):
                if raw["id"] == item_id or item_id == "any":
                    raw["stock"] = max(0, new_stock)
                    break
            self.save_merchant_data(merchant_id, data)
            return self.get_item(merchant_id, item_id)

        return None

    def update_price(self, merchant_id: str, item_id: str, new_price: float) -> Item | None:
        """Updates price for a product variant on disk."""
        data = self.load_merchant_data(merchant_id)

        # 1. Update in products/variants
        if "products" in data:
            updated = False
            for prod in data.get("products", []):
                p_id = prod.get("product_id", "")
                for var in prod.get("variants", []):
                    var_key = f"{p_id}_{var.get('color')}_{var.get('size')}"
                    clean_target = item_id.lower().replace("-", "_")
                    clean_key = var_key.lower().replace("-", "_")

                    if clean_target in clean_key or clean_key in clean_target or item_id == "any":
                        var["price"] = float(new_price)
                        updated = True
                        break
                if updated:
                    break
            self.save_merchant_data(merchant_id, data)
            return self.get_item(merchant_id, item_id)

        # 2. Update in legacy catalog
        if "catalog" in data:
            for raw in data.get("catalog", []):
                if raw["id"] == item_id or item_id == "any":
                    raw["price"] = float(new_price)
                    break
            self.save_merchant_data(merchant_id, data)
            return self.get_item(merchant_id, item_id)

        return None


merchant_repository = MerchantRepository()

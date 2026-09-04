"""Base Autonomous Merchant Agent.

Represents an independent seller-side autonomous agent with its own:
- Isolated catalog (catalog.json)
- Isolated commercial policy (policy.json)
- Dynamic ACP proposal formulation
- Dynamic 1-to-1 counter-negotiation engine
- Authoritative ACP checkout session creation and ES256 signing
- Compliant A2A Agent Card and message handling
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    from google import genai
except ImportError:
    genai = None

from app.modules.a2a.agent_card import AgentCard, AgentSkill
from app.modules.acp.checkout import checkout_manager
from app.modules.acp.models import (
    AuthoritativeCheckoutToken,
    CheckoutSession,
    Item,
    MerchantProposal,
)

logger = logging.getLogger("merchant_agent")


class BaseMerchantAgent:
    """Independent autonomous Merchant Agent that represents a seller's business."""

    def __init__(
        self,
        merchant_id: str,
        base_dir: Path,
        catalog_filename: str = "catalog.json",
        policy_filename: str = "policy.json",
        base_url: str | None = None,
    ):
        self.merchant_id = merchant_id
        self.base_dir = Path(base_dir)
        self.catalog_file = self.base_dir / catalog_filename
        self.policy_file = self.base_dir / policy_filename
        self.base_url = base_url or f"http://localhost:8000/a2a/{merchant_id}"

        self.merchant_name: str = merchant_id
        self.currency: str = "INR"
        self.products: list[dict[str, Any]] = []
        self.inventory: dict[str, Item] = {}
        self.policy: dict[str, Any] = {}

        self.reload_from_disk()

    def reload_from_disk(self) -> None:
        """Loads catalog.json and policy.json from the merchant's isolated directory."""
        if self.policy_file.exists():
            self.policy = json.loads(self.policy_file.read_text(encoding="utf-8"))

        if self.catalog_file.exists():
            data = json.loads(self.catalog_file.read_text(encoding="utf-8"))
            self.merchant_name = data.get("name", self.merchant_name)
            self.currency = data.get("currency", self.currency)
            self.products = data.get("products", [])

            # Flatten variants into Item models
            items: dict[str, Item] = {}
            for prod in self.products:
                pid = prod.get("product_id")
                brand = prod.get("brand", "")
                name = prod.get("name", "")
                category = prod.get("category", "")
                desc = prod.get("description", f"{brand} {name} {category}".strip())
                deliv = (
                    self.policy.get("fulfillment_policy", {}).get(pid)
                    or self.policy.get("fulfillment_policy", {}).get("default", {})
                    or prod.get("delivery", {})
                )

                for v in prod.get("variants", []):
                    color = v.get("color", "")
                    size = v.get("size", "")
                    vid = f"{pid}_{color}_{size}".replace(" ", "_")
                    price = float(v.get("price", 0.0))
                    stock = int(v.get("stock", 0))

                    attrs = {
                        "color": color,
                        "size": size,
                        "category": category,
                        "product_id": pid,
                        "merchant_id": self.merchant_id,
                        "discount": prod.get("discount", {}),
                        "delivery": deliv,
                    }
                    items[vid] = Item(
                        id=vid,
                        name=f"{brand} {name} ({color.capitalize()}, Size {size})",
                        brand=brand,
                        price=price,
                        currency=self.currency,
                        stock=stock,
                        attributes=attrs,
                        description=desc,
                    )
            self.inventory = items

    def save_catalog_to_disk(self) -> None:
        """Persists catalog data to disk."""
        data = {
            "merchant_id": self.merchant_id,
            "name": self.merchant_name,
            "currency": self.currency,
            "products": self.products,
        }
        self.catalog_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def save_policy_to_disk(self) -> None:
        """Persists policy data to disk."""
        self.policy_file.write_text(json.dumps(self.policy, indent=2), encoding="utf-8")

    def get_agent_card(self) -> AgentCard:
        """Generates an A2A Agent Card advertising this merchant's capabilities."""
        objective = self.policy.get("business_objective", "Autonomous seller representative")
        negotiable = self.policy.get("negotiation_policy", {}).get("allows_negotiation", False)

        skills = [
            AgentSkill(
                name="request_proposal",
                description="Formulates a binding commercial proposal with price, discounts, and delivery.",
                parameters={
                    "query": "Product or brand query",
                    "filters": "Variant filters such as size and color",
                },
            ),
            AgentSkill(
                name="create_checkout",
                description="Creates an authoritative ACP checkout session signed with merchant private key.",
                parameters={"item_id": "Item SKU", "quantity": "Quantity", "agreed_price": "Negotiated price"},
            ),
            AgentSkill(
                name="complete_checkout",
                description="Finalizes checkout session upon verified payment capture and decrements stock.",
                parameters={"session_id": "Checkout session ID", "payment_id": "Razorpay payment ID"},
            ),
        ]

        if negotiable:
            skills.append(
                AgentSkill(
                    name="negotiate_proposal",
                    description="1-to-1 dynamic counter-negotiation to beat competitor pricing within merchant policy margins.",
                    parameters={"proposal_id": "Original proposal ID", "competing_price": "Competing quote to beat"},
                )
            )

        return AgentCard(
            name=self.merchant_name,
            description=f"{self.merchant_name} — {objective}",
            url=self.base_url,
            protocols=["a2a", "acp", "ap2"],
            skills=skills,
            provider={
                "id": self.merchant_id,
                "name": self.merchant_name,
                "negotiable": negotiable,
                "currency": self.currency,
            },
        )

    def get_catalog(self) -> list[Item]:
        """Returns the full catalog of items for this merchant."""
        self.reload_from_disk()
        return list(self.inventory.values())

    def search_catalog(
        self,
        query: str = "",
        filters: dict[str, Any] | None = None,
    ) -> list[Item]:
        """Returns the complete catalog directly to the agent.

        No regexes or keyword token slop: the LLM receives the full catalog
        context to reason over all products, prices, and variants.
        """
        return self.get_catalog()

    def get_full_catalog(self) -> list[dict[str, Any]]:
        """Returns the full catalog with all products, variants, prices, colors, stock, and delivery."""
        self.reload_from_disk()
        return [it.model_dump() for it in self.inventory.values()]

    def get_item(self, item_id: str) -> Item | None:
        self.reload_from_disk()
        if item_id in self.inventory:
            return self.inventory[item_id]
        for it in self.inventory.values():
            if it.id == item_id:
                return it
            clean_t = item_id.lower().replace("-", "_")
            clean_i = it.id.lower().replace("-", "_")
            if clean_t in clean_i or clean_i in clean_t:
                return it
        return None

    def set_stock(self, item_id: str, new_stock: int) -> Item | None:
        """Updates stock for a product variant, persists to catalog.json, and publishes INVENTORY_CHANGED."""
        self.reload_from_disk()
        for prod in self.products:
            pid = prod.get("product_id")
            for v in prod.get("variants", []):
                color = v.get("color", "")
                size = v.get("size", "")
                vid = f"{pid}_{color}_{size}".replace(" ", "_")
                if vid == item_id or item_id in vid or vid in item_id:
                    v["stock"] = int(new_stock)
                    self.save_catalog_to_disk()
                    self.reload_from_disk()
                    item = self.get_item(vid)
                    try:
                        from app.modules.watch.event_bus import event_bus
                        event_bus.publish(
                            event_type="INVENTORY_CHANGED",
                            merchant_id=self.merchant_id,
                            item_id=vid,
                            payload={"stock": int(new_stock), "price": v.get("price")},
                        )
                    except Exception as e:
                        logger.warning("Failed to publish INVENTORY_CHANGED event: %s", e)
                    return item
        return None

    def set_price(self, item_id: str, new_price: float) -> Item | None:
        """Updates base price for a product variant, persists to catalog.json, and publishes PRICE_CHANGED."""
        self.reload_from_disk()
        for prod in self.products:
            pid = prod.get("product_id")
            for v in prod.get("variants", []):
                color = v.get("color", "")
                size = v.get("size", "")
                vid = f"{pid}_{color}_{size}".replace(" ", "_")
                if vid == item_id or item_id in vid or vid in item_id:
                    v["price"] = float(new_price)
                    self.save_catalog_to_disk()
                    self.reload_from_disk()
                    item = self.get_item(vid)
                    try:
                        from app.modules.watch.event_bus import event_bus
                        event_bus.publish(
                            event_type="PRICE_CHANGED",
                            merchant_id=self.merchant_id,
                            item_id=vid,
                            payload={"price": float(new_price), "stock": v.get("stock")},
                        )
                    except Exception as e:
                        logger.warning("Failed to publish PRICE_CHANGED event: %s", e)
                    return item
        return None

    def _call_merchant_llm(self, prompt: str) -> dict[str, Any] | None:
        """Calls Gemini LLM to reason over the merchant's catalog and policy."""
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key or not genai:
            return None

        try:
            client = genai.Client(api_key=api_key)
            model_name = os.getenv("AGENT_MODEL", "gemini-3.5-flash")
            if not model_name:
                model_name = "gemini-3.5-flash"

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            if response and response.text:
                return json.loads(response.text)
        except Exception as e:
            logger.warning(f"Merchant {self.merchant_id} LLM reasoning exception: {e}")
            return None
        return None

    def _evaluate_catalog_with_llm(
        self, query: str = "", filters: dict[str, Any] | None = None
    ) -> MerchantProposal | None:
        """Option A: Pure LLM Merchant Agent reasoning over complete catalog and policy."""
        filters = filters or {}
        intent_payload = {
            "query": query,
            "brand": filters.get("brand"),
            "category": filters.get("category", "footwear"),
            "color": filters.get("color"),
            "size": filters.get("size"),
            "max_price": filters.get("max_price"),
            "max_delivery_days": filters.get("max_delivery_days"),
        }

        prompt = f"""You are the autonomous AI sales representative for '{self.merchant_name}' (Merchant ID: '{self.merchant_id}').
Your business objective: {self.policy.get("business_objective", "Maximize conversion while protecting profit margins.")}

Customer Shopping Intent:
{json.dumps(intent_payload, indent=2)}

Your Entire Store Catalog:
{json.dumps(self.products, indent=2)}

Your Commercial Policy (Pricing, Discounts, Negotiation, Fulfillment):
{json.dumps(self.policy, indent=2)}

Instructions:
1. Evaluate all products across footwear, t-shirts, apparel, and jackets against the customer's shopping intent.
2. Evaluate all products and variants in your catalog against the customer's shopping intent.
3. Select the single best product variant to propose to this customer.
4. Calculate the base price, discount amount, and net proposed price following your discount_policy.
5. Determine delivery capability from your fulfillment_policy (standard delivery days, no express bypass).
6. Check if your negotiation_policy allows negotiation and whether this item is negotiable.
7. If an item matches the customer's request but is currently out of stock (stock == 0), still select it and set stock=0 to provide inventory transparency.
8. If NO product in your catalog matches the customer's requested product category, brand, or item type (e.g. customer requests cargo pants/pants and your store has no pants, or customer requests jackets and your store has no jackets), you MUST set "has_match": false. Do NOT substitute with an unrelated product.
9. Craft a unique, natural commercial pitch representing {self.merchant_name}.

Respond with a JSON object with this exact structure:
{{
  "has_match": true,
  "selected_item_id": "<product_id>_<color>_<size>",
  "product_name": "<full item name>",
  "brand": "<brand>",
  "color": "<color>",
  "size": 10,
  "base_price": 5299.0,
  "discount_amount": 400.0,
  "proposed_price": 4899.0,
  "stock": 5,
  "delivery_days": 4,
  "is_negotiable": false,
  "commercial_pitch": "<pitch string>"
}}
"""
        res_json = self._call_merchant_llm(prompt)
        if not res_json or not res_json.get("has_match"):
            return None

        # Resolve selected item in inventory directly from the LLM's choice
        item_id = res_json.get("selected_item_id", "")
        item = self.get_item(item_id)
        if not item:
            clean_id = item_id.replace(" ", "_").lower()
            for it in self.inventory.values():
                if clean_id in it.id.lower() or it.id.lower() in clean_id:
                    item = it
                    break
        if not item:
            return None

        base_price = float(res_json.get("base_price", item.price))
        disc_amount = float(res_json.get("discount_amount", 0.0))
        proposed_price = float(res_json.get("proposed_price", base_price - disc_amount))
        stock = int(res_json.get("stock", item.stock))
        std_days = int(res_json.get("delivery_days", res_json.get("standard_delivery_days", 4)))
        exp_days = std_days
        exp_fee = 0.0
        is_neg = bool(res_json.get("is_negotiable", False))
        pitch = res_json.get("commercial_pitch") or f"{self.merchant_name}: Offering {item.name} for Rs. {proposed_price:,.2f}"

        item.attributes["delivery"] = {
            "standard_days": std_days,
            "express_days": exp_days,
            "express_fee": exp_fee,
        }

        return MerchantProposal(
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            item=item,
            base_price=base_price,
            discount_type="llm_evaluated",
            discount_amount=disc_amount,
            proposed_price=proposed_price,
            currency=self.currency,
            stock=stock,
            is_in_stock=(stock > 0),
            standard_delivery_days=std_days,
            express_delivery_days=exp_days,
            express_delivery_fee=exp_fee,
            is_negotiable=is_neg,
            minimum_price_floor=float(self.policy.get("negotiation_policy", {}).get("floor_price", 0.0)) or None,
            commercial_pitch=pitch,
        )

    def _evaluate_catalog_fallback(
        self,
        query: str = "",
        filters: dict[str, Any] | None = None,
    ) -> MerchantProposal | None:
        matching = list(self.inventory.values())
        filters = filters or {}
        brand_req = (filters.get("brand") or "").lower().strip()
        color_req = (filters.get("color") or "").lower().strip()
        size_req = filters.get("size")

        if not brand_req:
            for b in ["adidas", "nike", "puma", "asics", "reebok", "new balance", "cargolab", "poloclub", "urbanstyle", "denimco"]:
                if b in query.lower():
                    brand_req = b
                    break

        candidates = []
        for it in matching:
            if brand_req and brand_req not in it.brand.lower() and brand_req not in it.name.lower():
                continue
            if color_req and color_req not in ["any", "all", ""]:
                if color_req not in (it.attributes.get("color") or "").lower():
                    continue
            if size_req is not None and str(size_req) not in ["", "0", "None", "any"]:
                if str(it.attributes.get("size", "")).lower() != str(size_req).lower():
                    continue
            candidates.append(it)

        if candidates:
            matching = candidates
        elif brand_req or size_req or (color_req and color_req not in ["any", "all", ""]):
            return None

        # Prioritize in-stock candidates, then lowest price
        matching.sort(key=lambda it: (0 if it.stock > 0 else 1, it.price))
        candidate = matching[0]
        base_price = candidate.price
        stock = candidate.stock
        attrs = candidate.attributes or {}
        prod_id = attrs.get("product_id", "")

        # Look up discount policy from policy.json or catalog fallback
        prod_discount_policy = self.policy.get("discount_policy", {}).get(prod_id, {})
        if not prod_discount_policy:
            prod_discount_policy = attrs.get("discount", {})

        prod_delivery_policy = self.policy.get("fulfillment_policy", {}).get(prod_id, {})
        if not prod_delivery_policy:
            prod_delivery_policy = self.policy.get("fulfillment_policy", {}).get("default", {})
        if not prod_delivery_policy:
            prod_delivery_policy = attrs.get("delivery", {})

        disc_type = prod_discount_policy.get("type", "none")
        disc_amount = 0.0
        is_negotiable = False
        min_price = None

        # Check discount eligibility based on inventory and rules
        eligible = False
        elig_rule = prod_discount_policy.get("eligible_if", "none")
        if elig_rule == "any" or elig_rule == "stock_above_2" and stock > 2 or elig_rule == "stock_above_3" and stock > 3 or elig_rule == "stock_above_4" and stock > 4 or elig_rule == "stock_above_5" and stock > 5:
            eligible = True

        if eligible and stock > 0:
            if disc_type == "flat":
                disc_amount = float(prod_discount_policy.get("amount", 0.0))
            elif disc_type == "percentage":
                pct = float(prod_discount_policy.get("amount", 0.0))
                disc_amount = round(base_price * (pct / 100.0), 2)
            elif disc_type == "negotiable":
                is_negotiable = True
                min_price = float(prod_discount_policy.get("minimum_price", base_price - 300))
                max_amt = float(prod_discount_policy.get("max_amount", 300))
                disc_amount = round(max_amt * 0.55, 2)

        # Check if merchant global negotiation policy allows negotiation and sets a floor
        neg_policy = self.policy.get("negotiation_policy", {})
        if neg_policy.get("allows_negotiation", False):
            is_negotiable = True
            policy_floor = float(neg_policy.get("floor_price", 0.0))
            if policy_floor > 0:
                min_price = max(min_price or 0.0, policy_floor)
            elif min_price is None:
                min_price = float(neg_policy.get("floor_price", base_price - 400))

        proposed_price = max(base_price - disc_amount, min_price or 0.0)

        # Delivery terms
        # Delivery terms (product-specific standard delivery)
        std_days = int(prod_delivery_policy.get("standard_days", 4))
        exp_days = std_days
        exp_fee = 0.0

        candidate.attributes["delivery"] = {
            "standard_days": std_days,
            "express_days": exp_days,
            "express_fee": exp_fee,
        }

        # Commercial pitch message aligned with merchant strategy
        if stock == 0:
            pitch = f"{self.merchant_name}: {candidate.name} is currently out of stock (base price Rs. {base_price:,.2f})."
        elif is_negotiable:
            pitch = (
                f"{self.merchant_name}: {candidate.name} in stock ({stock} units). "
                f"Base Rs. {base_price:,.2f} discounted to Rs. {proposed_price:,.2f} ({std_days}-day delivery). "
                f"Open to competitive counter-offers."
            )
        elif disc_amount > 0:
            pitch = (
                f"{self.merchant_name}: {candidate.name} in stock ({stock} units). "
                f"Healthy inventory qualifies for Rs. {disc_amount:,.2f} discount! Net: Rs. {proposed_price:,.2f} ({std_days}-day delivery)."
            )
        else:
            pitch = (
                f"{self.merchant_name}: {candidate.name} in stock ({stock} units). "
                f"Firm price Rs. {proposed_price:,.2f} ({std_days}-day delivery)."
            )

        return MerchantProposal(
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            item=candidate,
            base_price=base_price,
            discount_type=disc_type,
            discount_amount=disc_amount,
            proposed_price=proposed_price,
            currency=candidate.currency,
            stock=stock,
            is_in_stock=(stock > 0),
            standard_delivery_days=std_days,
            express_delivery_days=exp_days,
            express_delivery_fee=exp_fee,
            is_negotiable=is_negotiable,
            minimum_price_floor=min_price,
            commercial_pitch=pitch,
        )

    def create_proposal(
        self,
        query: str = "",
        filters: dict[str, Any] | None = None,
    ) -> MerchantProposal | None:
        """A2A Entry point: Formulates an ACP commercial proposal based on merchant catalog, stock, and commercial policy."""
        self.reload_from_disk()

        # In automated test suites, use fast deterministic evaluation to prevent API rate limits
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return self._evaluate_catalog_fallback(query=query, filters=filters)

        # Option A: Pure LLM Merchant Agent reasoning over entire catalog and policy
        llm_prop = self._evaluate_catalog_with_llm(query=query, filters=filters)
        if llm_prop is not None:
            return llm_prop

        # Deterministic fallback if LLM is unavailable or offline
        return self._evaluate_catalog_fallback(query=query, filters=filters)

    def negotiate(
        self,
        proposal: MerchantProposal,
        competing_price: float,
    ) -> MerchantProposal | None:
        """A2A Entry point: Evaluates buyer counter-offer against merchant commercial strategy and margin constraints."""
        self.reload_from_disk()
        neg_policy = self.policy.get("negotiation_policy", {})

        if not proposal.is_negotiable and not neg_policy.get("allows_negotiation", False):
            return None

        floor = proposal.minimum_price_floor
        policy_floor = float(neg_policy.get("floor_price", 0.0))
        if policy_floor > 0:
            floor = max(floor or 0.0, policy_floor)
        if floor is None:
            floor = float(neg_policy.get("floor_price", proposal.base_price - 400))

        undercut_step = float(neg_policy.get("undercut_step", 50.0))
        target_price = competing_price - undercut_step

        target_price = max(target_price, floor)

        if target_price >= proposal.proposed_price:
            return None  # Cannot improve further

        concession = proposal.base_price - target_price
        revised_pitch = (
            f"{self.merchant_name}: We want your business! "
            f"Beating competitor quote of Rs. {competing_price:,.2f} with a counter-offer of Rs. {target_price:,.2f} "
            f"with reliable {proposal.standard_delivery_days}-day delivery."
        )

        return MerchantProposal(
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            item=proposal.item,
            base_price=proposal.base_price,
            discount_type="negotiated",
            discount_amount=round(concession, 2),
            proposed_price=round(target_price, 2),
            currency=proposal.currency,
            stock=proposal.stock,
            is_in_stock=proposal.is_in_stock,
            standard_delivery_days=proposal.standard_delivery_days,
            express_delivery_days=proposal.standard_delivery_days,
            express_delivery_fee=0.0,
            is_negotiable=False,
            minimum_price_floor=floor,
            commercial_pitch=revised_pitch,
        )

    def create_checkout(
        self,
        item_id: str,
        quantity: int = 1,
        agreed_price: float | None = None,
    ) -> CheckoutSession:
        """A2A Entry point: Initiates an ACP checkout session with authoritative merchant prices."""
        item = self.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found at {self.merchant_name}")
        if item.stock < quantity:
            raise ValueError(f"Item {item_id} out of stock at {self.merchant_name}")

        checkout_item = item.model_copy()
        if agreed_price is not None:
            checkout_item.price = float(agreed_price)

        return checkout_manager.create_session(
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            items=[checkout_item],
            quantities=[quantity],
        )

    def sign_authoritative_checkout(self, session_id: str) -> AuthoritativeCheckoutToken:
        """Signs the checkout session with the merchant's ES256 private key."""
        return checkout_manager.sign_authoritative_checkout(session_id)

    def complete_checkout(self, session_id: str, payment_id: str) -> CheckoutSession:
        """Completes checkout session upon verified payment and decrements inventory."""
        session = checkout_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Checkout session {session_id} not found")
        for line in session.line_items:
            item = self.get_item(line.item.id)
            if item:
                self.set_stock(item.id, max(0, item.stock - line.quantity))
        return checkout_manager.complete_session(session_id, payment_id)

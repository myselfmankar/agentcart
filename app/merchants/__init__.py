"""Merchants package with lazy attribute resolution to prevent circular imports."""

from typing import Any


def __getattr__(name: str) -> Any:
    if name in ("Merchant", "merchant_a", "merchant_b", "merchant_c"):
        from app.merchants import merchant

        return getattr(merchant, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Merchant", "merchant_a", "merchant_b", "merchant_c"]

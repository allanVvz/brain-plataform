"""Canonical price contract shared by control-plane and conversation-runtime.

Product price exists today in five different storage shapes with no formal
contract anywhere:

  1. v3/Tock canonical write   -> ``data["offer"]``
  2. offer-node / legacy graph -> ``data["price"]``
  3. product_import_service    -> ``metadata["price"]["unit"]["amount"]``
     (``unit`` is a **dict** to unwrap)
  4. offer NODES                -> ``metadata["amount"]`` / ``metadata["currency"]``
     directly on the node's own metadata (product_import_service:551-579)
  5. knowledge_rag_intake      -> ``metadata["price"]`` with
     ``{"amount", "currency", "unit": "por kg", "display"}``
     (``unit`` here is a **string** label, never a dict to unwrap)
  6. Baita                     -> ``metadata["price_cents"]`` (integer cents)

``Offer`` is the single canonical slot going forward. ``normalize_offer``
reads any of the shapes above; ``offer_to_price_cents`` derives the legacy
integer-cents field so existing readers keep working during the dual-emit
transition (see docs/roadmaps/AGENT_ROADMAP.md).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from .models import ContractModel


class Offer(ContractModel):
    amount: float
    currency: str = "BRL"
    channel: Literal["varejo", "atacado"] | None = None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _channel_from(*sources: Any) -> Optional[str]:
    for source in sources:
        if isinstance(source, dict):
            value = source.get("channel")
            if value in ("varejo", "atacado"):
                return value
    return None


def _amount_currency_from_price_dict(price: dict) -> Optional[tuple[float, str]]:
    """Pull ``amount``/``currency`` out of one price-like dict.

    ``unit`` is the single field that means two unrelated things depending on
    the writer: ``product_import_service`` nests the real amount/currency
    inside a ``unit`` *dict* (``metadata.price.unit.amount``); the RAG intake
    pipeline instead writes a ``unit`` *string* label such as ``"por kg"``
    describing how the already-top-level amount is priced. Only the dict
    shape gets unwrapped -- a string ``unit`` is never dict-unwrapped.
    """
    unit = price.get("unit")
    source = unit if isinstance(unit, dict) else price
    amount = _as_float(source.get("amount"))
    if amount is None and source is not price:
        amount = _as_float(price.get("amount"))
    if amount is None:
        return None
    currency = str(source.get("currency") or price.get("currency") or "BRL")
    if currency.upper() == "PERCENT":
        # knowledge_rag_intake also extracts bare "30%" discounts from free
        # text with this same shape; that is a discount, never a price.
        return None
    return amount, currency


def normalize_offer(data: dict, metadata: dict | None = None) -> Optional[Offer]:
    """Read the canonical price out of whichever of the write shapes exist.

    Fallback chain, in order:
      1. ``data["offer"]``           - v3/Tock canonical write.
      2. ``data["price"]``           - offer-node / legacy graph write.
      3. ``metadata["price"]``       - product_import_service (unit dict) and
         knowledge_rag_intake (unit str) shapes.
      4. ``metadata`` itself         - offer NODES write amount/currency
         directly on the node's own metadata, not nested under "price".
      5. ``data["price_cents"]``     - already-cents integer at data level.
      6. ``metadata["price_cents"]`` - Baita's integer-cents write.
    """
    data = data or {}
    metadata = metadata or {}

    for raw in (data.get("offer"), data.get("price"), metadata.get("price"), metadata):
        if not isinstance(raw, dict):
            continue
        result = _amount_currency_from_price_dict(raw)
        if result is None:
            continue
        amount, currency = result
        channel = _channel_from(raw, data, metadata)
        return Offer(amount=amount, currency=currency, channel=channel)

    for cents_source in (data, metadata):
        cents = cents_source.get("price_cents")
        if cents is None:
            continue
        try:
            amount = int(cents) / 100
        except (TypeError, ValueError):
            continue
        channel = _channel_from(data, metadata)
        return Offer(amount=amount, currency="BRL", channel=channel)

    return None


def offer_to_price_cents(offer: Offer | None) -> int:
    """Derive the legacy integer-cents field from the canonical offer."""
    if offer is None:
        return 0
    return round(offer.amount * 100)

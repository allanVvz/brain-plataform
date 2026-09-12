"""Product price exists in five different storage shapes with no formal
contract anywhere -- this file pins ``brain_contracts.pricing.normalize_offer``
as the single reader for all of them.

Real production symptoms this guards against:
  - vz-lupas: ``metadata.price.amount`` -> API used to return ``price_cents: 0``
    with a correct ``offer`` -> the site rendered R$ 0,00 for all 94 products.
  - Baita: ``metadata.price_cents`` -> API used to return ``offer: None``.
  - Tock Fatal (v3): ``data.offer`` -> API used to omit ``price_cents`` entirely.
"""
from __future__ import annotations

from brain_contracts.pricing import Offer, normalize_offer, offer_to_price_cents


def _assert_invariant(offer: Offer) -> None:
    assert offer_to_price_cents(offer) == round(offer.amount * 100)


def test_v3_tock_canonical_data_offer_shape():
    data = {"offer": {"amount": 189.9, "currency": "BRL"}}

    offer = normalize_offer(data, metadata=None)

    assert offer == Offer(amount=189.9, currency="BRL")
    assert offer_to_price_cents(offer) == 18990
    _assert_invariant(offer)


def test_product_import_service_metadata_price_unit_dict_shape():
    """apps/control-plane/api/services/product_import_service.py:406-411 --
    ``unit`` is a **dict** here and must be unwrapped for amount/currency."""
    metadata = {"price": {"unit": {"amount": 169.0, "currency": "BRL"}}}

    offer = normalize_offer({}, metadata)

    assert offer == Offer(amount=169.0, currency="BRL")
    assert offer_to_price_cents(offer) == 16900
    _assert_invariant(offer)


def test_product_import_service_offer_node_top_level_metadata_shape():
    """apps/control-plane/api/services/product_import_service.py:551-579 --
    the offer NODE carries ``amount``/``currency`` directly on its own
    metadata, with no "price" key wrapping it at all."""
    metadata = {
        "is_offer": True,
        "amount": 49.9,
        "currency": "BRL",
        "price_cents": 4990,
        "price_label": "BRL 49.9",
    }

    offer = normalize_offer({}, metadata)

    assert offer == Offer(amount=49.9, currency="BRL")
    assert offer_to_price_cents(offer) == 4990
    _assert_invariant(offer)


def test_knowledge_rag_intake_metadata_price_unit_string_shape():
    """apps/control-plane/api/services/knowledge_rag_intake.py:111-137 --
    ``unit`` here is a **string** display label ("por kg"), never a dict, and
    must NOT be dict-unwrapped -- the amount stays at the top level."""
    metadata = {
        "price": {
            "amount": 32.5,
            "currency": "BRL",
            "unit": "por kg",
            "display": "R$ 32,50 por kg",
        }
    }

    offer = normalize_offer({}, metadata)

    assert offer == Offer(amount=32.5, currency="BRL")
    assert offer_to_price_cents(offer) == 3250
    _assert_invariant(offer)


def test_baita_metadata_price_cents_only_shape():
    """Baita: ``metadata.price_cents`` (integer cents), no dict price at all."""
    metadata = {"price_cents": 1200}

    offer = normalize_offer({}, metadata)

    assert offer == Offer(amount=12.0, currency="BRL")
    assert offer_to_price_cents(offer) == 1200
    _assert_invariant(offer)


def test_vz_lupas_metadata_price_amount_shape_never_renders_zero():
    """The exact production bug: metadata.price.amount must resolve to a
    non-zero price, not silently fall through to ``price_cents: 0``."""
    metadata = {"price": {"amount": 169.0, "currency": "BRL"}}

    offer = normalize_offer({}, metadata)

    assert offer is not None
    assert offer.amount == 169.0
    assert offer_to_price_cents(offer) != 0
    assert offer_to_price_cents(offer) == 16900


def test_unit_string_is_never_dict_unwrapped():
    """Regression for the single easiest trap: a string ``unit`` must never
    be treated as a dict to unwrap -- doing so would raise or silently drop
    the amount."""
    metadata = {"price": {"amount": 10.0, "currency": "BRL", "unit": "por kg"}}

    offer = normalize_offer({}, metadata)

    assert offer is not None
    assert offer.amount == 10.0


def test_dict_unit_is_unwrapped_for_amount_and_currency():
    metadata = {"price": {"unit": {"amount": 25.0, "currency": "USD"}}}

    offer = normalize_offer({}, metadata)

    assert offer == Offer(amount=25.0, currency="USD")


def test_no_price_source_returns_none():
    assert normalize_offer({}, {}) is None
    assert normalize_offer({}, None) is None


def test_data_offer_takes_priority_over_metadata_price():
    data = {"offer": {"amount": 1.0, "currency": "BRL"}}
    metadata = {"price": {"amount": 999.0, "currency": "BRL"}}

    offer = normalize_offer(data, metadata)

    assert offer.amount == 1.0


def test_dict_price_beats_price_cents_fallback():
    data = {"price_cents": 500}
    metadata = {"price": {"amount": 7.5, "currency": "BRL"}}

    offer = normalize_offer(data, metadata)

    assert offer.amount == 7.5


def test_offer_to_price_cents_returns_zero_for_none():
    assert offer_to_price_cents(None) == 0

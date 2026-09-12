"""The public storefront must show the same price the SDR already quotes.

Tock Fatal models price as a separate ``offer`` node (``about_product`` edge
to the ``product``), never on the product node's own ``data``. Before this
fix, ``_compiled_offer`` only looked at the product node itself, so every
Tock product rendered with ``offer: null`` on ``/vitrine`` even though the
graph had a perfectly good price two hops away.
"""
from __future__ import annotations

from brain_contracts.pricing import normalize_offer, offer_to_price_cents

from routes import menu


def test_compiled_offer_reads_from_the_linked_offer_node_when_given():
    product_node = {"id": "product:x", "node_type": "product", "data": {}}
    offer_node = {
        "id": "offer:x-varejo",
        "node_type": "offer",
        "data": {"price": {"amount": 99.9, "currency": "BRL"}, "channel": "varejo"},
    }

    assert menu._compiled_offer(product_node, offer_node) == {"amount": 99.9, "currency": "BRL"}


def test_compiled_offer_falls_back_to_the_product_nodes_own_data():
    product_node = {"id": "product:x", "node_type": "product", "data": {"price_cents": 4990}}

    assert menu._compiled_offer(product_node) == {"amount": 49.9, "currency": "BRL"}


def test_compiled_offer_returns_none_without_any_price_source():
    assert menu._compiled_offer({"id": "product:x", "node_type": "product", "data": {}}) is None


def test_compiled_offer_reads_metadata_price_cents_only():
    """vz-lupas / Baita shape: no ``data`` at all, only ``metadata.price_cents``."""
    product_node = {
        "id": "product:x",
        "node_type": "product",
        "data": {},
        "metadata": {"price_cents": 16900},
    }

    resolved = menu._compiled_offer(product_node)
    assert resolved == {"amount": 169.0, "currency": "BRL"}

    offer = normalize_offer(product_node.get("data") or {}, product_node.get("metadata") or {})
    assert offer_to_price_cents(offer) == 16900
    assert offer_to_price_cents(offer) == round(offer.amount * 100)


def test_compiled_offer_reads_data_offer_only():
    """v3/Tock canonical shape: ``data.offer`` with no ``price`` key at all."""
    product_node = {
        "id": "product:x",
        "node_type": "product",
        "data": {"offer": {"amount": 99.9, "currency": "BRL"}},
    }

    resolved = menu._compiled_offer(product_node)
    assert resolved == {"amount": 99.9, "currency": "BRL"}

    offer = normalize_offer(product_node.get("data") or {}, product_node.get("metadata") or {})
    assert offer_to_price_cents(offer) == 9990
    assert offer_to_price_cents(offer) == round(offer.amount * 100)

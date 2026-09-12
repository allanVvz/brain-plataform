"""Unit tests for the pure conversion logic in
``scripts/backfill_product_offer_metadata.py`` -- no production data or
database access required. Feeds the known legacy shapes through
``plan_node``/``compute_offer_patch`` and asserts the resulting
``metadata["offer"]`` plus the idempotency and value-preservation checks.
"""
from __future__ import annotations

from scripts.backfill_product_offer_metadata import compute_offer_patch, plan_node


def _product_node(node_id: str, *, data: dict | None = None, metadata: dict | None = None) -> dict:
    return {
        "id": node_id,
        "node_type": "product",
        "slug": f"slug-{node_id}",
        "title": f"Product {node_id}",
        "data": data or {},
        "metadata": metadata or {},
    }


def test_vz_lupas_metadata_price_amount_shape():
    node = _product_node("vz-1", metadata={"price": {"amount": 169.0, "currency": "BRL"}})

    patch = compute_offer_patch(node)

    assert patch == {"amount": 169.0, "currency": "BRL"}

    plan = plan_node(node)
    assert plan["action"] == "write"
    assert plan["before"] is None
    assert plan["after"] == {"amount": 169.0, "currency": "BRL"}
    assert plan["value_changed"] is False
    assert plan["price_cents_before"] == plan["price_cents_after"] == 16900


def test_baita_metadata_price_cents_shape():
    node = _product_node("baita-1", metadata={"price_cents": 1200})

    patch = compute_offer_patch(node)

    assert patch == {"amount": 12.0, "currency": "BRL"}

    plan = plan_node(node)
    assert plan["action"] == "write"
    assert plan["price_cents_before"] == plan["price_cents_after"] == 1200


def test_v3_tock_canonical_data_offer_shape_is_already_canonical_once_mirrored():
    node = _product_node(
        "tock-1",
        data={"offer": {"amount": 189.9, "currency": "BRL"}},
        metadata={"offer": {"amount": 189.9, "currency": "BRL"}},
    )

    plan = plan_node(node)

    assert plan["action"] == "noop_already_canonical"
    assert plan["value_changed"] is False


def test_product_import_service_metadata_price_unit_dict_shape():
    node = _product_node("import-1", metadata={"price": {"unit": {"amount": 25.0, "currency": "USD"}}})

    patch = compute_offer_patch(node)

    assert patch == {"amount": 25.0, "currency": "USD"}


def test_knowledge_rag_intake_metadata_price_unit_string_shape():
    node = _product_node(
        "rag-1",
        metadata={"price": {"amount": 32.5, "currency": "BRL", "unit": "por kg", "display": "R$ 32,50 por kg"}},
    )

    patch = compute_offer_patch(node)

    assert patch == {"amount": 32.5, "currency": "BRL"}


def test_no_resolvable_price_is_skipped():
    node = _product_node("empty-1")

    assert compute_offer_patch(node) is None
    plan = plan_node(node)
    assert plan["action"] == "skip_unresolved"
    assert plan["after"] is None


def test_idempotent_second_run_is_noop():
    node = _product_node("vz-2", metadata={"price": {"amount": 169.0, "currency": "BRL"}})

    first = plan_node(node)
    assert first["action"] == "write"

    # Simulate the write landing: metadata["offer"] now holds exactly what
    # the first run computed, legacy "price" key left untouched.
    node["metadata"] = {**node["metadata"], "offer": first["after"]}

    second = plan_node(node)
    assert second["action"] == "noop_already_canonical"
    assert second["before"] == second["after"] == {"amount": 169.0, "currency": "BRL"}


def test_channel_is_included_only_when_present():
    node = _product_node(
        "channel-1",
        metadata={"price": {"amount": 50.0, "currency": "BRL", "channel": "atacado"}},
    )

    patch = compute_offer_patch(node)

    assert patch == {"amount": 50.0, "currency": "BRL", "channel": "atacado"}

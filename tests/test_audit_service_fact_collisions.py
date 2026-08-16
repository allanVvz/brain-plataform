from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.audit_service_fact_collisions import find_collisions


def test_dry_run_finds_service_value_stored_in_non_service_field():
    facts = [{
        "id": "fact:1", "ledger_id": "ledger:1", "field_key": "objective",
        "owner_node_id": "persona:aurora", "status": "known",
        "value_json": "Vitrificação", "source_message_id": "message:1",
        "revision": 2,
    }]

    collisions = find_collisions(
        facts=facts,
        service_values={"vitrificacao": {"aurora-product-vitrification"}},
    )

    assert collisions == [{
        "fact_id": "fact:1", "ledger_id": "ledger:1",
        "field_key": "objective", "owner_node_id": "persona:aurora",
        "source_message_id": "message:1", "revision": 2,
        "matched_service_anchor_ids": ["aurora-product-vitrification"],
        "created_at": None,
    }]


def test_dry_run_ignores_real_service_fact_and_unrelated_value():
    facts = [
        {"field_key": "servico", "status": "known", "value_json": "Vitrificação"},
        {"field_key": "objective", "status": "known", "value_json": "continuar cuidando"},
    ]

    assert find_collisions(
        facts=facts,
        service_values={"vitrificacao": {"aurora-product-vitrification"}},
    ) == []

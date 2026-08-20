from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle


EXAMPLE = ROOT / "data" / "graph_bundles" / "examples" / "basic-commercial-sdr.json"
TOCK_EXAMPLE = ROOT / "data" / "graph_bundles" / "tock-fatal" / "sdr-qualification-v1.json"


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def load_tock_example() -> dict:
    return json.loads(TOCK_EXAMPLE.read_text(encoding="utf-8"))


def test_tock_sales_bundle_declares_generic_audience_selector():
    bundle = load_tock_example()
    document = graph_bundle.compile_bundle(bundle)

    assert graph_bundle.graph_compiler_v3.branch_selection_field_key(
        document["branch_contracts"], document["node_by_id"]["persona:tock-fatal"]
    ) == "purchase_profile"
    selector = next(
        field for field in document["common_contract"]["fields"]
        if field.get("branch_selection_field") is True
    )
    assert selector["key"] == "purchase_profile"
    assert document["branch_anchors"] == [
        "audience:tock-reseller", "audience:tock-retail"
    ]


def test_tock_sales_bundle_declares_terminal_qualification_copy():
    document = graph_bundle.compile_bundle(load_tock_example())

    for branch_id in document["branch_anchors"]:
        contract = document["branch_contracts"][branch_id]
        qualification = contract["conversation_policy"]["qualification"]
        assert qualification["summary_template"]
        assert qualification["confirmation_question"]
        assert qualification["completion_message"]
        assert qualification["correction_prompt"]
        assert qualification["incomplete_handoff_template"]
        assert contract["handoff_rules"] == [{
            "node_id": "rule:tock-safe-handoff",
            "condition": "qualification_complete",
            "text": "Perfeito. Vou encaminhar seu interesse para a equipe continuar o atendimento.",
        }]


def test_tock_sales_bundle_publishes_voice_tone_greetings_and_plain_labels():
    document = graph_bundle.compile_bundle(load_tock_example())
    node_by_id = document["node_by_id"]

    assert node_by_id["tone:tock-vitoria-voice"]["node_type"] == "tone"
    assert node_by_id["tone:tock-vitoria-clear-language"]["node_type"] == "tone"
    greeting = node_by_id["persona:tock-fatal"]["data"]["conversation_policy"][
        "intents"
    ]["greeting"]
    assert len(greeting["response_node_ids"]) == 6
    assert all(
        node_by_id[node_id]["node_type"] == "faq"
        and node_by_id[node_id]["data"]["role"] == "greeting_response"
        for node_id in greeting["response_node_ids"]
    )
    for branch_id in document["branch_anchors"]:
        contract = document["branch_contracts"][branch_id]
        assert contract["field_labels"]["purchase_profile"] == "tipo de compra"
        selector = next(
            field for field in contract["fields"]
            if field["key"] == "purchase_profile"
        )
        assert selector["validation"] == {
            "mode": "enum",
            "values": [
                {
                    "value": "uso-proprio-varejo",
                    "aliases": ["uso próprio", "pra mim", "varejo", "comprar para mim"],
                },
                {
                    "value": "atacado-revenda",
                    "aliases": ["revenda", "revender", "atacado", "minha loja", "empreender"],
                },
            ],
        }
        assert "tone:tock-vitoria-voice" in contract["closure_node_ids"]
        assert "tone:tock-vitoria-clear-language" in contract["closure_node_ids"]
        assert set(greeting["response_node_ids"]).issubset(contract["closure_node_ids"])


@pytest.mark.parametrize(
    ("copy_key", "invalid_value"),
    [
        (copy_key, invalid_value)
        for copy_key in graph_bundle.SALES_QUALIFICATION_COPY_KEYS
        for invalid_value in (None, "   ")
    ],
)
def test_sales_bundle_without_required_qualification_copy_is_blocked(
    copy_key: str,
    invalid_value: str | None,
):
    bundle = load_tock_example()
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    qualification = persona["data"]["conversation_policy"]["qualification"]
    if invalid_value is None:
        qualification.pop(copy_key)
    else:
        qualification[copy_key] = invalid_value

    expected_error = f"bundle_sales_qualification_copy_required:{copy_key}"
    with pytest.raises(graph_bundle.GraphBundleError) as exc_info:
        graph_bundle.compile_bundle(bundle)
    assert expected_error in exc_info.value.errors

    plan = graph_bundle.build_publication_plan(bundle)
    assert plan["disposition"] == "blocked"
    assert plan["publication_allowed"] is False
    assert expected_error in plan["validation_errors"]


def test_tock_bundle_is_ready_for_explicit_publication_approval():
    plan = graph_bundle.build_publication_plan(load_tock_example())

    assert plan["disposition"] == "awaiting_approval"
    assert plan["approval_scope"] == "publication_plan"
    assert plan["publication_allowed"] is True
    assert plan["validation_errors"] == []


def test_invalid_explicit_sales_selector_blocks_compilation():
    bundle = load_tock_example()
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    persona["data"]["conversation_policy"]["branch_selection"]["field_key"] = "missing"

    plan = graph_bundle.build_publication_plan(bundle)

    assert "branch_selection_field_invalid:missing" in plan["validation_errors"]


def test_basic_commercial_bundle_compiles_two_isolated_audience_branches(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    document = graph_bundle.compile_bundle(load_example())

    assert document["persona"]["slug"] == "example-commercial"
    assert document["branch_anchors"] == ["audience:reseller", "audience:retail"]
    retail = document["branch_contracts"]["audience:retail"]
    reseller = document["branch_contracts"]["audience:reseller"]
    assert retail["required_fields"] == ["need"]
    assert reseller["required_fields"] == ["resale_stage", "volume_interest"]
    assert "faq:reseller-stage" not in retail["closure_node_ids"]
    assert "faq:retail-need" not in reseller["closure_node_ids"]


def test_publication_plan_is_a_non_publishable_dry_run(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    plan = graph_bundle.build_publication_plan(load_example(), next_version=1)

    assert plan["disposition"] == "dry_run_complete"
    assert plan["publication_allowed"] is False
    assert plan["approval_scope"] == "dry_run_only"
    assert plan["draft_checksum"].startswith("sha256:")
    assert plan["runtime_checksum"].startswith("sha256:")
    assert plan["next_version"] == 1
    assert plan["nodes_added"] == 8
    assert plan["nodes_changed"] == 0
    assert plan["edges_added"] == 7
    assert plan["branches_affected"] == ["audience:reseller", "audience:retail"]
    assert plan["chunks_reused"] == 0
    assert plan["chunks_to_embed"] > 0
    assert plan["breaking_contract_changes"] == []
    assert plan["validation_errors"] == []


def test_second_plan_reuses_chunks_and_has_no_semantic_diff(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    bundle = load_example()
    current = graph_bundle.compile_bundle(bundle)
    plan = graph_bundle.build_publication_plan(
        bundle, current_document=current, next_version=2
    )

    assert plan["nodes_added"] == 0
    assert plan["nodes_changed"] == 0
    assert plan["nodes_removed"] == 0
    assert plan["edges_added"] == 0
    assert plan["edges_changed"] == 0
    assert plan["edges_removed"] == 0
    assert plan["branches_affected"] == []
    assert plan["chunks_reused"] > 0
    assert plan["chunks_to_embed"] == 0


def test_invalid_bundle_returns_blocked_plan_instead_of_publishing(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    bundle = load_example()
    bundle["edges"][0]["source"] = "node:missing"

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert plan["publication_allowed"] is False
    assert plan["runtime_checksum"] is None
    assert "bundle_edge_source_missing:edge:persona-brand:node:missing" in plan["validation_errors"]


def test_edge_only_change_marks_both_audience_branches_affected(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    bundle = load_example()
    current = graph_bundle.compile_bundle(bundle)
    bundle["edges"].append({
        "id": "edge:audience-reference",
        "source": "audience:retail",
        "target": "audience:reseller",
        "relation_type": "references",
    })

    plan = graph_bundle.build_publication_plan(bundle, current_document=current)

    assert plan["edges_added"] == 1
    assert plan["branches_affected"] == ["audience:reseller", "audience:retail"]


def test_embedding_profile_change_disables_chunk_reuse(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    bundle = load_example()
    previous_bundle = load_example()
    previous_bundle["metadata"]["embedding_profile"]["embedding_model"] = "different-model"
    current = graph_bundle.compile_bundle(previous_bundle)

    plan = graph_bundle.build_publication_plan(bundle, current_document=current)

    assert plan["chunks_reused"] == 0
    assert plan["chunks_to_embed"] > 0


def test_orphan_node_is_blocked_before_compilation(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    bundle = load_example()
    bundle["edges"] = [
        edge for edge in bundle["edges"]
        if edge["target"] != "faq:retail-need"
    ]

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert "bundle_primary_parent_missing:faq:retail-need" in plan["validation_errors"]


def test_missing_source_is_normalized_and_blocks_publication_plan(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    bundle = load_example()
    del bundle["nodes"][0]["data"]["source"]

    normalized = graph_bundle.normalize_bundle(bundle)

    persona = next(node for node in normalized["nodes"] if node["node_type"] == "persona")
    assert persona["data"]["source"] == "pending_source"
    plan = graph_bundle.build_publication_plan(bundle)
    assert plan["disposition"] == "blocked"
    assert "bundle_node_source_pending:persona:example-commercial" in plan["validation_errors"]


def test_pending_node_blocks_plan_instead_of_disappearing(monkeypatch):
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "openai")
    bundle = load_example()
    bundle["nodes"][1]["status"] = "pending_validation"

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert "bundle_node_not_publishable:brand:example-commercial:pending_validation" in plan["validation_errors"]


def test_bundle_embedding_profile_makes_runtime_checksum_environment_independent(monkeypatch):
    bundle = load_example()
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "local")
    local_checksum = graph_bundle.compile_bundle(bundle)["checksum"]
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "openai")
    openai_env_checksum = graph_bundle.compile_bundle(bundle)["checksum"]

    assert local_checksum == openai_env_checksum


def test_invalid_projection_identity_is_blocked(monkeypatch):
    bundle = load_example()
    bundle["nodes"][0]["projection_node_id"] = "not-a-uuid"

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert "bundle_projection_node_id_invalid:persona:example-commercial" in plan["validation_errors"]


def test_untrusted_baseline_is_blocked(monkeypatch):
    bundle = load_example()
    current = graph_bundle.compile_bundle(bundle)
    current["persona"]["slug"] = "other-persona"

    plan = graph_bundle.build_publication_plan(bundle, current_document=current)

    assert plan["disposition"] == "blocked"
    assert "baseline_persona_slug_mismatch" in plan["validation_errors"]
    assert "baseline_checksum_invalid" in plan["validation_errors"]


def test_empty_or_case_variant_pending_source_blocks_plan(monkeypatch):
    for source in ("", None, " PENDING_SOURCE "):
        bundle = load_example()
        bundle["nodes"][0]["data"]["source"] = source
        plan = graph_bundle.build_publication_plan(bundle)
        assert plan["disposition"] == "blocked"
        assert "bundle_node_source_pending:persona:example-commercial" in plan["validation_errors"]


def test_duplicate_logical_edge_is_blocked(monkeypatch):
    bundle = load_example()
    duplicate = dict(bundle["edges"][0])
    duplicate["id"] = "edge:duplicate-id"
    bundle["edges"].append(duplicate)

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert "bundle_duplicate_logical_edge:persona:example-commercial:brand:example-commercial:contains" in plan["validation_errors"]


def test_conflicting_node_and_data_status_is_blocked(monkeypatch):
    bundle = load_example()
    bundle["nodes"][0]["data"]["status"] = "pending_validation"

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert "bundle_node_status_conflict:persona:example-commercial:validated:pending_validation" in plan["validation_errors"]


def test_reparenting_is_a_breaking_structure_change(monkeypatch):
    bundle = load_example()
    bundle["nodes"].append({
        "id": "rule:example",
        "node_type": "rule",
        "slug": "example",
        "title": "Regra sintética",
        "summary": "Regra sem efeito comercial usada apenas no teste estrutural.",
        "status": "validated",
        "data": {"source": "synthetic_fixture", "status": "validated"},
    })
    bundle["edges"].append({
        "id": "edge:retail-rule",
        "source": "audience:retail",
        "target": "rule:example",
        "relation_type": "contains",
    })
    current = graph_bundle.compile_bundle(bundle)
    retail_rule = next(
        edge for edge in bundle["edges"] if edge["id"] == "edge:retail-rule"
    )
    retail_rule["source"] = "audience:reseller"

    plan = graph_bundle.build_publication_plan(bundle, current_document=current)

    assert "branch_structure_changed:audience:reseller" in plan["breaking_contract_changes"]
    assert "branch_structure_changed:audience:retail" in plan["breaking_contract_changes"]


def test_structurally_invalid_rechecksummed_baseline_is_blocked(monkeypatch):
    bundle = load_example()
    current = graph_bundle.compile_bundle(bundle)
    current["branch_memberships"]["audience:retail"]["node:missing"] = {}
    current_without_checksum = dict(current)
    current_without_checksum.pop("checksum")
    current["checksum"] = graph_bundle.graph_compiler_v3.canonical_checksum(
        current_without_checksum
    )

    plan = graph_bundle.build_publication_plan(bundle, current_document=current)

    assert plan["disposition"] == "blocked"
    assert "baseline_branch_membership_invalid:audience:retail" in plan["validation_errors"]

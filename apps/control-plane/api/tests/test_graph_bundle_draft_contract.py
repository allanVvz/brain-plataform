from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.graph_bundle_drafts import PatchGraphBundleDraftBody, PublishGraphBundleDraftBody
from services import graph_bundle, graph_bundle_draft_ops


CHECKSUM = "sha256:" + "a" * 64


def _bundle() -> dict:
    return {
        "bundle_version": "1.0",
        "persona": {"id": "4acb2739-127e-4143-acf5-f5c3ea1aaa98", "slug": "demo"},
        "metadata": {},
        "nodes": [
            {
                "id": "persona:demo", "node_type": "persona", "slug": "demo",
                "title": "Demo", "summary": "Persona", "status": "validated",
                "data": {"source": "operator"},
            },
            {
                "id": "product:item", "node_type": "product", "slug": "item",
                "title": "Item", "summary": "Produto", "status": "validated",
                "data": {"source": "catalog"},
            },
            {
                "id": "faq:item", "node_type": "faq", "slug": "faq-item",
                "title": "Pergunta", "summary": "Resposta", "status": "pending_validation",
                "data": {
                    "source": "catalog", "question": "Pergunta?", "answer": "Resposta.",
                    "source_node_id": "product:item", "source_node_type": "product",
                    "branch_path": ["persona:demo", "product:item", "faq:item"],
                },
            },
            {
                "id": "embedded:demo", "node_type": "embedded", "slug": "embedded",
                "title": "Embedded", "summary": "Destino RAG", "status": "validated",
                "data": {"source": "system"},
            },
            {
                "id": "gallery:demo", "node_type": "gallery", "slug": "gallery",
                "title": "Gallery", "summary": "Destino visual", "status": "validated",
                "data": {"source": "system"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "persona:demo", "target": "product:item", "relation_type": "contains"},
            {"id": "e2", "source": "product:item", "target": "faq:item", "relation_type": "contains"},
        ],
    }


def _request(*operations: dict) -> PatchGraphBundleDraftBody:
    return PatchGraphBundleDraftBody.model_validate({
        "expected_revision": 1,
        "expected_draft_checksum": CHECKSUM,
        "reason": "Revisao humana",
        "source": {"surface": "graph"},
        "operations": list(operations),
        "idempotency_key": "draft-test-key",
    })


def test_patch_contract_requires_cas_and_idempotency_key():
    with pytest.raises(ValidationError):
        PatchGraphBundleDraftBody.model_validate({
            "reason": "Revisao humana",
            "source": {"surface": "graph"},
            "operations": [{"op": "archive_node", "node_id": "product:item"}],
        })


def test_publish_requires_durable_plan_and_validation_but_not_wa_validator():
    body = PublishGraphBundleDraftBody.model_validate({
        "expected_revision": 2,
        "expected_draft_checksum": CHECKSUM,
        "plan_ref": "plan:ledger-event-id",
        "validation_ref": "validation:ledger-event-id",
        "approved_runtime_checksum": CHECKSUM,
        "confirmation": True,
        "reason": "Publicacao revisada",
        "idempotency_key": "publish-test-key",
    })
    assert not hasattr(body, "test_run_id")


def test_draft_route_does_not_expose_fake_prepublication_wa_test():
    source = (API_ROOT / "routes/graph_bundles.py").read_text(encoding="utf-8")
    assert '@router.post("/drafts/{draft_ref}/test")' not in source
    assert 'f"test:' not in source


def test_update_node_contract_rejects_stable_identity_changes():
    with pytest.raises(ValidationError, match="immutable node fields"):
        _request({
            "op": "update_node", "node_id": "product:item",
            "patch": {"projection_node_id": "another-id"},
        })


def test_add_node_and_edge_contracts_reject_incomplete_shapes():
    with pytest.raises(ValidationError):
        _request({"op": "add_node", "node": {"id": "faq:incompleta"}})
    with pytest.raises(ValidationError):
        _request({"op": "add_edge", "edge": {"id": "edge:incompleta"}})


def test_pending_faq_has_no_embedded_projection():
    bundle = graph_bundle_draft_ops.canonicalize_draft(_bundle())
    assert not any(
        edge.get("source") == "faq:item"
        and edge.get("relation_type") == "publishes_to"
        for edge in bundle["edges"]
    )


def test_approve_faq_creates_exactly_one_embedded_projection_and_is_idempotent():
    request = _request({"op": "approve_faq", "node_id": "faq:item"})
    approved, _ = graph_bundle_draft_ops.apply_operations(_bundle(), request.operations)
    approved_again, _ = graph_bundle_draft_ops.apply_operations(approved, request.operations)
    projections = [
        edge for edge in approved_again["edges"]
        if edge.get("source") == "faq:item"
        and edge.get("target") == "embedded:demo"
        and edge.get("relation_type") == "publishes_to"
    ]
    faq = next(node for node in approved_again["nodes"] if node["id"] == "faq:item")
    assert faq["status"] == "validated"
    assert len(projections) == 1


def test_approve_faq_requires_verified_source():
    bundle = _bundle()
    faq = next(node for node in bundle["nodes"] if node["id"] == "faq:item")
    faq["data"]["source"] = "pending_source"
    request = _request({"op": "approve_faq", "node_id": "faq:item"})
    with pytest.raises(graph_bundle_draft_ops.GraphBundleDraftOperationError, match="source_required"):
        graph_bundle_draft_ops.apply_operations(bundle, request.operations)


def test_protected_nodes_cannot_be_archived():
    request = _request({"op": "archive_node", "node_id": "persona:demo"})
    with pytest.raises(graph_bundle_draft_ops.GraphBundleDraftOperationError, match="protected_node"):
        graph_bundle_draft_ops.apply_operations(_bundle(), request.operations)


def test_protected_nodes_cannot_be_archived_through_generic_update():
    request = _request({
        "op": "update_node", "node_id": "embedded:demo",
        "patch": {"status": "archived"},
    })
    with pytest.raises(graph_bundle_draft_ops.GraphBundleDraftOperationError, match="protected_node"):
        graph_bundle_draft_ops.apply_operations(_bundle(), request.operations)


def test_bulk_faq_proposal_is_pending_and_impact_tracks_its_source():
    request = _request({
        "op": "add_faq_proposal",
        "node_id": "faq:item-price",
        "slug": "item-price",
        "question": "Quanto custa?",
        "answer": "Consulte o valor publicado.",
        "source": "catalog",
        "source_node_id": "product:item",
        "source_node_type": "product",
        "branch_path": ["persona:demo", "product:item"],
        "question_aliases": ["qual o valor"],
        "generator": "faq-generator-v1",
        "generation_batch_id": "batch-1",
    })
    proposed, _ = graph_bundle_draft_ops.apply_operations(_bundle(), request.operations)
    faq = next(node for node in proposed["nodes"] if node["id"] == "faq:item-price")
    assert faq["status"] == "pending_validation"
    assert not any(
        edge["source"] == faq["id"] and edge["relation_type"] == "publishes_to"
        for edge in proposed["edges"]
    )
    impact = graph_bundle_draft_ops.faq_impact(proposed, ["product:item"])
    assert impact["affected_faq_node_ids"] == ["faq:item", "faq:item-price"]


def test_draft_plan_excludes_pending_faq_but_preserves_authoring_checksum():
    bundle = _bundle()
    bundle["metadata"]["embedding_profile"] = {
        "embedding_provider": "local",
        "embedding_model": "test-model",
        "embedding_dimension": 1536,
    }
    plan = graph_bundle.build_draft_publication_plan(bundle)
    assert plan["draft_checksum"] == graph_bundle_draft_ops.draft_checksum(bundle)
    assert "faq:item" in plan["excluded_node_ids"]
    assert "faq:item" not in (plan.get("candidate_document") or {}).get("node_by_id", {})


def test_reject_faq_removes_only_its_embedded_projection():
    approved, _ = graph_bundle_draft_ops.apply_operations(
        _bundle(), _request({"op": "approve_faq", "node_id": "faq:item"}).operations,
    )
    rejected, _ = graph_bundle_draft_ops.apply_operations(
        approved, _request({"op": "reject_faq", "node_id": "faq:item"}).operations,
    )
    faq = next(node for node in rejected["nodes"] if node["id"] == "faq:item")
    assert faq["status"] == "rejected"
    assert not any(
        edge.get("source") == "faq:item"
        and edge.get("relation_type") == "publishes_to"
        for edge in rejected["edges"]
    )


def test_draft_checksum_is_stable_across_node_and_edge_order():
    left = _bundle()
    right = _bundle()
    right["nodes"].reverse()
    right["edges"].reverse()
    assert graph_bundle_draft_ops.draft_checksum(left) == graph_bundle_draft_ops.draft_checksum(right)


def test_draft_rejects_duplicate_ids_and_orphan_edges_before_checksum():
    duplicated = _bundle()
    duplicated["nodes"].append(dict(duplicated["nodes"][1]))
    with pytest.raises(
        graph_bundle_draft_ops.GraphBundleDraftOperationError,
        match="duplicate_node_id",
    ):
        graph_bundle_draft_ops.draft_checksum(duplicated)

    orphaned = _bundle()
    orphaned["edges"].append({
        "id": "e3", "source": "missing", "target": "faq:item",
        "relation_type": "contains",
    })
    with pytest.raises(
        graph_bundle_draft_ops.GraphBundleDraftOperationError,
        match="edge_source_missing",
    ):
        graph_bundle_draft_ops.draft_checksum(orphaned)


def test_migration_134_uses_text_ledger_ids_and_control_plane_grants():
    sql = (REPO_ROOT / "supabase/migrations/134_graph_bundle_draft_ledger.sql").read_text(
        encoding="utf-8"
    )
    assert "entity_id = p_draft_ref::text" in sql
    assert "activate_graph_bundle_draft_publication" in sql
    assert "TO service_role, brain_control_plane" in sql


def test_atomic_patch_requires_matching_revision_and_checksum():
    bundle = _bundle()
    checksum = graph_bundle_draft_ops.draft_checksum(bundle)
    request = _request({
        "op": "update_node", "node_id": "product:item",
        "patch": {"title": "Item revisado"},
    })
    updated, summary = graph_bundle_draft_ops.apply_operations_with_cas(
        bundle,
        actual_revision=1,
        expected_revision=1,
        expected_checksum=checksum,
        operations=request.operations,
    )
    assert summary["revision"] == 2
    assert summary["previous_checksum"] == checksum
    assert summary["draft_checksum"] != checksum
    assert next(node for node in updated["nodes"] if node["id"] == "product:item")[
        "title"
    ] == "Item revisado"

    with pytest.raises(graph_bundle_draft_ops.GraphBundleDraftConflict) as stale:
        graph_bundle_draft_ops.apply_operations_with_cas(
            updated,
            actual_revision=2,
            expected_revision=1,
            expected_checksum=checksum,
            operations=request.operations,
        )
    assert stale.value.actual_revision == 2
    assert stale.value.actual_checksum == summary["draft_checksum"]


def test_editing_fact_invalidates_approved_derived_faq_and_rag_projection():
    approved, _ = graph_bundle_draft_ops.apply_operations(
        _bundle(), _request({"op": "approve_faq", "node_id": "faq:item"}).operations,
    )
    updated, summary = graph_bundle_draft_ops.apply_operations(
        approved,
        _request({
            "op": "update_node", "node_id": "product:item",
            "patch": {"summary": "Produto com fato revisado"},
        }).operations,
    )
    faq = next(node for node in updated["nodes"] if node["id"] == "faq:item")
    assert faq["status"] == "pending_validation"
    assert summary["faq_nodes_requiring_review"] == ["faq:item"]
    assert not any(
        edge.get("source") == "faq:item"
        and edge.get("relation_type") == "publishes_to"
        for edge in updated["edges"]
    )

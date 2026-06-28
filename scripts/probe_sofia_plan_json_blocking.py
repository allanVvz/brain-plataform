"""BRA-82 blocking-case probe.

Exercises the three-bucket severity validator (cycle, orphan, edge_inverted,
product_above_product_group, embed_without_approved_faq, persistence_failure,
critical_duplication) and the patch-apply persist-rejection boundary against
the live qa_contract router via TestClient.

Run:
    python scripts/probe_sofia_plan_json_blocking.py
Artifact:
    test-artifacts/qa/sofia-plan-json-blocking-probe-<UTC>.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from routes import qa_contract  # noqa: E402
from services import sofia_orchestrator  # noqa: E402


BLOCKING_MARKERS = [
    ("cycle", "cycle detected"),
    ("orphan", "orphan node detected"),
    ("edge_inverted", "edge inverted (child -> parent)"),
    ("product_above_product_group", "product placed above product_group"),
    ("embed_without_approved_faq", "embed referenced without approved FAQ"),
    ("persistence_failure", "supabase persist failed"),
    ("critical_duplication", "duplicate canonical slug under same parent"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_app() -> FastAPI:
    app = FastAPI(title="bra82-blocking-probe")
    app.include_router(qa_contract.router)
    return app


def _stub_dependencies() -> None:
    qa_contract._require_non_production = lambda: None  # type: ignore[assignment]
    qa_contract.auth_service.assert_persona_access = (  # type: ignore[assignment]
        lambda request, persona_id=None, persona_slug=None: True
    )
    qa_contract.supabase_client.get_persona = (  # type: ignore[assignment]
        lambda slug: {"id": "p1", "slug": slug or "vz-lupas"}
    )
    qa_contract.supabase_client.get_persona_by_id = (  # type: ignore[assignment]
        lambda pid: {"id": pid, "slug": "vz-lupas"}
    )
    qa_contract.supabase_client.ensure_persona_knowledge_node = (  # type: ignore[assignment]
        lambda _pid: {"id": "persona-1", "node_type": "persona", "slug": "self"}
    )

    seeded_product_group = {
        "id": "id-product-group-foo",
        "node_type": "product_group",
        "slug": "grupo-foo",
        "status": "active",
    }
    seeded_product = {
        "id": "id-product-foo",
        "node_type": "product",
        "slug": "produto-foo",
        "status": "active",
    }
    qa_contract.supabase_client.list_knowledge_nodes_by_type = (  # type: ignore[assignment]
        lambda *args, **kwargs: [seeded_product_group, seeded_product]
    )
    qa_contract.supabase_client.upsert_knowledge_node = (  # type: ignore[assignment]
        lambda payload: {
            "id": f"id-{payload.get('slug', 'node')}",
            "node_type": payload["node_type"],
            "slug": payload["slug"],
            "status": payload.get("status", "active"),
            "metadata": payload.get("metadata", {}),
        }
    )
    qa_contract.supabase_client.upsert_knowledge_edge = (  # type: ignore[assignment]
        lambda **kwargs: {"id": "edge-1", **kwargs}
    )
    qa_contract.supabase_client.insert_event = (  # type: ignore[assignment]
        lambda payload, source=None: {"ok": True}
    )


def main() -> None:
    _stub_dependencies()
    app = _mk_app()
    client = TestClient(app)
    session_id = "probe-blocking-01"
    persona_slug = "vz-lupas"

    report: dict = {
        "issue": "BRA-82",
        "generated_at": _now(),
        "session_id": session_id,
        "persona_slug": persona_slug,
        "objective": "Three-bucket severity validator + patch-apply/persist rejection.",
        "frozen_contract": "paperclip/docs/architecture/sofia-plan-json-contract-frozen-decision-2026-05-29.md",
        "steps": [],
        "assertions": {},
    }

    # 0) Reset orchestrator memory so probe starts clean.
    sofia_orchestrator._SESSION_MEMORY.clear()  # type: ignore[attr-defined]

    # 1) Acceptance #1 — product creation lands in pending, never blocking.
    r_create_product = client.patch(
        "/sofia/plan-json",
        json={
            "session_id": session_id,
            "persona_slug": persona_slug,
            "command": "crie um produto teste",
            "patch": {},
        },
    )
    body_create_product = r_create_product.json()
    val_after_product = body_create_product.get("plan_json", {}).get("validation", {})
    report["steps"].append(
        {
            "step": "acceptance_1_product_create_is_pending_not_blocking",
            "status": r_create_product.status_code,
            "validation": val_after_product,
        }
    )

    # 2) Acceptance #2a — each blocking marker individually flips is_valid=false.
    marker_results: list[dict] = []
    for marker, message in BLOCKING_MARKERS:
        marker_session = f"{session_id}-{marker}"
        sofia_orchestrator._SESSION_MEMORY.pop(marker_session, None)  # type: ignore[attr-defined]
        r_marker = client.patch(
            "/sofia/plan-json",
            json={
                "session_id": marker_session,
                "persona_slug": persona_slug,
                "patch": {
                    "graph_patch_queue": [{"marker": marker, "message": message}],
                },
            },
        )
        body_marker = r_marker.json()
        validation = body_marker.get("plan_json", {}).get("validation", {})
        marker_results.append(
            {
                "marker": marker,
                "expected_code": marker.upper(),
                "is_valid": validation.get("is_valid"),
                "blocking_codes": [
                    str(item.get("code"))
                    for item in (validation.get("blocking") or [])
                ],
                "suggestions_codes": [
                    str(item.get("code"))
                    for item in (validation.get("suggestions") or [])
                ],
                "pending_codes": [
                    str(item.get("code"))
                    for item in (validation.get("pending") or [])
                ],
            }
        )
    report["steps"].append(
        {
            "step": "acceptance_2a_all_seven_blocking_markers_trigger_validation_blocking",
            "marker_results": marker_results,
        }
    )

    # 3) Acceptance #2b — patch-apply path rejects persistence for inverted edge.
    inverted_edge_session = "probe-blocking-inverted-edge"
    sofia_orchestrator._SESSION_MEMORY.pop(inverted_edge_session, None)  # type: ignore[attr-defined]
    inverted_patch = {
        "nodes_upsert": [],
        "nodes_delete": [],
        "edges_upsert": [
            {
                # product -> product_group is inverted (canonical: product_group -> product).
                "source_ref": "slug:produto-foo",
                "target_ref": "slug:grupo-foo",
                "relation_type": "product_group_has_product",
            }
        ],
        "edges_delete": [],
    }
    r_inverted = client.post(
        "/sofia/graph-command",
        json={
            "persona_slug": persona_slug,
            "command": "aplique este patch invertido",
            "context": {
                "session_id": inverted_edge_session,
                "client_action": "structured_intent",
                "active_persona_slug": persona_slug,
                "graph_patch": inverted_patch,
                "selected_node_ids": [],
            },
        },
    )
    body_inverted = r_inverted.json()
    report["steps"].append(
        {
            "step": "acceptance_2b_patch_apply_rejects_inverted_edge",
            "status": r_inverted.status_code,
            "body": body_inverted,
        }
    )

    # 4) Acceptance #2c — patch-apply rejects product placed above product_group.
    product_above_session = "probe-blocking-product-above-pg"
    sofia_orchestrator._SESSION_MEMORY.pop(product_above_session, None)  # type: ignore[attr-defined]
    product_above_patch = {
        "nodes_upsert": [
            {
                "node_type": "product_group",
                "slug": "grupo-novo",
                "title": "Grupo Novo",
                "summary": "",
            },
            {
                "node_type": "product",
                "slug": "produto-novo",
                "title": "Produto Novo",
                "summary": "",
                "metadata": {"source_url": "https://example.com/p"},
            },
        ],
        "nodes_delete": [],
        "edges_upsert": [
            {
                # product -> product_group is forbidden via product_group_has_product
                # because product is the source instead of target.
                "source_ref": "slug:produto-novo",
                "target_ref": "slug:grupo-novo",
                "relation_type": "product_group_has_product",
            }
        ],
        "edges_delete": [],
    }
    r_product_above = client.post(
        "/sofia/graph-command",
        json={
            "persona_slug": persona_slug,
            "command": "aplique product-above-product_group",
            "context": {
                "session_id": product_above_session,
                "client_action": "structured_intent",
                "active_persona_slug": persona_slug,
                "graph_patch": product_above_patch,
                "selected_node_ids": [],
            },
        },
    )
    body_product_above = r_product_above.json()
    report["steps"].append(
        {
            "step": "acceptance_2c_patch_apply_rejects_product_above_product_group",
            "status": r_product_above.status_code,
            "body": body_product_above,
        }
    )

    # 5) needs_clarification short-circuits persist (no Supabase calls).
    clarify_session = "probe-blocking-needs-clarification"
    sofia_orchestrator._SESSION_MEMORY.pop(clarify_session, None)  # type: ignore[attr-defined]
    r_clarify = client.post(
        "/sofia/graph-command",
        json={
            "persona_slug": persona_slug,
            "command": "faca alguma coisa indefinida no grafo",
            "context": {
                "session_id": clarify_session,
                "client_action": "natural_language",
                "active_persona_slug": persona_slug,
                "selected_node_ids": [],
            },
        },
    )
    body_clarify = r_clarify.json()
    report["steps"].append(
        {
            "step": "acceptance_needs_clarification_short_circuits_persist",
            "status": r_clarify.status_code,
            "persisted": body_clarify.get("persisted"),
            "needs_clarification": body_clarify.get("needs_clarification"),
            "graph_patch": body_clarify.get("graph_patch"),
            "validation_buckets": body_clarify.get("plan_json", {}).get("validation"),
        }
    )

    # 6) FAQ/Rule must stay as suggestions, never blocking.
    suggestions_session = "probe-blocking-suggestions"
    sofia_orchestrator._SESSION_MEMORY.pop(suggestions_session, None)  # type: ignore[attr-defined]
    r_suggestions = client.get(
        "/sofia/plan-json",
        params={"session_id": suggestions_session, "persona_slug": persona_slug},
    )
    body_suggestions = r_suggestions.json()
    val_suggestions = body_suggestions.get("plan_json", {}).get("validation", {})
    report["steps"].append(
        {
            "step": "acceptance_faq_rule_are_suggestions_not_blocking",
            "status": r_suggestions.status_code,
            "validation": val_suggestions,
        }
    )

    # Aggregate assertions for QA gate.
    expected_codes = {marker.upper() for marker, _ in BLOCKING_MARKERS}
    observed_codes_per_marker = {
        item["marker"].upper(): set(item["blocking_codes"]) for item in marker_results
    }
    all_seven_markers_blocking = all(
        item["expected_code"] in observed_codes_per_marker.get(item["expected_code"], set())
        and item["is_valid"] is False
        for item in marker_results
    )
    inverted_rejected = r_inverted.status_code == 422 and "violations" in (
        body_inverted.get("detail", {}) if isinstance(body_inverted.get("detail"), dict) else {}
    )
    product_above_rejected = r_product_above.status_code == 422 and "violations" in (
        body_product_above.get("detail", {}) if isinstance(body_product_above.get("detail"), dict) else {}
    )
    suggestions_no_blocking = (
        any(x.get("code") == "FAQ_RECOMMENDED" for x in (val_suggestions.get("suggestions") or []))
        and any(x.get("code") == "RULE_RECOMMENDED" for x in (val_suggestions.get("suggestions") or []))
        and len(val_suggestions.get("blocking") or []) == 0
    )
    product_create_pending_only = (
        bool(val_after_product.get("is_valid"))
        and any(
            x.get("code") == "MISSING_PARENT"
            for x in (val_after_product.get("pending") or [])
        )
        and len(val_after_product.get("blocking") or []) == 0
    )
    needs_clarification_short_circuit = (
        r_clarify.status_code == 200
        and body_clarify.get("persisted") is False
        and body_clarify.get("needs_clarification") is True
        and body_clarify.get("graph_patch") is None
    )

    report["assertions"] = {
        "acceptance_1_product_create_pending_not_blocking": product_create_pending_only,
        "acceptance_2a_all_seven_blocking_markers_recognised": all_seven_markers_blocking,
        "acceptance_2b_inverted_edge_persist_rejected_422": inverted_rejected,
        "acceptance_2c_product_above_product_group_persist_rejected_422": product_above_rejected,
        "needs_clarification_short_circuits_persist": needs_clarification_short_circuit,
        "faq_rule_are_suggestions_not_blocking": suggestions_no_blocking,
        "expected_blocking_codes": sorted(expected_codes),
    }

    out_dir = Path("test-artifacts/qa")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        out_dir
        / f"sofia-plan-json-blocking-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()

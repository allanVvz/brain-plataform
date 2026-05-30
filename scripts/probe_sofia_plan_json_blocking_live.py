"""BRA-82 blocking-case probe — live :8001 variant.

Hits the running QA api at http://127.0.0.1:8001 (start with
`python scripts/start_api_qa.py`). Mirrors the TestClient probe but exercises
real Supabase-backed session storage via the QA admin token.

Run:
    python scripts/probe_sofia_plan_json_blocking_live.py
Artifact:
    test-artifacts/qa/sofia-plan-json-blocking-live-probe-<UTC>.json
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "env.qa.yaml"
BASE_URL = os.getenv("BRA82_PROBE_BASE_URL", "http://127.0.0.1:8001")


BLOCKING_MARKERS = [
    ("cycle", "cycle detected"),
    ("orphan", "orphan node detected"),
    ("edge_inverted", "edge inverted (child -> parent)"),
    ("product_above_product_group", "product placed above product_group"),
    ("embed_without_approved_faq", "embed referenced without approved FAQ"),
    ("persistence_failure", "supabase persist failed"),
    ("critical_duplication", "duplicate canonical slug under same parent"),
]


def _load_admin_token() -> str:
    if ENV_FILE.exists():
        with ENV_FILE.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        token = cfg.get("AI_BRAIN_ADMIN_TEST_TOKEN") or cfg.get("AI_BRAIN_ADMIN_TOKEN")
        if token:
            return str(token)
    fallback = os.getenv("AI_BRAIN_ADMIN_TEST_TOKEN") or os.getenv("AI_BRAIN_ADMIN_TOKEN")
    if not fallback:
        sys.exit("Missing AI_BRAIN_ADMIN_TEST_TOKEN in env.qa.yaml or environment.")
    return fallback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    token = _load_admin_token()
    session_prefix = f"bra82-live-{uuid.uuid4().hex[:8]}"
    persona_slug = "vz-lupas"
    headers = {
        "X-AI-BRAIN-ADMIN-TOKEN": token,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    def get(path: str, params: dict | None = None) -> requests.Response:
        return requests.get(f"{BASE_URL}{path}", headers=headers, params=params or {}, timeout=15)

    def patch(path: str, body: dict) -> requests.Response:
        return requests.patch(f"{BASE_URL}{path}", headers=headers, json=body, timeout=20)

    def post(path: str, body: dict) -> requests.Response:
        return requests.post(f"{BASE_URL}{path}", headers=headers, json=body, timeout=20)

    report: dict = {
        "issue": "BRA-82",
        "generated_at": _now(),
        "base_url": BASE_URL,
        "session_prefix": session_prefix,
        "persona_slug": persona_slug,
        "objective": "Three-bucket severity validator + patch-apply/persist rejection (live :8001).",
        "frozen_contract": "paperclip/docs/architecture/sofia-plan-json-contract-frozen-decision-2026-05-29.md",
        "steps": [],
        "assertions": {},
    }

    # 1) Acceptance #1 — product creation lands in pending, never blocking.
    sid_product = f"{session_prefix}-product"
    r_create_product = patch(
        "/sofia/plan-json",
        {
            "session_id": sid_product,
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
        sid_marker = f"{session_prefix}-{marker}"
        r_marker = patch(
            "/sofia/plan-json",
            {
                "session_id": sid_marker,
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
            }
        )
    report["steps"].append(
        {
            "step": "acceptance_2a_all_seven_blocking_markers_trigger_validation_blocking",
            "marker_results": marker_results,
        }
    )

    # 3) Acceptance #2b — patch-apply rejects inverted edge (product -> product_group).
    sid_inverted = f"{session_prefix}-inverted"
    inverted_patch = {
        "nodes_upsert": [
            {
                "node_type": "product_group",
                "slug": f"grupo-{session_prefix}",
                "title": "Grupo Probe Live",
                "summary": "BRA-82 probe — product_group",
            },
            {
                "node_type": "product",
                "slug": f"produto-{session_prefix}",
                "title": "Produto Probe Live",
                "summary": "BRA-82 probe — product",
                "metadata": {"source_url": "https://example.com/bra82-live"},
            },
        ],
        "nodes_delete": [],
        "edges_upsert": [
            {
                "source_ref": f"slug:produto-{session_prefix}",
                "target_ref": f"slug:grupo-{session_prefix}",
                "relation_type": "product_group_has_product",
            }
        ],
        "edges_delete": [],
    }
    r_inverted = post(
        "/sofia/graph-command",
        {
            "persona_slug": persona_slug,
            "command": "aplique patch invertido para teste BRA-82",
            "context": {
                "session_id": sid_inverted,
                "client_action": "structured_intent",
                "active_persona_slug": persona_slug,
                "graph_patch": inverted_patch,
                "selected_node_ids": [],
            },
        },
    )
    try:
        body_inverted = r_inverted.json()
    except ValueError:
        body_inverted = {"raw": r_inverted.text}
    report["steps"].append(
        {
            "step": "acceptance_2b_patch_apply_rejects_inverted_edge",
            "status": r_inverted.status_code,
            "body": body_inverted,
        }
    )

    # 4) Acceptance #2c — needs_clarification short-circuits persist.
    sid_clarify = f"{session_prefix}-clarify"
    r_clarify = post(
        "/sofia/graph-command",
        {
            "persona_slug": persona_slug,
            "command": "faca uma coisa indefinida no grafo BRA-82",
            "context": {
                "session_id": sid_clarify,
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
        }
    )

    # 5) GET refresh same session — confirm Supabase-backed plan_json survives.
    r_refresh = get(
        "/sofia/plan-json",
        params={"session_id": sid_product, "persona_slug": persona_slug},
    )
    body_refresh = r_refresh.json()
    refresh_products = (
        body_refresh.get("plan_json", {}).get("plan", {}).get("product", [])
    )
    report["steps"].append(
        {
            "step": "session_refetch_preserves_product",
            "status": r_refresh.status_code,
            "product_count": len(refresh_products),
        }
    )

    # 6) Acceptance #3 — refetch top-down semantic_tree after persisted patch.
    # Build a valid product_group -> product patch (canonical direction). Avoid
    # FAQ approval requirement by only persisting product_group + product under
    # persona:self -> brand (handled by reparent_brand on persona-only edges via
    # canonical_chain checks).
    canonical_session = f"{session_prefix}-canonical"
    canonical_patch = {
        "nodes_upsert": [
            {
                "node_type": "brand",
                "slug": f"brand-{session_prefix}",
                "title": "Brand BRA82 Live",
                "summary": "BRA-82 canonical brand",
            }
        ],
        "nodes_delete": [],
        "edges_upsert": [
            {
                "source_ref": "persona:self",
                "target_ref": f"slug:brand-{session_prefix}",
                "relation_type": "persona_has_brand",
            }
        ],
        "edges_delete": [],
    }
    r_canonical = post(
        "/sofia/graph-command",
        {
            "persona_slug": persona_slug,
            "command": "persista brand canonica BRA-82",
            "context": {
                "session_id": canonical_session,
                "client_action": "structured_intent",
                "active_persona_slug": persona_slug,
                "graph_patch": canonical_patch,
                "selected_node_ids": [],
            },
        },
    )
    try:
        body_canonical = r_canonical.json()
    except ValueError:
        body_canonical = {"raw": r_canonical.text}
    report["steps"].append(
        {
            "step": "acceptance_3a_persisted_canonical_patch",
            "status": r_canonical.status_code,
            "persisted": (body_canonical.get("persisted") if isinstance(body_canonical, dict) else None),
            "sofia_message": (body_canonical.get("sofia_message") if isinstance(body_canonical, dict) else None),
        }
    )

    # Semantic_tree refetch — confirms the canonical graph re-fetch contract.
    r_graph_data = get(
        "/knowledge/graph-data",
        params={"persona_slug": persona_slug, "mode": "semantic_tree"},
    )
    try:
        body_graph_data = r_graph_data.json()
    except ValueError:
        body_graph_data = {"raw": r_graph_data.text}
    graph_root_present = bool(
        isinstance(body_graph_data, dict)
        and (
            body_graph_data.get("nodes")
            or body_graph_data.get("tree")
            or body_graph_data.get("graph")
        )
    )
    report["steps"].append(
        {
            "step": "acceptance_3b_semantic_tree_refetch",
            "status": r_graph_data.status_code,
            "root_keys": list(body_graph_data.keys()) if isinstance(body_graph_data, dict) else [],
            "graph_payload_present": graph_root_present,
        }
    )

    # Aggregate assertions
    all_seven_markers_blocking = all(
        item["expected_code"] in set(item["blocking_codes"]) and item["is_valid"] is False
        for item in marker_results
    )
    inverted_rejected = r_inverted.status_code == 422
    needs_clarification_short_circuit = (
        r_clarify.status_code == 200
        and body_clarify.get("persisted") is False
        and body_clarify.get("needs_clarification") is True
        and body_clarify.get("graph_patch") is None
    )
    product_create_pending_only = (
        bool(val_after_product.get("is_valid"))
        and any(
            x.get("code") == "MISSING_PARENT"
            for x in (val_after_product.get("pending") or [])
        )
        and len(val_after_product.get("blocking") or []) == 0
    )

    report["assertions"] = {
        "acceptance_1_product_create_pending_not_blocking": product_create_pending_only,
        "acceptance_2a_all_seven_blocking_markers_recognised": all_seven_markers_blocking,
        "acceptance_2b_inverted_edge_persist_rejected_422": inverted_rejected,
        "needs_clarification_short_circuits_persist": needs_clarification_short_circuit,
        "session_refetch_preserves_product": len(refresh_products) >= 1,
        "acceptance_3_semantic_tree_refetch_responds_200": r_graph_data.status_code == 200,
    }

    out_dir = ROOT / "test-artifacts" / "qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        out_dir
        / f"sofia-plan-json-blocking-live-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()

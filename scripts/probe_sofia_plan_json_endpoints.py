from __future__ import annotations

import importlib
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

from routes import qa_contract
from services import sofia_orchestrator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_app() -> FastAPI:
    app = FastAPI(title="qa-contract-probe")
    app.include_router(qa_contract.router)
    return app


def _stub_dependencies() -> None:
    qa_contract._require_non_production = lambda: None  # type: ignore[assignment]
    qa_contract.auth_service.assert_persona_access = lambda request, persona_id=None, persona_slug=None: True  # type: ignore[assignment]
    qa_contract.supabase_client.get_persona = lambda slug: {"id": "p1", "slug": slug or "vz-lupas"}  # type: ignore[assignment]
    qa_contract.supabase_client.get_persona_by_id = lambda pid: {"id": pid, "slug": "vz-lupas"}  # type: ignore[assignment]
    qa_contract.supabase_client.ensure_persona_knowledge_node = lambda _pid: {"id": "persona-1", "node_type": "persona", "slug": "self"}  # type: ignore[assignment]
    qa_contract.supabase_client.list_knowledge_nodes_by_type = lambda *args, **kwargs: []  # type: ignore[assignment]
    qa_contract.supabase_client.upsert_knowledge_node = (  # type: ignore[assignment]
        lambda payload: {
            "id": f"id-{payload.get('slug', 'node')}",
            "node_type": payload["node_type"],
            "slug": payload["slug"],
            "status": payload.get("status", "active"),
            "metadata": payload.get("metadata", {}),
        }
    )
    qa_contract.supabase_client.upsert_knowledge_edge = lambda **kwargs: {"id": "edge-1", **kwargs}  # type: ignore[assignment]
    qa_contract.supabase_client.insert_event = lambda payload, source=None: {"ok": True}  # type: ignore[assignment]


def main() -> None:
    _stub_dependencies()
    app = _mk_app()
    client = TestClient(app)
    session_id = "probe-session-01"
    persona_slug = "vz-lupas"

    report: dict = {
        "generated_at": _now(),
        "session_id": session_id,
        "persona_slug": persona_slug,
        "steps": [],
        "assertions": {},
    }

    # 1) GET baseline
    r_get_1 = client.get("/sofia/plan-json", params={"session_id": session_id, "persona_slug": persona_slug})
    body_get_1 = r_get_1.json()
    report["steps"].append({"step": "GET /sofia/plan-json baseline", "status": r_get_1.status_code, "body": body_get_1})

    # 2) PATCH create product
    r_patch_product = client.patch(
        "/sofia/plan-json",
        json={"session_id": session_id, "persona_slug": persona_slug, "command": "crie um produto teste", "patch": {}},
    )
    body_patch_product = r_patch_product.json()
    report["steps"].append({"step": "PATCH /sofia/plan-json create product", "status": r_patch_product.status_code, "body": body_patch_product})

    # 3) POST graph-command create campaign (should update plan_json even without persisted graph patch)
    r_post_campaign = client.post(
        "/sofia/graph-command",
        json={
            "persona_slug": persona_slug,
            "command": "crie uma campanha teste ia",
            "context": {"session_id": session_id, "client_action": "natural_language", "selected_node_ids": []},
        },
    )
    body_post_campaign = r_post_campaign.json()
    report["steps"].append({"step": "POST /sofia/graph-command create campaign", "status": r_post_campaign.status_code, "body": body_post_campaign})

    # 4) PATCH structural blocking marker
    r_patch_block = client.patch(
        "/sofia/plan-json",
        json={
            "session_id": session_id,
            "persona_slug": persona_slug,
            "patch": {"graph_patch_queue": [{"marker": "cycle", "message": "cycle detected"}]},
        },
    )
    body_patch_block = r_patch_block.json()
    report["steps"].append({"step": "PATCH /sofia/plan-json structural blocking", "status": r_patch_block.status_code, "body": body_patch_block})

    # 5) GET refresh in same process (should preserve session memory)
    r_get_2 = client.get("/sofia/plan-json", params={"session_id": session_id, "persona_slug": persona_slug})
    body_get_2 = r_get_2.json()
    report["steps"].append({"step": "GET /sofia/plan-json refresh same process", "status": r_get_2.status_code, "body": body_get_2})

    # 6) Simulate reload/restart: module reload clears in-memory state
    importlib.reload(sofia_orchestrator)
    r_get_3 = client.get("/sofia/plan-json", params={"session_id": session_id, "persona_slug": persona_slug})
    body_get_3 = r_get_3.json()
    report["steps"].append({"step": "GET /sofia/plan-json after orchestrator reload", "status": r_get_3.status_code, "body": body_get_3})

    p1 = body_patch_product.get("plan_json", {}).get("plan", {}).get("product", [])
    c1 = body_post_campaign.get("plan_json", {}).get("plan", {}).get("campaign", [])
    v1 = body_post_campaign.get("plan_json", {}).get("validation", {})
    v2 = body_patch_block.get("plan_json", {}).get("validation", {})
    post_reload_products = body_get_3.get("plan_json", {}).get("plan", {}).get("product", [])

    report["assertions"] = {
        "product_created_via_patch": len(p1) >= 1,
        "campaign_created_via_graph_command": len(c1) >= 1,
        "faq_rule_are_suggestions_not_blocking": any(x.get("code") == "FAQ_RECOMMENDED" for x in (v1.get("suggestions") or []))
        and any(x.get("code") == "RULE_RECOMMENDED" for x in (v1.get("suggestions") or []))
        and len(v1.get("blocking") or []) == 0,
        "blocking_only_for_structural_marker": any(x.get("code") == "CYCLE" for x in (v2.get("blocking") or [])),
        "separated_validation_buckets_present": all(k in v1 for k in ("suggestions", "pending", "blocking")),
        "survives_refresh_same_process": len(body_get_2.get("plan_json", {}).get("plan", {}).get("product", [])) >= 1,
        "survives_reload_restart": len(post_reload_products) >= 1,
    }

    out_dir = Path("test-artifacts/qa")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sofia-plan-json-endpoints-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()

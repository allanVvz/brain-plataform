from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _req():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))


def test_catalog_ingest_rejects_embed_rows(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract, "_require_qa_persona", lambda request, persona_ref: {"id": "p1", "slug": "vz-lupas"})

    created = []

    def fake_persist_pending_knowledge_item(**kwargs):
        created.append(kwargs)
        return {"id": f"ki-{len(created)}", "content_type": kwargs["content_type"], "status": "pending"}

    monkeypatch.setattr(qa_contract.knowledge_lifecycle, "persist_pending_knowledge_item", fake_persist_pending_knowledge_item)

    body = qa_contract.CatalogIngestBody(
        persona_slug="vz-lupas",
        entries=[
            qa_contract.CatalogEntry(title="Prod A", content="A", content_type="product"),
            qa_contract.CatalogEntry(title="Nope", content="B", content_type="embed"),
        ],
    )
    result = qa_contract.catalog_ingest(body, _req())

    assert result["ok"] is True
    assert result["drafts_created"] == 1
    assert result["rejected_embed_rows"] == 1
    assert len(result["items"]) == 1


def test_vzlupas_alias_resolves_to_canonical_vz_lupas_persona(monkeypatch):
    from routes import qa_contract

    personas = {
        "vz-lupas": {"id": "p1", "slug": "vz-lupas", "name": "VZ Lupas"},
    }
    access_checks = []

    monkeypatch.setattr(qa_contract.supabase_client, "get_persona", lambda slug: personas.get(slug))
    monkeypatch.setattr(
        qa_contract.auth_service,
        "assert_persona_access",
        lambda request, persona_id=None, persona_slug=None: access_checks.append(
            {"persona_id": persona_id, "persona_slug": persona_slug}
        ),
    )

    persona = qa_contract._require_qa_persona(_req(), "vzlupas")

    assert persona["id"] == "p1"
    assert persona["slug"] == "vz-lupas"
    assert access_checks == [{"persona_id": "p1", "persona_slug": "vz-lupas"}]


def test_embeds_generate_requires_approved_faq(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract, "_require_qa_persona", lambda request, persona_ref: {"id": "p1", "slug": "vz-lupas"})
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "get_knowledge_node",
        lambda _node_id: {"id": "n1", "node_type": "faq", "status": "pending", "persona_id": "p1"},
    )

    body = qa_contract.EmbedsGenerateBody(persona_slug="vz-lupas", faq_node_id="n1")
    try:
        qa_contract.embeds_generate(body, _req())
        raised = False
    except HTTPException as exc:
        raised = True
        assert exc.status_code == 409
        assert "Unapproved FAQ" in str(exc.detail)
    assert raised is True


def test_seed_official_real_runs_pipeline(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract, "_require_qa_persona", lambda request, persona_ref: {"id": "p1", "slug": "vz-lupas"})
    monkeypatch.setattr(
        qa_contract,
        "_build_official_seed_entries",
        lambda limit_products=9: [
            qa_contract.CatalogEntry(title="Prod A", content="A", content_type="product"),
            qa_contract.CatalogEntry(title="FAQ A", content="Pergunta: x\nResposta: y", content_type="faq"),
        ],
    )

    calls = {"persist": 0, "promote": 0, "publish": 0, "events": 0, "rebuild": 0}

    def fake_persist_pending_knowledge_item(**kwargs):
        calls["persist"] += 1
        item_id = "ki-faq" if kwargs["content_type"] == "faq" else "ki-prod"
        return {"id": item_id, "content_type": kwargs["content_type"], "status": "pending"}

    def fake_promote(item_id, promote_to_kb=False):
        calls["promote"] += 1
        return {"item": {"id": item_id, "status": "approved"}, "evidence": {"ok": True}}

    def fake_get_knowledge_node_for_source(source_table, source_id, persona_id=None):
        if source_table == "knowledge_items" and source_id == "ki-faq":
            return {"id": "gn-faq", "node_type": "faq", "persona_id": "p1"}
        return None

    def fake_publish_approved_node(node_id, approved_by=None, require_rag_for_faq=True):
        calls["publish"] += 1
        return {"status": "active", "embedded_edge_id": "ge-1", "rag_entry_id": "re-1"}

    def fake_insert_event(payload, source=None):
        calls["events"] += 1
        return {"ok": True}

    def fake_rebuild_graph_for_persona(persona_id):
        calls["rebuild"] += 1
        return {"nodes": 10 + calls["rebuild"], "edges": 20 + calls["rebuild"]}

    monkeypatch.setattr(qa_contract.knowledge_lifecycle, "persist_pending_knowledge_item", fake_persist_pending_knowledge_item)
    monkeypatch.setattr(qa_contract.knowledge_lifecycle, "promote_knowledge_item", fake_promote)
    monkeypatch.setattr(qa_contract.supabase_client, "get_knowledge_node_for_source", fake_get_knowledge_node_for_source)
    monkeypatch.setattr(qa_contract.approved_knowledge_snapshots, "publish_approved_node", fake_publish_approved_node)
    monkeypatch.setattr(qa_contract.supabase_client, "insert_event", fake_insert_event)
    monkeypatch.setattr(qa_contract.knowledge_graph, "rebuild_graph_for_persona", fake_rebuild_graph_for_persona)

    result = qa_contract.seed_official_real(qa_contract.OfficialSeedBody(persona_slug="vz-lupas"), _req())

    assert result["ok"] is True
    assert result["draft_items_created"] == 2
    assert result["faqs_approved"] == 1
    assert result["embeds_generated"] == 1
    assert calls["persist"] == 2
    assert calls["promote"] == 1
    assert calls["publish"] == 1
    assert calls["rebuild"] == 2


def test_sofia_graph_command_rejects_product_to_embed(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract, "_require_qa_persona", lambda request, persona_ref: {"id": "p1", "slug": "vz-lupas"})
    monkeypatch.setattr(qa_contract.supabase_client, "ensure_persona_knowledge_node", lambda _persona_id: {"id": "persona-1", "node_type": "persona", "slug": "self"})
    monkeypatch.setattr(qa_contract.supabase_client, "list_knowledge_nodes_by_type", lambda *args, **kwargs: [])
    monkeypatch.setattr(qa_contract.supabase_client, "insert_event", lambda payload, source=None: {"ok": True})
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "upsert_knowledge_node",
        lambda payload: {"id": f"id-{payload['slug']}", "node_type": payload["node_type"], "slug": payload["slug"], "status": payload.get("status", "active")},
    )

    body = qa_contract.SofiaGraphCommandBody(
        persona_slug="vz-lupas",
        command="intent",
        context=qa_contract.SofiaGraphCommandContext(
            client_action="structured_intent",
            graph_patch={
                "nodes_upsert": [
                    {"node_type": "product", "slug": "prod-x", "title": "Prod X", "metadata": {"source_url": "https://example.com/x"}},
                    {"node_type": "embedded", "slug": "emb-x", "title": "Emb X"},
                ],
                "edges_upsert": [{"source_ref": "slug:prod-x", "target_ref": "slug:emb-x", "relation_type": "contains"}],
            },
        ),
    )
    try:
        qa_contract.sofia_graph_command(body, _req())
        raised = False
    except HTTPException as exc:
        raised = True
        assert exc.status_code == 422
        assert exc.detail["code"] == "GRAPH_VALIDATION_FAILED"
    assert raised is True


def test_sofia_graph_command_applies_reencaixe(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract, "_require_qa_persona", lambda request, persona_ref: {"id": "p1", "slug": "vz-lupas"})
    monkeypatch.setattr(qa_contract.supabase_client, "ensure_persona_knowledge_node", lambda _persona_id: {"id": "persona-1", "node_type": "persona", "slug": "self"})
    monkeypatch.setattr(qa_contract.supabase_client, "list_knowledge_nodes_by_type", lambda *args, **kwargs: [])
    monkeypatch.setattr(qa_contract.supabase_client, "insert_event", lambda payload, source=None: {"ok": True})
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "upsert_knowledge_node",
        lambda payload: {"id": "brand-1", "node_type": payload["node_type"], "slug": payload["slug"], "status": "active"},
    )
    edge_calls = []

    def fake_upsert_edge(**kwargs):
        edge_calls.append(kwargs)
        return {"id": "e1"}

    monkeypatch.setattr(qa_contract.supabase_client, "upsert_knowledge_edge", fake_upsert_edge)

    body = qa_contract.SofiaGraphCommandBody(
        persona_slug="vz-lupas",
        command="reencaixe VZ Lupas abaixo de AllanVvz",
        context=qa_contract.SofiaGraphCommandContext(client_action="natural_language"),
    )
    result = qa_contract.sofia_graph_command(body, _req())

    assert result["ok"] is True
    assert result["persisted"] is True
    assert len(edge_calls) == 1

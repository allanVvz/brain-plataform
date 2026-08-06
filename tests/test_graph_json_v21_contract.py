from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from schemas.graph_json_v2 import GraphJson
from services import (
    graph_action_policy,
    graph_context_resolver_v2,
    graph_document_publisher,
    graph_json_v2_store,
    graph_json_v2_validator,
    graph_markdown,
)


def _graph(*, include_unpublished: bool = False) -> GraphJson:
    nodes = [
        {
            "id": "node:persona:acme", "node_class": "knowledge", "node_type": "persona",
            "slug": "acme", "title": "Acme", "lifecycle": {"status": "approved"},
            "provenance": {"source": "test"}, "spec": {"summary": "Empresa Acme"},
        },
        {
            "id": "node:product:wash", "node_class": "knowledge", "node_type": "product",
            "slug": "wash", "title": "Lavagem", "lifecycle": {"status": "approved"},
            "provenance": {"source": "test"}, "spec": {"summary": "Lavagem detalhada", "aliases": ["detalhamento"]},
        },
        {
            "id": "node:faq:wash-price", "node_class": "knowledge", "node_type": "faq",
            "slug": "wash-price", "title": "Quanto custa?", "lifecycle": {"status": "approved"},
            "provenance": {"source": "test"}, "spec": {"question": "Quanto custa?", "answer": "R$ 180."},
        },
        {
            "id": "action:embedded:sdr", "node_class": "action", "node_type": "embedded",
            "slug": "sdr", "title": "SDR", "lifecycle": {"status": "approved"},
            "action": {
                "destination_id": "dataset:sdr", "destination_type": "rag_dataset",
                "consumer": {"kind": "agent", "ref": "sdr:acme"},
                "accepted_node_types": ["product", "faq"],
                "projection": {"kind": "rag", "embedding_profile_ref": "default-1536"},
            },
        },
    ]
    if include_unpublished:
        nodes.append({
            "id": "node:faq:private", "node_class": "knowledge", "node_type": "faq",
            "slug": "private", "title": "Interna", "lifecycle": {"status": "approved"},
            "provenance": {"source": "test"}, "spec": {"question": "Segredo?", "answer": "Não publicar."},
        })
    edges = [
        {"id": "edge:contains:product", "source": "node:persona:acme", "target": "node:product:wash", "relation_type": "contains"},
        {"id": "edge:contains:faq", "source": "node:product:wash", "target": "node:faq:wash-price", "relation_type": "contains"},
        {"id": "edge:answers", "source": "node:faq:wash-price", "target": "node:product:wash", "relation_type": "answers", "primary_tree": False},
        {
            "id": "edge:publish:product", "source": "node:product:wash", "target": "action:embedded:sdr",
            "relation_type": "publishes_to", "lifecycle": {"status": "active"},
            "grant": {"mode": "manual", "reason": "test"},
        },
        {
            "id": "edge:publish:faq", "source": "node:faq:wash-price", "target": "action:embedded:sdr",
            "relation_type": "publishes_to", "lifecycle": {"status": "active"},
            "grant": {"mode": "manual", "reason": "test"},
        },
    ]
    if include_unpublished:
        edges.append({"id": "edge:contains:private", "source": "node:product:wash", "target": "node:faq:private", "relation_type": "contains"})
    return GraphJson.model_validate({
        "schema_version": "2.1", "graph_id": "acme", "tenant": "test",
        "persona_slug": "acme", "status": "draft", "nodes": nodes, "edges": edges,
    })


def test_v21_validates_publication_and_markdown_is_deterministic():
    graph = _graph()
    assert graph_json_v2_validator.validate_graph_json(graph) == (True, [])
    rendered = graph_markdown.canonicalize_graph(graph)
    again = graph_markdown.canonicalize_graph(rendered, reject_markdown_drift=False)
    assert rendered.nodes[1].markdown.content == again.nodes[1].markdown.content
    assert "## Publicação" in rendered.nodes[1].markdown.content


def test_checksum_ignores_layout_and_graph_version():
    graph = _graph()
    first = graph_json_v2_store.checksum_graph(graph)
    graph.graph_version = 9
    graph.layout.positions["node:product:wash"] = [120, 450]
    assert graph_json_v2_store.checksum_graph(graph) == first


def test_material_edit_invalidates_approval_and_revoke_preserves_edge():
    graph = _graph()
    edited = graph_document_publisher.apply_operations(graph, [
        {"op": "update_node", "node_id": "node:product:wash", "patch": {"spec.summary": "Novo texto"}},
        {"op": "revoke_edge", "edge_id": "edge:publish:product"},
    ])
    product = next(node for node in edited.nodes if node.id == "node:product:wash")
    publication = next(edge for edge in edited.edges if edge.id == "edge:publish:product")
    assert product.lifecycle.status == "pending_validation"
    assert product.lifecycle.revision == 2
    assert publication.lifecycle.status == "revoked"


def test_resolver_never_returns_unpublished_node(monkeypatch):
    graph = _graph(include_unpublished=True)
    graph.graph_version = 3
    graph.content_checksum = graph_json_v2_store.checksum_graph(graph)
    monkeypatch.setattr(graph_json_v2_store, "load_activated_version", lambda *args, **kwargs: graph)
    result = graph_context_resolver_v2.resolve_context(
        persona_slug="acme", destination_id="dataset:sdr", graph_version=3,
        intent="product_interest", query="quanto custa lavagem", max_nodes=24, max_tokens=8000,
    )
    ids = {item["node_id"] for item in result["items"]}
    assert "node:faq:wash-price" in ids
    assert "node:faq:private" not in ids
    assert all(item["why"]["destination_id"] == "dataset:sdr" for item in result["items"])


def test_auto_policy_is_idempotent():
    graph = _graph()
    action = next(node for node in graph.nodes if node.node_class == "action")
    action.action.policy.auto_connect = [{
        "policy_id": "approved-products", "enabled": True,
        "accepted_node_types": ["product"],
        "conditions": {"all": [{"field": "lifecycle.status", "op": "eq", "value": "approved"}]},
    }]
    # Remove the manual product grant to let the policy create it.
    graph.edges = [edge for edge in graph.edges if edge.id != "edge:publish:product"]
    first, changes = graph_action_policy.apply(graph)
    second, replay_changes = graph_action_policy.apply(first)
    assert [item["op"] for item in changes] == ["activate"]
    assert replay_changes == []
    assert len([edge for edge in second.edges if edge.grant and edge.grant.policy_id == "approved-products"]) == 1


def test_activated_event_exposes_published_runtime_status(monkeypatch):
    graph = _graph()
    graph.status = "committed"
    monkeypatch.setattr(
        graph_json_v2_store.supabase_client,
        "list_system_events",
        lambda **_kwargs: [
            {
                "event_type": "graph_version_activated",
                "created_at": "2026-08-02T12:00:00Z",
                "payload": {
                    "persona_slug": "acme",
                    "brand_slug": None,
                    "version": 6,
                    "graph_json": graph.model_dump(mode="json"),
                },
            }
        ],
    )

    version, loaded = graph_json_v2_store.load_current("acme")
    assert version == 6
    assert loaded.status == "published"


def test_latest_graph_event_is_scoped_in_postgrest(monkeypatch):
    captured = {}

    def fake_list_system_events(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        graph_json_v2_store.supabase_client,
        "list_system_events",
        fake_list_system_events,
    )

    assert graph_json_v2_store.latest_event("aurora", "aurora") is None
    assert captured["payload_equals"] == {
        "persona_slug": "aurora",
        "brand_slug": "aurora",
    }
    assert captured["limit"] == 20

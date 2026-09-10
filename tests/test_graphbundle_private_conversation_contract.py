from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_API = ROOT / "apps" / "control-plane" / "api"
if str(CONTROL_API) not in sys.path:
    sys.path.insert(0, str(CONTROL_API))

from services import graph_bundle, graph_bundle_adapter  # noqa: E402


def test_detached_conversation_is_valid_private_terminal() -> None:
    bundle = {
        "bundle_version": "1.0",
        "persona": {"id": "00000000-0000-0000-0000-000000000001", "slug": "persona"},
        "metadata": {"source": "test", "publication_allowed": False, "embedding_profile": {"embedding_provider": "local", "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "embedding_dimension": 1536}},
        "nodes": [
            {"id": "persona:root", "projection_node_id": "00000000-0000-0000-0000-000000000002", "node_type": "persona", "slug": "persona", "title": "Persona", "summary": "Root", "status": "validated", "data": {"source": "test", "status": "validated"}},
            {"id": "conversation:lead-1", "projection_node_id": "00000000-0000-0000-0000-000000000003", "node_type": "conversation", "slug": "conversation-lead-1", "title": "Conversation", "summary": "Private thread", "status": "active", "data": {"source": "messages", "status": "active", "lead_id": 1, "rag_eligible": False, "public_site_eligible": False}},
            {"id": "asset:lead-1-photo", "projection_node_id": "00000000-0000-0000-0000-000000000004", "node_type": "asset", "slug": "lead-1-photo", "title": "Received photo", "summary": "Private inbound media", "status": "active", "data": {"source": "messages", "status": "active", "rag_eligible": False, "public_site_eligible": False}},
        ],
        "edges": [{"id": "edge:conversation-photo", "source": "conversation:lead-1", "target": "asset:lead-1-photo", "relation_type": "contains", "weight": 1, "metadata": {}}],
    }

    normalized = graph_bundle.normalize_bundle(bundle)

    assert any(node["node_type"] == "conversation" for node in normalized["nodes"])
    assert "conversation" in graph_bundle.DETACHED_TERMINAL_TYPES


def test_reachability_repair_never_exposes_private_conversation() -> None:
    assert "conversation" in graph_bundle_adapter._DETACHED_TERMINAL_TYPES


def test_control_plane_media_tracking_falls_back_to_lead_membership(monkeypatch) -> None:
    module_path = CONTROL_API / "services" / "inbound_media_graph.py"
    spec = importlib.util.spec_from_file_location("control_inbound_media_graph", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def execute(self): return type("R", (), {"data": []})()

    monkeypatch.setattr(module.supabase_client, "get_client", lambda: type("C", (), {"table": lambda _s, _n: Query()})())
    monkeypatch.setattr(module.supabase_client, "get_lead_memberships", lambda _lead_id: [{"audience_id": "audience-1", "audience": {"persona_id": "persona-1"}}])
    monkeypatch.setattr(module.supabase_client, "get_knowledge_node_for_source", lambda *_a, **_k: {"id": "audience-node-1"})

    audience = module._audience_node("persona-1", None, 42)

    assert audience["id"] == "audience-node-1"

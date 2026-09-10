from __future__ import annotations

import sys
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) in sys.path:
    sys.path.remove(str(API_DIR))
sys.path.insert(0, str(API_DIR))

from services import asset_product_correlation as service  # noqa: E402
from services.agent_harness import classify_intent  # noqa: E402
from services.agent_harness_tools import HARNESS_TOOL_REGISTRY  # noqa: E402


class _Graph:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self, mode: str = "json") -> dict:
        return self.payload


def _graph(relation: str = "contains", *, slot: bool = False) -> _Graph:
    metadata = {"role": "product_image"} if slot else {}
    return _Graph({
        "nodes": [
            {"id": "product:one", "node_type": "product", "slug": "one"},
            {"id": "asset:one", "node_type": "asset", "data": {"asset_id": "registry-1", "product_node_id": "product:one"}},
        ],
        "edges": [{"id": "edge:old", "source": "product:one", "target": "asset:one", "relation_type": relation, "metadata": metadata}],
    })


def _arrange(monkeypatch, graph: _Graph) -> None:
    monkeypatch.setattr(service.supabase_client, "get_persona_by_id", lambda _id: {"id": "persona-1", "slug": "persona"})
    monkeypatch.setattr(service.supabase_client, "list_assets", lambda **_kwargs: [{
        "id": "registry-1", "persona_id": "persona-1", "content_sha256": "a" * 64, "status": "approved",
    }])
    monkeypatch.setattr(service.graph_json_v2_store, "load_current", lambda _slug: (7, graph))
    monkeypatch.setattr(service.graph_json_v2_store, "checksum_graph", lambda _graph: "sha256:graph")


def _call() -> dict:
    return service.propose_asset_product_correlations(
        {}, persona_id="persona-1", persona_slug="persona", asset_ids=["registry-1"],
        content_sha256=[], correlations=[], expected_graph_version=7, graph_hash="sha256:graph",
        idempotency_key="correlation-preview-1", reason="Corrigir imagem do produto",
    )


def test_relation_mismatch_proposes_product_to_asset_uses_asset_without_writing(monkeypatch) -> None:
    _arrange(monkeypatch, _graph())

    result = _call()

    assert result["automatic_mutation"] is False
    assert result["publication_allowed"] is False
    assert result["candidates"][0]["decision"] == "exact"
    assert "relation_mismatch:contains" in result["candidates"][0]["evidence"]
    operations = result["patch"].model_dump(mode="json")["operations"]
    assert [item["op"] for item in operations] == ["revoke_edge", "add_edge"]
    edge = operations[1]["value"]
    assert edge["source"] == "product:one"
    assert edge["target"] == "asset:one"
    assert edge["relation_type"] == "uses_asset"
    assert edge["metadata"]["page_binding"]["slot_key"] == "product_image:one"


def test_existing_canonical_edge_is_a_noop(monkeypatch) -> None:
    _arrange(monkeypatch, _graph("uses_asset", slot=True))

    result = _call()

    assert result["candidates"][0]["decision"] == "duplicate"
    assert result["patch"] is None


def test_filename_or_ocr_without_canonical_identity_needs_human_review(monkeypatch) -> None:
    graph = _graph()
    graph.payload["nodes"][1]["data"].pop("product_node_id")
    _arrange(monkeypatch, graph)

    result = _call()

    assert result["candidates"][0]["decision"] == "needs_human_review"
    assert result["patch"] is None


def test_sofia_exposes_and_routes_the_draft_correlation_tool() -> None:
    manifest = HARNESS_TOOL_REGISTRY.get("graph.propose_asset_product_correlations")
    assert manifest is not None
    assert manifest.effect.value == "draft"
    assert classify_intent("correlacione estas imagens aos produtos") == ("asset.correlation", "graph_card_specialist")

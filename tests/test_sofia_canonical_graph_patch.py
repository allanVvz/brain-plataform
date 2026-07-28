from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from schemas.graph_json_v2 import GraphJson
from services.graph_document_publisher import apply_sofia_patch
from services.graph_json_v2_validator import validate_graph_json


def test_sofia_patch_updates_complete_document_without_projection_writes():
    graph = GraphJson.model_validate(
        {
            "graph_id": "sofia-canonical",
            "tenant": "qa",
            "persona_slug": "acme",
            "nodes": [
                {"id": "persona", "node_type": "persona", "slug": "acme", "label": "Acme"},
                {
                    "id": "brand",
                    "node_type": "brand",
                    "slug": "brand",
                    "label": "Brand",
                    "parent_id": "persona",
                },
            ],
            "edges": [
                {
                    "id": "brand-edge",
                    "source": "persona",
                    "target": "brand",
                    "relation": "belongs_to_persona",
                }
            ],
        }
    )
    updated = apply_sofia_patch(
        graph,
        {
            "nodes_upsert": [
                {
                    "node_type": "campaign",
                    "slug": "winter",
                    "title": "Winter",
                    "status": "pending_validation",
                }
            ],
            "edges_upsert": [
                {
                    "source_ref": "slug:brand",
                    "target_ref": "slug:winter",
                    "relation_type": "part_of_campaign",
                    "metadata": {"primary_tree": True},
                }
            ],
        },
    )
    campaign = next(node for node in updated.nodes if node.slug == "winter")
    assert campaign.parent_id == "brand"
    assert campaign.data["source"] == "sofia_graph"
    valid, errors = validate_graph_json(updated)
    assert valid, errors


def test_sofia_patch_reuses_type_and_slug():
    graph = GraphJson.model_validate(
        {
            "graph_id": "sofia-dedupe",
            "tenant": "qa",
            "persona_slug": "acme",
            "nodes": [
                {"id": "persona", "node_type": "persona", "slug": "acme", "label": "Acme"},
                {
                    "id": "brand",
                    "node_type": "brand",
                    "slug": "brand",
                    "label": "Old",
                    "parent_id": "persona",
                },
            ],
            "edges": [
                {
                    "id": "brand-edge",
                    "source": "persona",
                    "target": "brand",
                    "relation": "belongs_to_persona",
                }
            ],
        }
    )
    updated = apply_sofia_patch(
        graph,
        {"nodes_upsert": [{"node_type": "brand", "slug": "brand", "title": "New"}]},
    )
    brands = [node for node in updated.nodes if node.node_type == "brand" and node.slug == "brand"]
    assert len(brands) == 1
    assert brands[0].label == "New"

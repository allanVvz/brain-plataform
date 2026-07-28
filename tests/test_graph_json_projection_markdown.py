from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from schemas.graph_json_v2 import GraphJson
from services import graph_json_importer


def test_every_node_type_uses_canonical_persona_vault_path():
    graph = GraphJson.model_validate(
        {
            "graph_id": "paths",
            "tenant": "qa",
            "persona_slug": "tock-fatal",
            "nodes": [],
            "edges": [],
        }
    )
    for node_type in ("persona", "embedded", "gallery", "asset", "faq"):
        node = graph_json_importer.Node(
            id=node_type,
            node_type=node_type,
            slug=f"{node_type}-default",
            label=node_type.title(),
        )
        path = graph_json_importer._file_path(graph, node)
        assert path.startswith("AI-BRAIN/05_ENTITIES/CLIENTS/TOCK_FATAL/")
        assert path.endswith(".md")


def test_supplied_traversal_path_is_rejected():
    graph = GraphJson.model_validate(
        {
            "graph_id": "paths",
            "tenant": "qa",
            "persona_slug": "acme",
            "nodes": [],
            "edges": [],
        }
    )
    node = graph_json_importer.Node(
        id="asset",
        node_type="asset",
        slug="hero",
        label="Hero",
        data={"file_path": "../../outside.md"},
    )
    with pytest.raises(ValueError, match="unsafe file_path"):
        graph_json_importer._file_path(graph, node)

from __future__ import annotations

import json
import os
from pathlib import Path

import requests
import yaml


def _load_admin_token(repo_root: Path) -> str:
    env_path = repo_root / "env.qa.yaml"
    raw = yaml.safe_load(env_path.read_text(encoding="utf-8")) or {}
    token = str(raw.get("AI_BRAIN_ADMIN_TEST_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("AI_BRAIN_ADMIN_TEST_TOKEN not found in env.qa.yaml")
    return token


def _to_graph_json(graph_data: dict) -> dict:
    nodes = []
    edges = []
    for node in graph_data.get("nodes", []):
        data = node.get("data") or {}
        nodes.append(
            {
                "id": node.get("id"),
                "type": data.get("node_type") or data.get("content_type") or "unknown",
                "slug": data.get("slug"),
                "label": data.get("label"),
                "approved": str(data.get("approval_state") or "").lower() in {"approved", "embedded", "validated"},
                "metadata": data.get("metadata") or {},
            }
        )
    for edge in graph_data.get("edges", []):
        data = edge.get("data") or {}
        if str(edge.get("id") or "").startswith("draft:"):
            continue
        metadata = data.get("metadata") or {}
        relation_type = data.get("relation_type") or "related"
        structural_relations = {
            "persona_has_brand",
            "brand_has_briefing",
            "briefing_has_campaign",
            "campaign_has_audience",
            "audience_has_product_group",
            "product_group_has_product",
            "product_has_faq",
            "faq_has_embed",
        }
        is_main = bool(data.get("primary_tree") or metadata.get("primary_tree")) and relation_type in structural_relations
        edges.append(
            {
                "id": edge.get("id"),
                "source": edge.get("source"),
                "target": edge.get("target"),
                "relation_type": relation_type,
                "edge_type": "main" if is_main else "reference",
                "metadata": metadata,
            }
        )
    return {"version": "1.0", "nodes": nodes, "edges": edges}


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    token = _load_admin_token(repo_root)
    base = os.environ.get("AI_BRAIN_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    headers = {"X-AI-BRAIN-ADMIN-TOKEN": token}

    graph_resp = requests.get(
        f"{base}/knowledge/graph-data",
        params={"persona_slug": "allanvvz", "mode": "semantic_tree", "max_depth": 6, "include_embedded": "true"},
        headers=headers,
        timeout=120,
    )
    graph_resp.raise_for_status()
    graph_json = _to_graph_json(graph_resp.json())

    publish_resp = requests.post(
        f"{base}/graph-documents/publish",
        headers=headers,
        json={
            "persona_slug": "allanvvz",
            "brand_slug": "vz-lupas",
            "graph_json": graph_json,
            "source": "import_v1_to_v2_allanvvz",
            "note": "Imported from knowledge graph V1",
        },
        timeout=120,
    )
    publish_resp.raise_for_status()
    print(json.dumps(publish_resp.json(), ensure_ascii=False))


if __name__ == "__main__":
    main()

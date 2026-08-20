from __future__ import annotations

import json
import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle, graph_bundle_publisher


def _bundle() -> dict:
    return json.loads(
        (REPO_ROOT / "data" / "graph_bundles" / "tock-fatal" / "sdr-qualification-v1.json")
        .read_text(encoding="utf-8")
    )


def test_stage_bundle_materializes_then_requires_exact_runtime_checksum(monkeypatch):
    bundle = _bundle()
    plan = graph_bundle.build_publication_plan(bundle)
    normalized = graph_bundle.normalize_bundle(bundle)
    persona, compiled_nodes, compiled_edges, _profile = graph_bundle._compiler_inputs(bundle)
    current_nodes = [
        {
            "id": node["projection_node_id"],
            "node_type": node["node_type"],
            "slug": node["slug"],
            "status": node["status"],
            "metadata": {},
        }
        for node in normalized["nodes"]
        if node["node_type"] in {"persona", "embed", "gallery"}
    ]
    graph_reads = iter([(current_nodes, []), (compiled_nodes, compiled_edges)])
    monkeypatch.setattr(
        graph_bundle_publisher.supabase_client,
        "get_persona",
        lambda _slug: {**persona, "name": "Tock Fatal"},
    )
    monkeypatch.setattr(
        graph_bundle_publisher.supabase_client,
        "list_all_knowledge_graph",
        lambda **_kwargs: next(graph_reads),
    )
    materialized_nodes: list[dict] = []
    monkeypatch.setattr(
        graph_bundle_publisher.supabase_client,
        "upsert_knowledge_node",
        lambda row: materialized_nodes.append(row) or row,
    )
    monkeypatch.setattr(
        graph_bundle_publisher.supabase_client,
        "upsert_knowledge_edge",
        lambda *_args, **_kwargs: {"id": "edge-row"},
    )
    monkeypatch.setattr(
        graph_bundle_publisher.graph_compiler_v3,
        "compile_persona_publication",
        lambda *_args, **_kwargs: {
            "publication": {
                "id": "publication-1",
                "version": 1,
                "checksum": plan["runtime_checksum"],
                "status": "compiled",
            },
            "activation": None,
            "cached": False,
        },
    )
    monkeypatch.setattr(
        graph_bundle_publisher.supabase_client, "insert_event", lambda *_a, **_k: None
    )

    staged = graph_bundle_publisher.stage_bundle(
        bundle,
        approved_draft_checksum=plan["draft_checksum"],
        actor="test",
        embedder=lambda texts: [[0.0] * 1536 for _ in texts],
    )

    assert staged["publication"]["checksum"] == plan["runtime_checksum"]
    assert staged["activation"] is None
    assert materialized_nodes
    assert all("source_id" not in row for row in materialized_nodes)
    assert all(row["metadata"].get("graph_json_node_id") for row in materialized_nodes)


def test_stage_bundle_rejects_stale_human_approval_before_writes(monkeypatch):
    writes: list[dict] = []
    monkeypatch.setattr(
        graph_bundle_publisher.supabase_client,
        "upsert_knowledge_node",
        lambda row: writes.append(row),
    )

    try:
        graph_bundle_publisher.stage_bundle(
            _bundle(), approved_draft_checksum="sha256:stale", actor="test"
        )
        raise AssertionError("expected checksum rejection")
    except graph_bundle_publisher.GraphBundlePublishError as exc:
        assert "approved_draft_checksum_mismatch" in str(exc)

    assert writes == []

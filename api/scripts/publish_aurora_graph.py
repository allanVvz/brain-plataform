"""Publish only Aurora's canonical graph fixture; never creates accounts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.graph_json_v2 import Edge, EdgeLifecycle, GraphJson, PublicationGrant
from services import (
    graph_document_publisher,
    graph_json_v21_adapter,
    graph_json_v2_store,
)


FIXTURE = ROOT / "scripts" / "fixtures" / "aurora_graph_v2.json"


def build_graph() -> GraphJson:
    """Build Aurora's v2.1 graph and preserve the 44-node agent dataset.

    The historical fixture published every approved factual node into the
    persona-wide RAG.  During the v2.1 cutover we make that authorization
    explicit against Aurora's isolated Embedded action so the dialogue loses
    neither rules, tone, products nor FAQs.
    """
    legacy = GraphJson.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    graph = graph_json_v21_adapter.upgrade_to_v21(legacy)
    embedded = next(node for node in graph.nodes if node.node_type == "embedded")
    if embedded.action is None:
        raise RuntimeError("Aurora Embedded action is missing")
    embedded.slug = "sdr-aurora"
    embedded.title = "Golden Dataset SDR Aurora"
    embedded.label = embedded.title
    embedded.action.destination_id = "dataset:sdr-aurora"
    embedded.action.consumer.kind = "agent"
    embedded.action.consumer.ref = "sdr:aurora"

    active_sources = {
        edge.source
        for edge in graph.edges
        if edge.target == embedded.id
        and edge.relation_type == "publishes_to"
        and edge.lifecycle.status == "active"
    }
    for node in graph.nodes:
        if (
            node.node_class != "knowledge"
            or node.node_type == "persona"
            or node.lifecycle.status != "approved"
            or node.id in active_sources
        ):
            continue
        graph.edges.append(
            Edge(
                id=f"edge:publish:{node.id}:sdr-aurora",
                source=node.id,
                target=embedded.id,
                relation_type="publishes_to",
                relation_class="publication",
                primary_tree=False,
                lifecycle=EdgeLifecycle(status="active"),
                grant=PublicationGrant(
                    mode="manual",
                    actor="production-release",
                    reason="Preserve Aurora's approved agent dataset during Graph v2.1 cutover",
                ),
                metadata={"migration": "aurora-v20-to-v21"},
            )
        )
    return graph


def publish(*, expected_version: int | None = None) -> dict:
    graph = build_graph()
    current = graph_json_v2_store.load_current("aurora", graph.brand_slug)
    base_version = int(expected_version) if expected_version is not None else (int(current[0]) if current else 0)
    checksum = graph_json_v2_store.checksum_graph(graph)
    return graph_document_publisher.commit(
        graph=graph,
        persona_slug="aurora",
        brand_slug=graph.brand_slug,
        source="aurora_markdown_release",
        reason="Aurora Graph JSON v2.1 canonical rollout",
        published_by="production-release",
        expected_version=base_version,
        idempotency_key=f"aurora-graph-v21:{checksum}",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", type=int)
    args = parser.parse_args()
    result = publish(expected_version=args.expected_version)
    print(json.dumps({
        "ok": result.get("ok"),
        "version": result.get("version"),
        "checksum": result.get("checksum"),
        "idempotent_replay": result.get("idempotent_replay"),
    }))

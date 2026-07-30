"""Publish only Aurora's canonical graph fixture; never creates accounts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.graph_json_v2 import GraphJson
from services import graph_document_publisher, graph_json_v2_store


FIXTURE = ROOT / "scripts" / "fixtures" / "aurora_graph_v2.json"


def publish(*, expected_version: int | None = None) -> dict:
    graph = GraphJson.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    checksum = graph_json_v2_store.checksum_graph(graph)
    return graph_document_publisher.publish(
        graph=graph,
        persona_slug="aurora",
        brand_slug=graph.brand_slug,
        source="aurora_markdown_release",
        note="Aurora canonical factual Markdown publication",
        expected_version=expected_version,
        idempotency_key=f"aurora-markdown:{checksum}",
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

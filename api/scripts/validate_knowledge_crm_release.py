"""Production-safe release contract checks; prints no secrets or user content."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import graph_json_v2_store


def validate() -> dict:
    aurora_current = graph_json_v2_store.load_current("aurora")
    if not aurora_current:
        raise RuntimeError("Aurora graph is not published")
    aurora_version, aurora = aurora_current
    aurora_event = graph_json_v2_store.latest_event("aurora") or {}
    factual = [
        node for node in aurora.nodes
        if node.node_type not in {"embedded", "gallery"}
    ]
    faqs = [node for node in aurora.nodes if node.node_type == "faq"]
    embedded = next(node for node in aurora.nodes if node.node_type == "embedded")
    faq_edges = [
        edge for edge in aurora.edges
        if edge.target == embedded.id
        and edge.source in {node.id for node in faqs}
        and edge.primary_tree is False
    ]
    checks = {
        "aurora_nodes": len(aurora.nodes),
        "aurora_edges": len(aurora.edges),
        "aurora_markdown_documents": sum(
            1 for node in factual if str((node.data or {}).get("markdown") or "").strip()
        ),
        "aurora_faqs": len(faqs),
        "aurora_faq_embedded_edges": len(faq_edges),
        "aurora_orphan_faqs": len(faqs) - len({edge.source for edge in faq_edges}),
    }
    expected = {
        "aurora_nodes": 26,
        "aurora_edges": 32,
        "aurora_markdown_documents": 24,
        "aurora_faqs": 8,
        "aurora_faq_embedded_edges": 8,
        "aurora_orphan_faqs": 0,
    }
    if checks != expected:
        raise RuntimeError({"expected": expected, "actual": checks})
    if any(
        (node.data or {}).get("markdown_document") is not True
        or int((node.data or {}).get("question_count") or 0) != 1
        for node in faqs
    ):
        raise RuntimeError("Aurora FAQ Markdown contract failed")

    baita_current = graph_json_v2_store.load_current("baita-conveniencia")
    if not baita_current or int(baita_current[0]) != 9:
        raise RuntimeError("Baita Graph v9 was not preserved")
    baita_event = graph_json_v2_store.latest_event("baita-conveniencia") or {}
    return {
        "ok": True,
        **checks,
        "aurora_version": aurora_version,
        "aurora_checksum": (aurora_event.get("payload") or {}).get("checksum"),
        "baita_version": int(baita_current[0]),
        "baita_checksum": (baita_event.get("payload") or {}).get("checksum"),
    }


if __name__ == "__main__":
    print(json.dumps(validate(), sort_keys=True))

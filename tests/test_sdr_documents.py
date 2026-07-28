from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services.sdr_documents import compile_persona_documents


def test_baita_markdown_migration_and_publication_counts():
    base = ROOT / "docs" / "sdr" / "baita-conveniencia"
    assert len(list((base / "products").glob("*.md"))) == 383
    graph = compile_persona_documents(ROOT / "docs" / "sdr", "baita-conveniencia")
    counts = Counter(node.node_type for node in graph.nodes)
    assert counts["product_group"] == 15
    assert counts["product"] == 382
    assert counts["copy"] == 17
    assert counts["faq"] == 20
    assert all(
        node.slug != "refrigerantes-sucos-chas-tonica-antarctica-lata-350ml"
        for node in graph.nodes
    )


def test_every_approved_content_node_has_full_markdown_and_chunk_lineage():
    graph = compile_persona_documents(
        ROOT / "docs" / "sdr",
        "baita-conveniencia",
    )
    content_types = {
        "brand",
        "campaign",
        "audience",
        "briefing",
        "tone",
        "rule",
        "product_group",
        "product",
        "copy",
        "faq",
    }
    for node in graph.nodes:
        if node.node_type not in content_types:
            continue
        assert str(node.data.get("markdown") or "").strip(), node.id
        assert node.data.get("source"), node.id
        assert node.data.get("source_file"), node.id
        assert node.data.get("source_checksum"), node.id
        assert node.data.get("rag_chunk", {}).get("checksum"), node.id


def test_every_faq_has_one_secondary_embedded_edge():
    graph = compile_persona_documents(
        ROOT / "docs" / "sdr",
        "baita-conveniencia",
    )
    faq_ids = {node.id for node in graph.nodes if node.node_type == "faq"}
    embedded_ids = {
        node.id for node in graph.nodes if node.node_type == "embedded"
    }
    links = [
        edge
        for edge in graph.edges
        if edge.source in faq_ids and edge.target in embedded_ids
    ]
    assert len(links) == len(faq_ids) == 20
    assert all(edge.primary_tree is False for edge in links)

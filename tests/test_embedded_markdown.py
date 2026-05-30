"""Embedded Markdown builder + FAQ branch-markdown context (pure logic)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


# ── Embedded markdown builder ────────────────────────────────────────────────

def test_build_embedded_markdown_lists_all_connected_faqs():
    from services import embedded_markdown as em

    md = em.build_embedded_markdown(
        "AllanVvz",
        [
            {"question": "Como comprar Plantaris?", "answer": "Fale com a loja.", "node_label": "Produto Plantaris", "source_url": "http://x", "parent_type": "product"},
            {"question": "Como comprar Juliet?", "answer": "Confirme estoque.", "node_label": "Produto Juliet", "parent_type": "product"},
        ],
    )
    assert md.startswith("# Embedded — AllanVvz")
    assert "## FAQs conectadas" in md
    assert "### Como comprar Plantaris?" in md
    assert "Resposta: Fale com a loja." in md
    assert "* Node: Produto Plantaris" in md
    assert "* Source URL: http://x" in md
    assert "* Parent type: product" in md
    assert "### Como comprar Juliet?" in md


def test_build_embedded_markdown_empty():
    from services import embedded_markdown as em

    md = em.build_embedded_markdown("AllanVvz", [])
    assert "Nenhuma FAQ conectada" in md


def test_answer_extraction_from_content():
    from services import embedded_markdown as em

    assert em._answer_from_content("Pergunta: X\nResposta: Y aqui") == "Y aqui"
    assert em._answer_from_content("texto solto") == "texto solto"


# ── FAQ generation reads branch markdown ─────────────────────────────────────

def test_generation_uses_branch_markdown():
    from services import sofia_faq_tool as t

    nodes = [
        {"id": "b1", "node_type": "brand", "title": "VZ Lupas"},
        {"id": "p1", "node_type": "product", "title": "Plantaris Matte Sand", "metadata": {"markdown": "Lente Prizm polarizada com proteção UV400."}},
        {"id": "f1", "node_type": "faq", "title": "Como comprar?"},
    ]
    edges = [
        {"source_node_id": "b1", "target_node_id": "p1", "metadata": {"active": True}},
        {"source_node_id": "p1", "target_node_id": "f1", "metadata": {"active": True}},
    ]
    faq = nodes[2]
    out = t.adaptar_faqs_universais_ao_grafo(target_node=faq, nodes=nodes, edges=edges, count=3)

    # parent resolves to the product, and its markdown flows into context + answer
    assert out["parent_node_id"] == "p1"
    assert "Lente Prizm polarizada" in out["source_context"]["branch_markdown"]
    assert "Lente Prizm polarizada" in out["suggestions"][0]["answer"]
    assert "Plantaris Matte Sand" in out["suggestions"][0]["question"]

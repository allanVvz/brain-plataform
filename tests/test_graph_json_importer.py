from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from services.graph_json_importer import normalized_plan_to_graph_json
from services.graph_json_v2_validator import validate_graph_json


def _plan() -> dict:
    # Persona -> Brand -> Campaign -> Audience -> Product Group -> Product -> Copy -> FAQ
    return {
        "persona_slug": "allanvvz",
        "entries": [
            {"content_type": "brand", "title": "VZ Lupas", "slug": "vz-lupas",
             "content": "Marca de lupas.", "metadata": {"parent_slug": "self"}},
            {"content_type": "campaign", "title": "Coleção Inverno", "slug": "colecao-inverno",
             "content": "Campanha.", "metadata": {"parent_slug": "vz-lupas"}},
            {"content_type": "audience", "title": "Revenda", "slug": "revenda",
             "content": "Público revenda.", "metadata": {"parent_slug": "colecao-inverno"}},
            {"content_type": "product_group", "title": "Radar", "slug": "grupo-radar",
             "content": "Grupo Radar.", "metadata": {"parent_slug": "revenda"}},
            {"content_type": "product", "title": "Radar EV", "slug": "radar-ev",
             "content": "Produto Radar EV.", "metadata": {"parent_slug": "grupo-radar"}},
            {"content_type": "copy", "title": "Copy Radar", "slug": "copy-radar",
             "content": "Copy de venda.", "metadata": {"parent_slug": "radar-ev"}},
            {"content_type": "faq", "title": "FAQ Radar", "slug": "faq-radar",
             "content": "## Como comprar?\nFale com a marca.",
             "metadata": {"parent_slug": "copy-radar", "generate_via": "branch", "question_count": 3}},
            # Tone is a first-class canonical category and remains in the tree.
            {"content_type": "tone", "title": "Tom de voz", "slug": "tom",
             "content": "Tom amigável.", "metadata": {"parent_slug": "vz-lupas"}},
        ],
        "links": [],
    }


def test_converter_produces_valid_canonical_graph():
    graph = normalized_plan_to_graph_json(_plan(), {"persona_name": "AllanVvz"})
    assert graph.schema_version == "2.0"
    assert graph.persona_slug == "allanvvz"
    # 1 persona + 8 canonical entries.
    assert len(graph.nodes) == 9
    types = {n.node_type for n in graph.nodes}
    assert "tone" in types
    # Every non-persona node has a parent and a primary edge.
    non_persona = [n for n in graph.nodes if n.node_type != "persona"]
    assert all(n.parent_id for n in non_persona)
    primary_targets = {e.target for e in graph.edges if e.primary_tree}
    assert all(n.id in primary_targets for n in non_persona)
    # FAQ carries the inherited-context fields.
    faq = next(n for n in graph.nodes if n.node_type == "faq")
    assert faq.data["source_node_type"] == "copy"
    assert faq.data["branch_path"]
    assert faq.data["markdown_document"] is True
    assert faq.data["question_count"] == 3
    # The whole document passes the canonical validator.
    is_valid, errors = validate_graph_json(graph)
    assert is_valid, errors


def test_converter_roots_orphans_at_persona():
    plan = {
        "persona_slug": "allanvvz",
        "entries": [
            {"content_type": "brand", "title": "Brand", "slug": "brand-x", "content": "x"},
        ],
    }
    graph = normalized_plan_to_graph_json(plan)
    brand = next(n for n in graph.nodes if n.node_type == "brand")
    assert brand.parent_id == "node:persona:allanvvz"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid, errors

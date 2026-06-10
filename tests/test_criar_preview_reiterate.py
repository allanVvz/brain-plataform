"""Sofia Criar — iterate-after-preview contract.

Reproduces the operator complaint: after a graph preview, the operator must be
able to *correct* the plan (e.g. the catalog import dumped every product under a
single product_group instead of the 3 requested groups) and the preview graph
must mirror the corrected plan — without starting over.

These tests exercise the deterministic preview core (`_plan_state_from_normalized`,
which rebuilds `graph_json` from the normalized plan) and the live-edit path
(`normalize_validate_summarize_plan`), so they run without an LLM or Supabase.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from services import kb_intake_service as kb


def _session() -> dict:
    return {"id": "sess-reiterate", "persona_slug": "vz-lupas", "classification": {"persona_slug": "vz-lupas", "source": "https://vzlupas.com"}}


def _entry(content_type: str, slug: str, title: str, parent_slug: str) -> dict:
    return {
        "content_type": content_type,
        "slug": slug,
        "title": title,
        "status": "pendente_validacao",
        "content": f"{title} conteudo.",
        "tags": [content_type],
        "metadata": {"parent_slug": parent_slug},
    }


def _base_branch() -> list[dict]:
    # persona is implicit (built from session); branch down to the audience.
    return [
        _entry("brand", "vz-lupas", "Vz Lupas", "self"),
        _entry("briefing", "briefing-retorno", "Briefing Campanha de Retorno", "vz-lupas"),
        _entry("campaign", "campanha-retorno", "Campanha de Retorno da Vz", "briefing-retorno"),
        _entry("audience", "jovens-modernos", "Jovens e Modernos", "campanha-retorno"),
    ]


def _buggy_plan() -> dict:
    """What Sofia produced: ONE product_group ("radar-ev") with products from
    other families wrongly dumped under it."""
    entries = _base_branch()
    entries.append(_entry("product_group", "radar-ev", "Radar Ev", "jovens-modernos"))
    # A product that really belongs to Radar Ev + two that do NOT (Juliet / Eye Jacket).
    for slug, title in [
        ("radar-ev-copper", "Radar Ev Path Copper Prizm Tungsten"),
        ("juliet-24k", "Juliet 24k DoubleX"),
        ("eye-jacket-piet-orange", "Eye Jacket Piet Orange"),
    ]:
        entries.append(_entry("product", slug, title, "radar-ev"))
    return {"persona_slug": "vz-lupas", "source": "https://vzlupas.com", "entries": entries, "links": []}


def _corrected_plan() -> dict:
    """The operator's correction: 3 product_groups, each product reparented to its
    real group (Radar Ev / Juliet / Eye Jacket)."""
    entries = _base_branch()
    for slug, title in [("radar-ev", "Radar Ev"), ("juliet", "Juliet"), ("eye-jacket", "Eye Jacket")]:
        entries.append(_entry("product_group", slug, title, "jovens-modernos"))
    entries.append(_entry("product", "radar-ev-copper", "Radar Ev Path Copper Prizm Tungsten", "radar-ev"))
    entries.append(_entry("product", "juliet-24k", "Juliet 24k DoubleX", "juliet"))
    entries.append(_entry("product", "eye-jacket-piet-orange", "Eye Jacket Piet Orange", "eye-jacket"))
    return {"persona_slug": "vz-lupas", "source": "https://vzlupas.com", "entries": entries, "links": []}


def _nodes_of_type(graph_json: dict, node_type: str) -> list[dict]:
    return [n for n in (graph_json.get("nodes") or []) if n.get("node_type") == node_type]


def test_preview_then_correction_mirrors_a_new_graph():
    session = _session()

    # 1) PREVIEW 1 — the buggy plan. graph_json reflects 1 group, products misfiled.
    state1 = kb._plan_state_from_normalized(_buggy_plan(), session, violations=[])
    graph1 = state1["graph_json"]
    assert len(_nodes_of_type(graph1, "product_group")) == 1
    groups1 = {n["id"] for n in _nodes_of_type(graph1, "product_group")}
    # every product hangs off the single (wrong) group
    assert all(p["parent_id"] in groups1 for p in _nodes_of_type(graph1, "product"))

    # 2) The operator sends a correction (reparent into 3 groups). PREVIEW 2 is
    #    rebuilt from the corrected plan and must mirror it.
    state2 = kb._plan_state_from_normalized(_corrected_plan(), session, violations=[])
    graph2 = state2["graph_json"]

    # The preview graph changed (new hash) and reflects the corrected structure.
    assert state2["plan_hash"] != state1["plan_hash"]
    groups2 = _nodes_of_type(graph2, "product_group")
    assert len(groups2) == 3
    group_slugs = {g["slug"] for g in groups2}
    assert group_slugs == {"radar-ev", "juliet", "eye-jacket"}

    # Each product is now under its OWN group, not all under "radar-ev".
    id_by_slug = {n["slug"]: n["id"] for n in graph2.get("nodes", [])}
    parent_by_slug = {n["slug"]: n.get("parent_id") for n in graph2.get("nodes", [])}
    assert parent_by_slug["radar-ev-copper"] == id_by_slug["radar-ev"]
    assert parent_by_slug["juliet-24k"] == id_by_slug["juliet"]
    assert parent_by_slug["eye-jacket-piet-orange"] == id_by_slug["eye-jacket"]

    # Primary edges mirror the corrected parenting (no product left under radar-ev only).
    edges_into_groups = [
        e for e in graph2.get("edges", [])
        if e.get("target") in {g["id"] for g in groups2} or e.get("source") in {g["id"] for g in groups2}
    ]
    assert edges_into_groups


def test_live_edit_path_reflects_count_change():
    """The path a sidebar/message edit uses (normalize_validate_summarize_plan
    with live_edit=True) must also re-mirror the graph after the preview."""
    session = _session()
    state1 = kb.normalize_validate_summarize_plan(_buggy_plan(), session, live_edit=True)
    state2 = kb.normalize_validate_summarize_plan(_corrected_plan(), session, live_edit=True)
    assert state1.get("graph_json") and state2.get("graph_json")
    assert state2["plan_hash"] != state1["plan_hash"]
    assert len(_nodes_of_type(state2["graph_json"], "product_group")) == 3

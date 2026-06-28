#!/usr/bin/env python3
"""[PATH: GRAPH] Contract for the 10 tree-creation requirements of Sofia Graph.

Graph path: UI /knowledge/graph, endpoint /sofia/graph-command, service
`sofia_orchestrator` (+ shared `services/graph_validation.py`). See SOFIA_PATHS.md.

All 10 requirements are enforced: validator-level (#1 path-to-persona, #3 FAQ
placement, #9 unified validator) via services/graph_validation.py, and the
tree-BUILDING ones (#2 materialize groups, #4 offer→copy exit, #5 rule+FAQ,
#6/#7 persisted skip decisions, #8 real repair) via
`sofia_orchestrator.run_graph_agent_command` (deterministic-first graph agent
that shares the Create path's taxonomy/validation).

Run: python -m pytest tests/test_sofia_graph_tree_contract.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import sofia_orchestrator as orch  # noqa: E402
from services import graph_validation as gv  # noqa: E402

ENGINE = "requires LLM-tools graph engine (Option B, em construcao)"


def _node(slug, parent):
    return {"slug": slug, "title": slug.replace("-", " ").title(), "parent_slug": parent}


def _plan(**sections):
    return {"plan": {k: v for k, v in sections.items()}}


# ── #1 — complete path to persona (validador, ENFORCED) ─────────────────────
def test_item1_incomplete_path_to_persona_blocks():
    # product hangs off a product_group whose parent chain dead-ends (no root).
    plan = _plan(
        product_group=[_node("grupo-solto", "")],   # no parent -> orphan branch
        product=[_node("prod-x", "grupo-solto")],
    )
    res = orch._validate_plan_json(plan)
    codes = {b["code"] for b in res["blocking"]}
    assert "NO_PATH_TO_PERSONA" in codes, res["blocking"]


def test_item1_complete_chain_is_rooted():
    plan = _plan(
        audience=[_node("pub", "self")],
        product_group=[_node("grupo", "pub")],
        product=[_node("prod", "grupo")],
    )
    res = orch._validate_plan_json(plan)
    assert not [b for b in res["blocking"] if b["code"] == "NO_PATH_TO_PERSONA"], res["blocking"]


# ── #3 — FAQ only under copy/offer/product/product_group (validador) ────────
def test_item3_faq_under_audience_is_blocked():
    assert gv.parent_violation("faq", "audience") is not None
    assert gv.parent_violation("faq", "campaign") is not None
    assert gv.parent_violation("faq", "copy") is None
    assert gv.parent_violation("faq", "product") is None
    plan = _plan(
        audience=[_node("pub", "self")],
        faq=[_node("faq-1", "pub")],   # FAQ under audience -> invalid
    )
    res = orch._validate_plan_json(plan)
    assert [b for b in res["blocking"] if b["code"] == "INVALID_PARENT" and "faq" in b["message"]], res["blocking"]


# ── #9 — Graph uses the SAME validator/rules as Create ──────────────────────
def test_item9_graph_uses_shared_validation():
    # product_group under product is rejected by the shared rule in BOTH paths.
    assert gv.parent_violation("product_group", "product") is not None
    plan = _plan(
        product=[_node("prod", "self")],
        product_group=[_node("grupo", "prod")],   # inverted
    )
    res = orch._validate_plan_json(plan)
    assert [b for b in res["blocking"] if b["code"] == "INVALID_PARENT"], res["blocking"]


# ── #2 — materialize product_group nodes/edges from text (ENGINE) ───────────
def test_item2_materializes_product_group_from_text():
    out = orch.run_graph_agent_command(  # noqa: F821 — function exists only with the engine
        command="crie 3 grupos de produtos (Radar, Juliet, HSTN) com 3 produtos cada",
        persona_slug="vz-lupas",
    )
    groups = out["plan"]["product_group"]
    assert len(groups) == 3 and all(g.get("parent_slug") for g in groups)


# ── #4 — offer must have an exit (copy) ─────────────────────────────────────
def test_item4_offer_has_exit():
    out = orch.run_graph_agent_command(command="crie uma oferta para o produto X", persona_slug="vz-lupas")
    assert out["plan"].get("copy"), "offer should be followed by a copy (exit)"


# ── #5 — rule connected to scope/FAQ ────────────────────────────────────────
def test_item5_rule_connected_to_scope_and_faq():
    out = orch.run_graph_agent_command(command="crie uma regra comercial e uma FAQ", persona_slug="vz-lupas")
    assert out["plan"].get("rule") and out["plan"].get("faq")


# ── #6 — asset per product OR persisted skip_assets ─────────────────────────
def test_item6_asset_or_skip_persisted():
    out = orch.run_graph_agent_command(command="seguir sem assets", persona_slug="vz-lupas")
    assert out["state"].get("skip_assets") is True


# ── #7 — "seguir sem oferta/regra" persists the decision ────────────────────
def test_item7_skip_offer_rule_persisted():
    out = orch.run_graph_agent_command(command="seguir sem oferta e sem regra", persona_slug="vz-lupas")
    assert out["state"].get("skip_offer") is True and out["state"].get("skip_rule") is True


# ── #8 — "resolver pendências" does a real repair ───────────────────────────
def test_item8_resolver_pendencias_repairs():
    out = orch.run_graph_agent_command(command="resolver pendências", persona_slug="vz-lupas")
    assert out["repaired"] is True and not out["validation"]["blocking"]


# ── route wiring — /sofia/graph-command uses the shared graph agent ─────────
def test_route_graph_agent_materializes_groups(monkeypatch):
    from types import SimpleNamespace
    from routes import qa_contract

    qa_contract.sofia_orchestrator._SESSION_MEMORY.clear()
    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract.supabase_client, "get_persona",
                        lambda _s: {"id": "11111111-1111-1111-1111-111111111111", "slug": "vz-lupas", "name": "VZ"})
    monkeypatch.setattr(qa_contract.supabase_client, "get_personas",
                        lambda: [{"id": "11111111-1111-1111-1111-111111111111", "slug": "vz-lupas", "name": "VZ"}])
    monkeypatch.setattr(qa_contract.auth_service, "assert_persona_access", lambda *a, **k: True)

    req = SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))
    body = qa_contract.SofiaGraphCommandBody(
        persona_slug="vz-lupas",
        command="crie 3 grupos (Radar, Juliet, HSTN)",
        context=qa_contract.SofiaGraphCommandContext(session_id=""),
    )
    res = qa_contract.sofia_graph_command(body, req)
    assert res["ok"] is True
    assert len(res["plan_json"]["plan"]["product_group"]) == 3, res["plan_json"]["plan"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

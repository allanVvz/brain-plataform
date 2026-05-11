#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import graph as graph_route
from services import kb_intake_service as svc
from services import knowledge_graph


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def entry(content_type: str, slug: str, title: str, parent_slug: str = "", content: str = "") -> dict:
    metadata = {"parent_slug": parent_slug} if parent_slug else {}
    return {
        "content_type": content_type,
        "title": title,
        "slug": slug,
        "status": "pendente_validacao",
        "content": content or title,
        "tags": [content_type],
        "metadata": metadata,
    }


def parent_slug(item: dict) -> str:
    return str((item.get("metadata") or {}).get("parent_slug") or "")


def make_session() -> dict:
    session = svc.create_session(
        model="gpt-4o-mini",
        initial_context=(
            "Persona: Tock Fatal\n"
            "Fonte: https://tockfatal.com\n"
            "Audiencia padrao existente.\n"
            "Produtos: Kit Modal 5 Pecas e Kit Modal 10 Pecas.\n"
            "Copy: Nesse inverno temos as roupas mais elegantes.\n"
            "FAQ: 2 FAQs por produto/oferta.\n"
            "Regra: foco em empreendedoras.\n"
        ),
        initial_state={
            "mode": "criar",
            "persona_slug": "tock-fatal",
            "source_url": "https://tockfatal.com",
            "initial_block_counts": {"briefing": 1, "audience": 1, "product": 2, "offer": 2, "copy": 2, "faq": 4, "rule": 1},
        },
    )
    session["classification"]["persona_slug"] = "tock-fatal"
    session["classification"]["content_type"] = "faq"
    session["classification"]["title"] = "Tock Fatal inverno"
    svc._save_session(session)  # type: ignore[attr-defined]
    return session


def raw_plan() -> dict:
    return {
        "source": "https://tockfatal.com",
        "persona_slug": "tock-fatal",
        "validation_policy": "human_validation_required",
        "tree_mode": "single_branch",
        "branch_policy": "single_branch_by_default",
        "faq_count_policy": "total",
        "entries": [
            entry("briefing", "briefing-tock-fatal", "Briefing Tock Fatal", "self"),
            entry("audience", "publico-tock-fatal", "Empreendedoras Tock Fatal", "briefing-tock-fatal", "Publico empreendedor e revendedor."),
            entry("product", "kit-modal-5-pecas", "Kit Modal 5 Pecas", "publico-tock-fatal"),
            entry("product", "kit-modal-10-pecas", "Kit Modal 10 Pecas", "publico-tock-fatal"),
            entry("copy", "copy-inverno", "Copy inverno", "kit-modal-5-pecas", "Nesse inverno temos as roupas mais elegantes."),
            entry("faq", "faq-kit-modal-5", "Qual o valor do Kit Modal 5 Pecas?", "copy-inverno", "Confirmar preco antes de publicar."),
            entry("faq", "faq-kit-modal-10", "Qual o valor do Kit Modal 10 Pecas?", "copy-inverno", "Confirmar preco antes de publicar."),
            entry("rules", "rules-foco-empreendedoras", "Foco em empreendedoras", "", "Priorizar linguagem para empreendedoras."),
        ],
        "links": [],
    }


def assert_chain(entries: list[dict], child_type: str, expected_parent_type: str) -> None:
    by_slug = {str(item.get("slug")): item for item in entries if item.get("slug")}
    for item in [entry for entry in entries if entry.get("content_type") == child_type]:
        parent = by_slug.get(parent_slug(item))
        expect(parent and parent.get("content_type") == expected_parent_type, f"{child_type} stays below {expected_parent_type}")


def main() -> int:
    session = make_session()
    plan_state = svc.normalize_validate_summarize_plan(raw_plan(), session)
    normalized = plan_state["normalized_plan"]
    entries = normalized["entries"]
    counts = svc.count_blocks_by_type(entries)

    expect(len(entries) > 0, "normalizedPlan has entries")
    expect(plan_state["validation"]["valid"] is True, "normalizedPlan validates before preview/save")
    expect(counts == plan_state["summary"]["current_block_counts"], "summary counts come from normalizedPlan")
    expect(counts["offer"] > 0, "price/quantity materializes explicit offers")
    expect(counts["rule"] >= 1, "commercial rule is generated")
    expect(all(item.get("content_type") != "rules" for item in entries), "rules alias is normalized to rule")
    assert_chain(entries, "offer", "product")
    assert_chain(entries, "copy", "offer")
    assert_chain(entries, "faq", "copy")

    by_slug = {str(item.get("slug")): item for item in entries if item.get("slug")}
    for rule in [item for item in entries if item.get("content_type") == "rule"]:
        governing_parent = by_slug.get(parent_slug(rule))
        expect(governing_parent and governing_parent.get("content_type") in {"briefing", "campaign", "brand"}, "rule is attached to governing scope")

    expect(knowledge_graph._CONTENT_TYPE_TO_NODE.get("offer") == "offer", "knowledge_items.content_type=offer maps to node_type=offer")
    expect(knowledge_graph._tipo_to_node_type("oferta") == "offer", "legacy tipo oferta maps to offer")

    original_get_item = graph_route.supabase_client.get_knowledge_item
    try:
        graph_route.supabase_client.get_knowledge_item = lambda item_id: {"id": item_id, "content_type": "offer"}  # type: ignore[method-assign]
        repaired = graph_route._canonicalize_semantic_node_types(
            [{"id": "n-offer", "source_table": "knowledge_items", "source_id": "ki-offer", "node_type": "knowledge_item", "metadata": {}}],
            {"offer": {"default_level": 35, "default_importance": 0.78}},
        )
    finally:
        graph_route.supabase_client.get_knowledge_item = original_get_item  # type: ignore[method-assign]
    expect(repaired[0]["node_type"] == "offer", "graph-data repairs stale offer mirror node type")
    expect(repaired[0]["metadata"]["content_type"] == "offer", "graph-data preserves repaired offer content_type")

    demoted = graph_route._demote_auxiliary_primary_edges(
        [{"id": "e-tag", "source_node_id": "persona", "target_node_id": "tag", "metadata": {"primary_tree": True}}],
        {"persona": {"node_type": "persona"}, "tag": {"node_type": "tag"}},
    )
    meta = demoted[0]["metadata"]
    expect(meta["primary_tree"] is False and meta["graph_layer"] == "auxiliary" and meta["visual_hidden"] is True, "tag edges are demoted out of primary tree")

    migration_sql = (ROOT / "supabase" / "migrations" / "031_allow_offer_content_type.sql").read_text(encoding="utf-8")
    expect("node_type = 'offer'" in migration_sql and "repaired_from_node_type" in migration_sql, "migration backfills offer node_type")
    expect("src.node_type IN ('tag', 'mention', 'knowledge_item', 'kb_entry')" in migration_sql and "'{primary_tree}'" in migration_sql, "migration demotes auxiliary/technical primary edges")

    graph_view = (ROOT / "dashboard" / "components" / "graph" / "GraphView.tsx").read_text(encoding="utf-8")
    expect("offer: 6" in graph_view, "visual rank places offer between product and copy")
    expect("terminalShift" in graph_view, "embedded and gallery render as terminal destinations, not a chained branch")

    prompt_source = (ROOT / "api" / "services" / "kb_intake_service.py").read_text(encoding="utf-8")
    expect("explorar -> confirmar -> montar normalizedPlan -> validar -> resumir curto" in prompt_source, "Sofia prompt uses explore/confirm/normalize contract")
    expect("faq_count_policy = total" in prompt_source, "prompt defaults FAQ policy to total")

    print("PASS e2e_criar_visual_branch_integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
smoke_knowledge_graph.py
========================

Pure-Python tests (no DB) that exercise the inference logic of
services/knowledge_graph.py. They monkey-patch the supabase client so the
graph layer can be exercised without needing migration 008 to be applied.

Run: python -m tests.smoke_knowledge_graph
"""
from __future__ import annotations

import sys
import re
from typing import Optional


# ── Fake supabase backend ─────────────────────────────────────────────────

class _FakeStore:
    """In-memory stand-in for knowledge_nodes + knowledge_edges + helpers."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}                # id -> node row
        self.edges: dict[tuple, dict] = {}              # (src, tgt, rel) -> row
        self.kb_entries: dict[str, dict] = {}           # id -> kb_entry
        self.messages_by_ref: dict[str, list[dict]] = {}
        self._next_node_id = 0
        self._next_edge_id = 0

    # mimic supabase_client.upsert_knowledge_node
    def upsert_knowledge_node(self, data: dict) -> dict:
        key = (data.get("persona_id"), data["node_type"], data["slug"])
        for n in self.nodes.values():
            if (n.get("persona_id"), n["node_type"], n["slug"]) == key:
                n["title"] = data.get("title") or n["title"]
                n["summary"] = data.get("summary") or n.get("summary")
                merged_tags = sorted(set((n.get("tags") or []) + (data.get("tags") or [])))
                n["tags"] = merged_tags
                merged_meta = {**(n.get("metadata") or {}), **(data.get("metadata") or {})}
                n["metadata"] = merged_meta
                if data.get("source_table"):
                    n["source_table"] = data["source_table"]
                if data.get("source_id"):
                    n["source_id"] = data["source_id"]
                if data.get("status"):
                    n["status"] = data["status"]
                return n
        self._next_node_id += 1
        nid = f"n{self._next_node_id}"
        row = {
            "id": nid,
            "persona_id": data.get("persona_id"),
            "node_type": data["node_type"],
            "slug": data["slug"],
            "title": data.get("title") or data["slug"],
            "summary": data.get("summary"),
            "tags": data.get("tags") or [],
            "metadata": data.get("metadata") or {},
            "status": data.get("status") or "active",
            "source_table": data.get("source_table"),
            "source_id": data.get("source_id"),
        }
        self.nodes[nid] = row
        return row

    def upsert_knowledge_edge(self, src: str, tgt: str, rel: str, **kw) -> dict:
        if not src or not tgt or src == tgt:
            return {}
        key = (src, tgt, rel)
        if key in self.edges:
            return self.edges[key]
        self._next_edge_id += 1
        row = {"id": f"e{self._next_edge_id}", "source_node_id": src, "target_node_id": tgt, "relation_type": rel}
        row.update({k: v for k, v in kw.items() if v is not None})
        self.edges[key] = row
        return row

    def find_knowledge_nodes(self, term: str, persona_id=None, node_types=None, limit=25) -> list[dict]:
        if not term:
            return []
        norm = term.strip().lower()
        slug_norm = norm.replace(" ", "-")
        out = []
        for n in self.nodes.values():
            if persona_id and n.get("persona_id") != persona_id:
                continue
            if node_types and n.get("node_type") not in node_types:
                continue
            slug_l = (n.get("slug") or "").lower()
            title_l = (n.get("title") or "").lower()
            tags_l = [t.lower() for t in (n.get("tags") or [])]
            if slug_l == slug_norm or norm in title_l or norm in tags_l:
                out.append(n)
        return out[:limit]

    def get_knowledge_neighbors(self, ids: list[str], max_edges=200) -> tuple[list[dict], list[dict]]:
        ids_set = set(ids or [])
        edges = [e for e in self.edges.values()
                 if e["source_node_id"] in ids_set or e["target_node_id"] in ids_set][:max_edges]
        related: set[str] = set(ids_set)
        for e in edges:
            related.add(e["source_node_id"])
            related.add(e["target_node_id"])
        nodes = [self.nodes[i] for i in related if i in self.nodes]
        return nodes, edges

    def list_knowledge_nodes_by_type(self, types, persona_id=None, limit=200) -> list[dict]:
        out = []
        for n in self.nodes.values():
            if n.get("node_type") in types:
                if persona_id and n.get("persona_id") != persona_id:
                    continue
                out.append(n)
        return out[:limit]

    def list_all_knowledge_graph(self, persona_id=None, limit_nodes=1500):
        nodes = list(self.nodes.values())
        if persona_id:
            nodes = [n for n in nodes if n.get("persona_id") == persona_id]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.edges.values()
                 if e["source_node_id"] in node_ids or e["target_node_id"] in node_ids]
        return nodes[:limit_nodes], edges

    def get_kb_entry(self, entry_id: str) -> Optional[dict]:
        return self.kb_entries.get(entry_id)

    def get_messages(self, lead_id: str, limit: int = 30) -> list[dict]:
        return self.messages_by_ref.get(str(lead_id), [])[:limit]


def _install_fake_supabase(store: _FakeStore) -> None:
    """Replace supabase_client functions with the fake store's methods."""
    from services import supabase_client as sb
    sb.upsert_knowledge_node = store.upsert_knowledge_node      # type: ignore[attr-defined]
    sb.upsert_knowledge_edge = store.upsert_knowledge_edge      # type: ignore[attr-defined]
    sb.find_knowledge_nodes = store.find_knowledge_nodes        # type: ignore[attr-defined]
    sb.get_knowledge_neighbors = store.get_knowledge_neighbors  # type: ignore[attr-defined]
    sb.list_knowledge_nodes_by_type = store.list_knowledge_nodes_by_type  # type: ignore[attr-defined]
    sb.list_all_knowledge_graph = store.list_all_knowledge_graph  # type: ignore[attr-defined]
    sb.get_kb_entry = store.get_kb_entry                        # type: ignore[attr-defined]
    sb.get_messages = store.get_messages                        # type: ignore[attr-defined]


# ── Tests ─────────────────────────────────────────────────────────────────

def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)


def test_helpers():
    from services.knowledge_graph import _slugify, _normalize_tags

    _assert(_slugify("Inverno 2026") == "inverno-2026", "slugify spaces")
    _assert(_slugify("Modal!") == "modal", "slugify symbols")

    _assert(_normalize_tags("modal,inverno") == ["modal", "inverno"], "tags csv")
    _assert(_normalize_tags(["Modal", "INVERNO"]) == ["modal", "inverno"], "tags list lowercased")
    _assert(_normalize_tags(None) == [], "tags none")
    _assert(_normalize_tags('["modal","inverno"]') == ["modal", "inverno"], "tags jsonb-string")
    print("OK helpers")


def test_bootstrap_product_campaign_fixture():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph
    knowledge_graph.logger.setLevel("WARNING")

    persona_id = "p-tock-fatal"
    item = {
        "id": "ki-1",
        "title": "Modal — Briefing",
        "content_type": "product",
        "content": "Detalhes sobre o produto Modal e a campanha Inverno 2026.",
        "file_path": "TOCK_FATAL/produtos/modal.md",
        "tags": ["modal", "produto"],
    }
    fm = {"product": "modal", "campaigns": ["inverno-2026"], "type": "product"}
    knowledge_graph.bootstrap_from_item(item, fm, item["content"], persona_id=persona_id)

    products = store.list_knowledge_nodes_by_type(["product"], persona_id)
    campaigns = store.list_knowledge_nodes_by_type(["campaign"], persona_id)
    _assert(any(p["slug"] == "modal" for p in products), "product:modal node created")
    _assert(any(c["slug"] == "inverno-2026" for c in campaigns), "campaign:inverno-2026 created")

    # Edge product:modal -> campaign:inverno-2026 part_of_campaign
    modal = next(p for p in products if p["slug"] == "modal")
    inverno = next(c for c in campaigns if c["slug"] == "inverno-2026")
    _assert(
        (modal["id"], inverno["id"], "part_of_campaign") in store.edges,
        "part_of_campaign edge exists",
    )
    print("OK bootstrap_product_campaign_fixture")


def test_bootstrap_asset():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph

    persona_id = "p-tock-fatal"
    item = {
        "id": "asset-1",
        "title": "Modal Inverno Hero",
        "content_type": "asset",
        "content": "[asset: hero-modal.png]",
        "file_path": "TOCK_FATAL/assets/hero-modal.png",
        "asset_type": "product",
        "asset_function": "campaign_hero",
        "tags": ["modal", "inverno-2026", "asset"],
    }
    fm = {"product": "modal", "campaigns": ["inverno-2026"], "type": "asset"}
    knowledge_graph.bootstrap_from_item(item, fm, "", persona_id=persona_id)

    # Asset node exists
    asset_nodes = store.list_knowledge_nodes_by_type(["asset"], persona_id)
    _assert(any(a["title"] == "Modal Inverno Hero" for a in asset_nodes), "asset node created")
    asset = next(a for a in asset_nodes if a["title"] == "Modal Inverno Hero")

    # campaign supports_campaign edge from asset → campaign
    inverno = next(c for c in store.list_knowledge_nodes_by_type(["campaign"], persona_id) if c["slug"] == "inverno-2026")
    _assert(
        (asset["id"], inverno["id"], "supports_campaign") in store.edges,
        "asset supports_campaign edge",
    )
    # product uses_asset edge from product → asset
    modal = next(p for p in store.list_knowledge_nodes_by_type(["product"], persona_id) if p["slug"] == "modal")
    _assert(
        (modal["id"], asset["id"], "uses_asset") in store.edges,
        "product uses_asset edge points product→asset",
    )
    print("OK bootstrap_asset")


def test_idempotency():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph

    persona_id = "p-tock-fatal"
    item = {
        "id": "ki-2",
        "title": "Modal",
        "content_type": "product",
        "content": "Modal Inverno 2026",
        "file_path": "x/modal.md",
        "tags": ["modal"],
    }
    fm = {"product": "modal", "campaigns": ["inverno-2026"]}

    knowledge_graph.bootstrap_from_item(item, fm, item["content"], persona_id=persona_id)
    n1 = len(store.nodes)
    e1 = len(store.edges)

    knowledge_graph.bootstrap_from_item(item, fm, item["content"], persona_id=persona_id)
    knowledge_graph.bootstrap_from_item(item, fm, item["content"], persona_id=persona_id)
    _assert(len(store.nodes) == n1, f"nodes idempotent: {len(store.nodes)} != {n1}")
    _assert(len(store.edges) == e1, f"edges idempotent: {len(store.edges)} != {e1}")
    print("OK idempotency")


def _seed_full_modal_persona(store: _FakeStore, persona_id: str = "p-tock-fatal") -> None:
    """Idempotently bootstrap product+campaign+faq+copy+2 assets for tests."""
    from services import knowledge_graph
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-prod", "title": "Modal", "content_type": "product",
         "content": "Modal Inverno 2026", "file_path": "TOCK_FATAL/produtos/modal.md",
         "tags": ["modal", "produto", "inverno-2026"]},
        {"product": "modal", "campaigns": ["inverno-2026"], "type": "product"},
        "Modal Inverno 2026",
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-camp", "title": "Inverno 2026", "content_type": "campaign",
         "content": "Lançamento de inverno", "file_path": "TOCK_FATAL/campanhas/inverno-2026.md",
         "tags": ["inverno-2026", "modal", "campanha"]},
        {"campaign": "inverno-2026", "product": "modal", "type": "campaign"},
        "Inverno 2026 modal",
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-faq", "title": "Modal vale a pena para o inverno?",
         "content_type": "faq", "content": "Sim, o modal é leve e respira",
         "file_path": "TOCK_FATAL/faq/modal-vale-a-pena.md",
         "tags": ["modal", "inverno-2026", "faq"]},
        {"product": "modal", "campaigns": ["inverno-2026"], "type": "faq"},
        "Sim, o modal é leve",
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-copy", "title": "Modal Inverno — Copy Hero",
         "content_type": "copy", "content": "Conforto que cai bem.",
         "file_path": "TOCK_FATAL/copies/modal-inverno-hero.md",
         "tags": ["modal", "inverno-2026", "copy"]},
        {"product": "modal", "campaigns": ["inverno-2026"], "type": "copy"},
        "Modal Tock Fatal toque de seda",
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-hero", "title": "Hero Modal Inverno", "content_type": "asset",
         "content": "[asset]", "file_path": "hero-modal-inverno.png",
         "asset_type": "product", "asset_function": "campaign_hero",
         "tags": ["modal", "inverno-2026", "asset"]},
        {"product": "modal", "campaigns": ["inverno-2026"], "type": "asset"},
        "",
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-banner", "title": "Banner Story Modal Inverno",
         "content_type": "asset", "content": "[asset]",
         "file_path": "banner-modal-story.jpg",
         "asset_type": "banner", "asset_function": "copy_support",
         "tags": ["modal", "inverno-2026", "asset", "banner"]},
        {"product": "modal", "campaigns": ["inverno-2026"], "type": "asset"},
        "",
        persona_id=persona_id,
    )


def test_chat_context_q_modal():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph
    _seed_full_modal_persona(store)
    persona_id = "p-tock-fatal"

    ctx = knowledge_graph.get_chat_context(
        lead_ref=None, persona_id=persona_id,
        user_text="Quero saber sobre o Modal",
    )
    _assert("Modal" in ctx["query_terms"], f"Modal detected in terms: {ctx['query_terms']}")
    _assert("entities" in ctx, "entities key present in response")
    entity_slugs = {e.get("slug") for e in ctx["entities"]}
    _assert("modal" in entity_slugs, f"product:modal in entities: {entity_slugs}")
    _assert(ctx.get("intent") == "product_inquiry", f"intent should be product_inquiry, got {ctx.get('intent')}")

    found_types = {n["node_type"] for n in ctx["nodes"]}
    _assert("product" in found_types, f"product node returned: {found_types}")
    _assert("campaign" in found_types, f"campaign node returned: {found_types}")
    _assert("faq" in found_types or any(e.get("tipo") == "faq" or e.get("node_type") == "faq" for e in ctx["kb_entries"]),
            "FAQ surfaced in nodes or kb_entries")
    _assert(len(ctx["assets"]) >= 1, "asset returned in bundle")

    rels = {e.get("relation_type") for e in ctx["edges"]}
    _assert("part_of_campaign" in rels, f"part_of_campaign present: {rels}")
    _assert("answers_question" in rels, f"answers_question present: {rels}")
    _assert("supports_copy" in rels, f"supports_copy present: {rels}")
    _assert("supports_campaign" in rels, f"supports_campaign present: {rels}")
    print("OK chat_context_q_modal")


def test_modal_subnodes_from_simplified_knowledge():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph

    persona_id = "p-tock-fatal"
    faq_content = """
Pergunta: Voces sao fabricantes ou so revendem?
Resposta: Somos fabricantes de malhas modais, o que ajuda a manter boa qualidade e preco competitivo.

Pergunta: O que voces tem de modal?
Resposta: Temos pecas em modal para verao e inverno, incluindo modelos para giro rapido no varejo e opcoes em kit para revenda.

Pergunta: O modal de voces e bom para vender?
Resposta: Sim. O modal costuma ter boa aceitacao por unir conforto, caimento e facilidade de combinacao no dia a dia.
"""
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-faq-simple", "title": "Modal FAQ", "content_type": "faq",
         "content": faq_content, "file_path": "TOCK_FATAL/faq/modal.md",
         "tags": ["modal", "faq"], "status": "pending"},
        {"product": "modal", "type": "faq"},
        faq_content,
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-prod-simple", "title": "Modal", "content_type": "product",
         "content": "Produto modal para verao e inverno.", "file_path": "TOCK_FATAL/produtos/modal.md",
         "tags": ["modal", "produto"], "status": "pending"},
        {"product": "modal", "type": "product"},
        "Produto modal para verao e inverno.",
        persona_id=persona_id,
    )
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-briefing-modal", "title": "Briefing Geral", "content_type": "briefing",
         "content": "## Modais - Introducao\nMalhas modais com giro rapido.", "file_path": "TOCK_FATAL/briefing.md",
         "tags": ["modal", "briefing"], "status": "pending"},
        {"product": "modal", "type": "briefing"},
        "## Modais - Introducao\nMalhas modais com giro rapido.",
        persona_id=persona_id,
    )

    slugs = {n["slug"] for n in store.nodes.values()}
    expected_slugs = {
        "modal",
        "modal-voces-sao-fabricantes-ou-so-revendem",
        "modal-o-que-voces-tem-de-modal",
        "modal-o-modal-de-voces-e-bom-para-vender",
        "modais-introducao",
    }
    for slug in expected_slugs:
        _assert(slug in slugs, f"{slug} subnode exists")

    modal = next(n for n in store.nodes.values() if n["node_type"] == "product" and n["slug"] == "modal")
    expected_targets = {
        next(n["id"] for n in store.nodes.values() if n["slug"] == "modal-voces-sao-fabricantes-ou-so-revendem"),
        next(n["id"] for n in store.nodes.values() if n["slug"] == "modal-o-que-voces-tem-de-modal"),
        next(n["id"] for n in store.nodes.values() if n["slug"] == "modal-o-modal-de-voces-e-bom-para-vender"),
        next(n["id"] for n in store.nodes.values() if n["slug"] == "modais-introducao"),
    }
    actual_targets = {tgt for src, tgt, rel in store.edges if src == modal["id"]}
    _assert(expected_targets.issubset(actual_targets), "product:modal links to FAQ and briefing subnodes")

    ctx = knowledge_graph.get_chat_context(
        lead_ref=None,
        persona_id=persona_id,
        user_text="Quero saber mais sobre as malhas. O que voces tem nesse tipo de produto?",
        limit=20,
    )
    ctx_slugs = {n.get("slug") for n in ctx["nodes"]}
    _assert("modal" in {t.lower() for t in ctx["query_terms"]}, f"malhas resolves to modal: {ctx['query_terms']}")
    _assert(expected_targets and (expected_slugs - {"modal"}).issubset(ctx_slugs),
            f"chat context returns all Modal subnodes: {ctx_slugs}")
    _assert(all(n.get("link_target") for n in ctx["nodes"]), "all nodes include link_target")
    _assert(ctx.get("unvalidated", {}).get("nodes"), "pending nodes are exposed separately")
    print("OK modal_subnodes_from_simplified_knowledge")


def test_generic_product_campaign_subnodes():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph

    persona_id = "p-generic-client"
    content = """
Pergunta: O tricot esquenta bem?
Resposta: Sim, o tricot premium foi planejado para dias frios e combina com a campanha Verao 2027.
"""
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-tricot-faq", "title": "Tricot Premium FAQ", "content_type": "faq",
         "content": content, "file_path": "CLIENTE/faq/tricot.md",
         "tags": ["tricot-premium", "faq"], "status": "pending"},
        {"product": "tricot-premium", "campaigns": ["verao-2027"], "type": "faq"},
        content,
        persona_id=persona_id,
    )

    slugs = {n["slug"] for n in store.nodes.values()}
    _assert("tricot-premium" in slugs, "generic product node created")
    _assert("verao-2027" in slugs, "generic campaign node created")
    _assert("tricot-premium-o-tricot-esquenta-bem" in slugs, "generic FAQ subnode created")

    ctx = knowledge_graph.get_chat_context(
        lead_ref=None,
        persona_id=persona_id,
        user_text="Quero detalhes do Tricot Premium para campanha Verao 2027",
    )
    ctx_slugs = {n.get("slug") for n in ctx["nodes"]}
    _assert({"tricot-premium", "verao-2027", "tricot-premium-o-tricot-esquenta-bem"}.issubset(ctx_slugs),
            f"generic chat context resolves product/campaign/subnode: {ctx_slugs}")
    print("OK generic_product_campaign_subnodes")


def test_chat_context_intent_asset_request():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph
    _seed_full_modal_persona(store)

    ctx = knowledge_graph.get_chat_context(
        lead_ref=None, persona_id="p-tock-fatal",
        user_text="Quais imagens do Modal posso usar?",
    )
    _assert(ctx["intent"] == "asset_request", f"intent asset_request, got {ctx['intent']}")
    _assert(len(ctx["assets"]) >= 1, "assets returned for asset_request")
    print("OK chat_context_intent_asset_request")


def test_chat_context_fallback_no_entity():
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph

    ctx = knowledge_graph.get_chat_context(
        lead_ref=None, persona_id="p-tock-fatal",
        user_text="aleatorio sem produto conhecido",
    )
    _assert(ctx["entities"] == [], f"no entities matched: {ctx['entities']}")
    _assert(ctx["intent"] == "fallback_text_search", f"fallback intent, got {ctx['intent']}")
    _assert(ctx["nodes"] == [], "no semantic nodes")
    _assert(ctx["assets"] == [], "no assets")
    print("OK chat_context_fallback_no_entity")


def test_graph_data_fallback_when_empty():
    """When knowledge_nodes is empty, the new /knowledge/graph-data branch
    must add zero semantic nodes — the legacy graph keeps working."""
    store = _FakeStore()
    _install_fake_supabase(store)

    nodes, edges = store.list_all_knowledge_graph()
    _assert(nodes == [] and edges == [], "empty graph returns empty lists")
    print("OK graph_data_fallback")


def test_messages_text_search_modal():
    """Ensure recent-messages-only path also detects Modal."""
    store = _FakeStore()
    _install_fake_supabase(store)
    from services import knowledge_graph

    persona_id = "p-tock-fatal"
    knowledge_graph.bootstrap_from_item(
        {"id": "ki-1", "title": "Modal", "content_type": "product",
         "content": "Modal", "file_path": "modal.md", "tags": ["modal"]},
        {"product": "modal", "campaigns": ["inverno-2026"]},
        "Modal",
        persona_id=persona_id,
    )

    store.messages_by_ref["117"] = [
        {"texto": "Olá! Vocês ainda têm Modal disponível pro inverno?"},
        {"texto": "Achei o produto MODAL na vitrine."},
    ]
    ctx = knowledge_graph.get_chat_context(lead_ref=117, persona_id=persona_id)
    _assert(any(t.lower() == "modal" for t in ctx["query_terms"]),
            f"Modal detected from messages: {ctx['query_terms']}")
    print("OK messages_text_search_modal")


def main():
    test_helpers()
    test_bootstrap_product_campaign_fixture()
    test_bootstrap_asset()
    test_idempotency()
    test_chat_context_q_modal()
    test_modal_subnodes_from_simplified_knowledge()
    test_generic_product_campaign_subnodes()
    test_chat_context_intent_asset_request()
    test_chat_context_fallback_no_entity()
    test_graph_data_fallback_when_empty()
    test_messages_text_search_modal()
    print("\nALL OK")


if __name__ == "__main__":
    main()

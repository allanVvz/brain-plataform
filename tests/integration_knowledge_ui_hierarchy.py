# -*- coding: utf-8 -*-
"""
Offline validation for persona-scoped knowledge sidebar inputs and graph
hierarchy payloads.

This test does not require Supabase or a running backend. It monkeypatches the
Supabase-facing functions and validates:
  - header filter defaults to "Todos" and messages page consumes its persona id;
  - chat-context returns at least one product + FAQ for Tock Fatal and Prime;
  - persona scoping prevents cross-client knowledge leakage;
  - graph-data defaults hide auxiliary tag/mention nodes;
  - graph-data exposes semantic levels, relation tiers, focus and focus_path.

Run:
  python tests/integration_knowledge_ui_hierarchy.py
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _fold(value: str) -> str:
    from services.knowledge_graph import _fold as fold

    return fold(value or "")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ok {msg}")


class FakeKnowledgeStore:
    def __init__(self) -> None:
        self.personas = [
            {"id": "persona-tock", "slug": "tock-fatal", "name": "Tock Fatal"},
            {"id": "persona-prime", "slug": "prime-higienizacao", "name": "Prime Higienizacao"},
        ]
        self.nodes = [
            self.node("tock-persona", "persona-tock", "persona", "self", "Persona", level=0),
            self.node("tock-brand", "persona-tock", "brand", "tock-fatal", "Tock Fatal", level=20),
            self.node("tock-product", "persona-tock", "product", "modal", "Modal", "Produto Modal Tock.", level=40, metadata={"price": {"display": "R$ 199,90"}}),
            self.node("tock-faq", "persona-tock", "faq", "quanto-custa-modal", "Quanto custa Modal?", "Modal custa R$ 199,90.", level=75),
            self.node("tock-tag", "persona-tock", "tag", "modal", "modal", level=90),
            self.node("prime-persona", "persona-prime", "persona", "self", "Persona", level=0),
            self.node("prime-brand", "persona-prime", "brand", "prime-higienizacao", "Prime Higienizacao", level=20),
            self.node(
                "prime-product",
                "persona-prime",
                "product",
                "higienizacao-cadeiras-prime",
                "Higienizacao-Cadeiras-Prime",
                "Higienizacao de Cadeiras Prime. Preco R$ 100,00 por cadeira.",
                level=40,
                metadata={"price": {"display": "R$ 100,00 por cadeira"}},
            ),
            self.node("prime-faq", "persona-prime", "faq", "quanto-custa-higienizacao-de-cadeiras-prime", "Quanto custa Higienizacao de Cadeiras Prime?", "Custa R$ 100,00 por cadeira.", level=75),
            self.node("prime-copy", "persona-prime", "copy", "copy-cadeiras-prime", "Copy Cadeiras Prime", "Atendimento serio e seguro.", level=70),
            self.node("prime-tag", "persona-prime", "tag", "higienizacao-cadeiras-prime", "higienizacao-cadeiras-prime", level=90),
            self.node("prime-mention", "persona-prime", "mention", "prime-cadeiras-mention", "Prime - Cadeiras", level=90),
        ]
        self.edges = [
            self.edge("e-tock-persona-brand", "tock-persona", "tock-brand", "contains", 1, primary=True),
            self.edge("e-tock-brand-product", "tock-brand", "tock-product", "about_product", 0.9, primary=True),
            self.edge("e-tock-product-faq", "tock-product", "tock-faq", "answers_question", 0.9, primary=True),
            self.edge("e-tock-product-tag", "tock-product", "tock-tag", "has_tag", 1),
            self.edge("e-prime-persona-brand", "prime-persona", "prime-brand", "contains", 1, primary=True),
            self.edge("e-prime-brand-product", "prime-brand", "prime-product", "about_product", 0.9, primary=True),
            self.edge("e-prime-product-faq", "prime-product", "prime-faq", "answers_question", 0.9, primary=True),
            self.edge("e-prime-copy-product", "prime-copy", "prime-product", "supports_copy", 0.85),
            self.edge("e-prime-product-tag", "prime-product", "prime-tag", "has_tag", 1),
            self.edge("e-prime-mention-product", "prime-mention", "prime-product", "mentions", 0.4),
        ]
        self.leads = {
            122: {"id": 122, "persona_id": "persona-tock", "interesse_produto": "Modal"},
            125: {"id": 125, "persona_id": "persona-prime", "interesse_produto": "Higienizacao de Cadeiras Prime"},
        }
        self.messages = {
            122: [{"lead_ref": 122, "texto": "Qual o catalogo do Modal?", "sender_type": "user"}],
            125: [{"lead_ref": 125, "texto": "Quanto custa Higienizacao de Cadeiras Prime?", "sender_type": "user"}],
        }

    def node(self, node_id: str, persona_id: str, node_type: str, slug: str, title: str, summary: str = "", level: int = 50, metadata: dict | None = None) -> dict:
        return {
            "id": node_id,
            "persona_id": persona_id,
            "source_table": None,
            "source_id": None,
            "node_type": node_type,
            "slug": slug,
            "title": title,
            "summary": summary,
            "tags": [slug],
            "metadata": metadata or {},
            "status": "active",
            "level": level,
            "importance": 0.9 if node_type in {"persona", "brand", "product"} else 0.65,
            "confidence": 0.9,
        }

    def edge(self, edge_id: str, src: str, tgt: str, rel: str, weight: float, primary: bool = False) -> dict:
        return {
            "id": edge_id,
            "persona_id": self.node_by_id(src)["persona_id"],
            "source_node_id": src,
            "target_node_id": tgt,
            "relation_type": rel,
            "weight": weight,
            "metadata": {"primary_tree": True, "active": True} if primary else {},
        }

    def node_by_id(self, node_id: str) -> dict:
        return next(n for n in self.nodes if n["id"] == node_id)

    def get_personas(self) -> list[dict]:
        return deepcopy(self.personas)

    def get_persona(self, slug: str) -> dict | None:
        row = next((p for p in self.personas if p["slug"] == slug), None)
        return deepcopy(row) if row else None

    def get_lead_by_ref(self, lead_ref: int) -> dict | None:
        return deepcopy(self.leads.get(int(lead_ref)))

    def get_messages(self, lead_id: str, limit: int = 30) -> list[dict]:
        return deepcopy(self.messages.get(int(lead_id), [])[:limit])

    def list_knowledge_nodes_by_type(self, node_types: list[str], persona_id: str | None = None, limit: int = 200) -> list[dict]:
        rows = [n for n in self.nodes if n["node_type"] in node_types]
        if persona_id:
            rows = [n for n in rows if n["persona_id"] == persona_id]
        return deepcopy(rows[:limit])

    def find_knowledge_nodes(self, term: str, persona_id: str | None = None, node_types: list[str] | None = None, limit: int = 25) -> list[dict]:
        folded = _fold(term)
        rows = []
        for node in self.nodes:
            if persona_id and node["persona_id"] != persona_id:
                continue
            if node_types and node["node_type"] not in node_types:
                continue
            blob = _fold(" ".join([node["slug"], node["title"], node.get("summary") or "", " ".join(node.get("tags") or [])]))
            if folded in blob or folded.replace(" ", "-") in blob:
                rows.append(node)
        return deepcopy(rows[:limit])

    def get_knowledge_neighbors(self, node_ids: list[str], max_edges: int = 200) -> tuple[list[dict], list[dict]]:
        ids = set(node_ids)
        related_edges = [
            e for e in self.edges
            if e["source_node_id"] in ids or e["target_node_id"] in ids
        ][:max_edges]
        related_ids = set(ids)
        for edge in related_edges:
            related_ids.add(edge["source_node_id"])
            related_ids.add(edge["target_node_id"])
        related_nodes = [n for n in self.nodes if n["id"] in related_ids]
        return deepcopy(related_nodes), deepcopy(related_edges)

    def list_all_knowledge_graph(self, persona_id: str | None = None, limit_nodes: int = 1500) -> tuple[list[dict], list[dict]]:
        nodes = [n for n in self.nodes if not persona_id or n["persona_id"] == persona_id][:limit_nodes]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.edges if e["source_node_id"] in node_ids and e["target_node_id"] in node_ids]
        return deepcopy(nodes), deepcopy(edges)

    def get_knowledge_items(self, *args, **kwargs) -> list[dict]:
        return []

    def get_kb_entries(self, *args, **kwargs) -> list[dict]:
        return []

    def get_kb_entries_by_ids(self, ids: list) -> dict:
        return {}


def validate_static_header_and_messages() -> None:
    layout = (ROOT / "dashboard" / "app" / "AppShell.tsx").read_text(encoding="utf-8")
    messages = (ROOT / "dashboard" / "app" / "messages" / "page.tsx").read_text(encoding="utf-8")
    graph_page = (ROOT / "dashboard" / "app" / "knowledge" / "graph" / "GraphPageClient.tsx").read_text(encoding="utf-8")
    graph_view = (ROOT / "dashboard" / "components" / "graph" / "GraphView.tsx").read_text(encoding="utf-8")
    node_drawer = (ROOT / "dashboard" / "components" / "graph" / "NodeDrawer.tsx").read_text(encoding="utf-8")

    _assert('value="">Todos</option>' in layout, "header has explicit Todos option")
    _assert('setPersona(savedExists ? saved : "")' in layout, "header defaults to Todos when saved persona is missing")
    _assert('removeItem("ai-brain-persona-id")' in layout, "Todos clears persona id")
    _assert('api.leads(200, 0, personaFilterId || undefined)' in messages, "messages lead list uses header persona id")
    _assert('api.conversations(168, personaFilterId || undefined)' in messages, "messages conversations use header persona id")
    _assert('POLL_INTERVAL_MS' not in messages, "messages page does not poll message/conversation APIs")
    _assert('postgres_changes' in messages and 'table: "messages"' in messages, "messages page refreshes from message realtime events")
    _assert('stickToBottomRef.current' in messages, "messages page preserves scroll when operator reads older messages")
    _assert('title="Conhecimento principal"' in messages, "sidebar renders primary knowledge section")
    _assert('title="Mais proximos"' in messages, "sidebar renders ranked nearby section")
    _assert("approved_snapshot_id" in node_drawer, "node drawer requires approved snapshot evidence")
    _assert("rag_chunk_count" in node_drawer, "node drawer verifies RAG chunk evidence from graph-data")
    _assert("ragChunkIds.length === 0" in node_drawer, "node drawer blocks false success without RAG chunks")
    _assert('includeTags = searchParams.get("tags") === "1"' in graph_page, "graph tags hidden by default")
    _assert('includeMentions = searchParams.get("mentions") === "1"' in graph_page, "graph mentions hidden by default")
    _assert('value: "semantic_tree"' in graph_page, "graph exposes semantic tree mode")
    _assert('setEdges(styledEdges)' in graph_view, "graph updates edge state when payload changes")


def validate_chat_context(store: FakeKnowledgeStore) -> None:
    from services import knowledge_graph, supabase_client

    originals = {
        "get_lead_by_ref": supabase_client.get_lead_by_ref,
        "get_messages": supabase_client.get_messages,
        "list_knowledge_nodes_by_type": supabase_client.list_knowledge_nodes_by_type,
        "find_knowledge_nodes": supabase_client.find_knowledge_nodes,
        "get_knowledge_neighbors": supabase_client.get_knowledge_neighbors,
        "get_knowledge_items": supabase_client.get_knowledge_items,
        "get_kb_entries": supabase_client.get_kb_entries,
        "get_kb_entries_by_ids": supabase_client.get_kb_entries_by_ids,
    }
    try:
        for name in originals:
            setattr(supabase_client, name, getattr(store, name))

        tock = knowledge_graph.get_chat_context(lead_ref=122, persona_id="persona-tock", user_text="Qual o catalogo do Modal?", limit=12)
        prime = knowledge_graph.get_chat_context(lead_ref=125, persona_id="persona-prime", user_text="Quanto custa Higienizacao de Cadeiras Prime?", limit=12)
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)

    for label, ctx, expected_product, forbidden_product in [
        ("Tock Fatal", tock, "modal", "higienizacao-cadeiras-prime"),
        ("Prime Higienizacao", prime, "higienizacao-cadeiras-prime", "modal"),
    ]:
        product_slugs = {n.get("slug") for n in ctx.get("nodes", []) if n.get("node_type") == "product"}
        faq_slugs = {n.get("slug") for n in ctx.get("nodes", []) if n.get("node_type") == "faq"}
        rels = {e.get("relation_type") for e in ctx.get("edges", [])}
        _assert(expected_product in product_slugs, f"{label} chat context returns expected product {expected_product}")
        _assert(forbidden_product not in product_slugs, f"{label} chat context does not leak other persona product")
        _assert(len(faq_slugs) >= 1, f"{label} chat context returns at least one FAQ")
        _assert("answers_question" in rels, f"{label} chat context returns FAQ relation")


def validate_graph_data(store: FakeKnowledgeStore) -> None:
    from api.routes import graph
    from services import auth_service, supabase_client

    originals = {
        "get_personas": supabase_client.get_personas,
        "get_persona": supabase_client.get_persona,
        "list_all_knowledge_graph": supabase_client.list_all_knowledge_graph,
        "get_knowledge_items": supabase_client.get_knowledge_items,
        "get_kb_entries": supabase_client.get_kb_entries,
        "ensure_gallery_node": supabase_client.ensure_gallery_node,
        "ensure_embedded_node": supabase_client.ensure_embedded_node,
        "list_approved_snapshots_for_nodes": supabase_client.list_approved_snapshots_for_nodes,
        "count_knowledge_rag_chunks_by_entry_ids": supabase_client.count_knowledge_rag_chunks_by_entry_ids,
        "_resolve_focus": graph._resolve_focus,
        "current_user": auth_service.current_user,
        "allowed_access": auth_service.allowed_access,
        "filter_personas_for_user": auth_service.filter_personas_for_user,
    }
    def fake_resolve_focus(focus: str, persona_id: str | None):
        if ":" in focus:
            node_type, slug = focus.split(":", 1)
            for node in store.nodes:
                if node["node_type"] == node_type and node["slug"] == slug and (not persona_id or node["persona_id"] == persona_id):
                    return deepcopy(node)
        for node in store.nodes:
            if node["id"] == focus and (not persona_id or node["persona_id"] == persona_id):
                return deepcopy(node)
        return None

    try:
        for name in originals:
            if name == "_resolve_focus":
                graph._resolve_focus = fake_resolve_focus
            elif name in {"current_user", "allowed_access", "filter_personas_for_user"}:
                continue
            else:
                if hasattr(store, name):
                    setattr(supabase_client, name, getattr(store, name))
        supabase_client.ensure_gallery_node = lambda _pid: None
        supabase_client.ensure_embedded_node = lambda _pid: None
        supabase_client.list_approved_snapshots_for_nodes = lambda _node_ids: {}
        supabase_client.count_knowledge_rag_chunks_by_entry_ids = lambda _entry_ids: {}
        auth_service.current_user = lambda _request: {"id": "user-test", "role": "admin"}
        auth_service.allowed_access = lambda _request: []
        auth_service.filter_personas_for_user = lambda _user, personas, _access: personas
        request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-test", "role": "admin"}, persona_access=[]))

        all_graph = graph.get_graph_data(
            request=request,
            persona_slug=None,
            focus=None,
            max_depth=3,
            include_tags=False,
            include_mentions=False,
            include_technical=False,
            mode="layered",
        )
        tock_graph = graph.get_graph_data(
            request=request,
            persona_slug="tock-fatal",
            focus=None,
            max_depth=3,
            include_tags=False,
            include_mentions=False,
            include_technical=False,
            mode="layered",
        )
        prime_graph = graph.get_graph_data(
            request=request,
            persona_slug="prime-higienizacao",
            focus=None,
            max_depth=3,
            include_tags=False,
            include_mentions=False,
            include_technical=False,
            mode="layered",
        )
        focus_graph = graph.get_graph_data(
            request=request,
            persona_slug="prime-higienizacao",
            focus="product:higienizacao-cadeiras-prime",
            max_depth=5,
            include_tags=False,
            include_mentions=False,
            include_technical=False,
            mode="semantic_tree",
        )
    finally:
        for name, fn in originals.items():
            if name == "_resolve_focus":
                graph._resolve_focus = fn
            elif name == "current_user":
                auth_service.current_user = fn
            elif name == "allowed_access":
                auth_service.allowed_access = fn
            elif name == "filter_personas_for_user":
                auth_service.filter_personas_for_user = fn
            else:
                setattr(supabase_client, name, fn)

    def slugs(payload: dict, node_type: str | None = None) -> set[str]:
        out = set()
        for node in payload["nodes"]:
            data = node.get("data") or {}
            if node_type and data.get("node_type") != node_type:
                continue
            if data.get("slug"):
                out.add(data["slug"])
        return out

    _assert("modal" in slugs(all_graph, "product"), "Todos graph includes Tock product")
    _assert("higienizacao-cadeiras-prime" in slugs(all_graph, "product"), "Todos graph includes Prime product")
    _assert("modal" in slugs(tock_graph, "product"), "Tock graph includes Tock product")
    _assert("higienizacao-cadeiras-prime" not in slugs(tock_graph, "product"), "Tock graph excludes Prime product")
    _assert("higienizacao-cadeiras-prime" in slugs(prime_graph, "product"), "Prime graph includes Prime product")
    _assert("modal" not in slugs(prime_graph, "product"), "Prime graph excludes Tock product")
    _assert("modal" not in slugs(tock_graph, "tag"), "tags are hidden by default")
    _assert("prime-cadeiras-mention" not in slugs(prime_graph, "mention"), "mentions are hidden by default")

    levels = {
        (node.get("data") or {}).get("node_type"): (node.get("data") or {}).get("level")
        for node in focus_graph["nodes"]
    }
    _assert(isinstance(levels.get("product"), int), "focused graph exposes product semantic level")
    _assert(isinstance(levels.get("faq"), int), "focused graph exposes FAQ semantic level")
    tiers = {(edge.get("data") or {}).get("tier") for edge in focus_graph["edges"]}
    _assert(any(tiers), "focused graph exposes edge tiers")
    _assert((focus_graph["meta"].get("focus") or {}).get("slug") == "higienizacao-cadeiras-prime", "focused graph resolves product focus")
    _assert(len(focus_graph["meta"].get("focus_path") or []) >= 2, "focused graph exposes focus path")


def main() -> int:
    print("\n-- Static frontend validation --")
    validate_static_header_and_messages()

    store = FakeKnowledgeStore()
    print("\n-- Chat context / sidebar backend validation --")
    validate_chat_context(store)

    print("\n-- Graph payload hierarchy validation --")
    validate_graph_data(store)

    print("\nPASS knowledge UI hierarchy validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

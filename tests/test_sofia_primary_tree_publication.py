from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from routes import graph as graph_route  # noqa: E402
from services import auth_service, knowledge_graph, supabase_client  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _Query:
    def __init__(self, store: "_FakeStore", table: str) -> None:
        self.store = store
        self.table = table
        self.filters: list[tuple[str, str, object]] = []
        self._limit: int | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field: str, value):
        self.filters.append(("eq", field, value))
        return self

    def in_(self, field: str, values):
        self.filters.append(("in", field, set(values)))
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def execute(self):
        rows = self.store._rows(self.table)
        for op, field, value in self.filters:
            if op == "eq":
                rows = [row for row in rows if row.get(field) == value]
            elif op == "in":
                rows = [row for row in rows if row.get(field) in value]
        if self._limit is not None:
            rows = rows[: self._limit]
        return SimpleNamespace(data=deepcopy(rows))


class _FakeStore:
    def __init__(self) -> None:
        self.persona = {"id": "persona-tock", "slug": "tock-fatal", "name": "Tock Fatal"}
        self.nodes: list[dict] = [
            self._node("persona-root", "persona", "self", "Persona", persona_id=self.persona["id"], level=0),
            self._node("brand-tock", "brand", "tock-fatal", "Tock Fatal", persona_id=self.persona["id"], level=10),
            self._node("briefing-tock", "briefing", "briefing-tock-fatal", "Briefing Inverno", persona_id=self.persona["id"], level=20),
            self._node("campaign-tock", "campaign", "campanha-inverno-tock-fatal", "Campanha de Inverno Tock Fatal", persona_id=self.persona["id"], level=30),
            self._node("audience-tock", "audience", "audiencia-padrao", "Audiencia Padrao", persona_id=self.persona["id"], level=40),
            self._node("group-modais", "product_group", "modais", "Modais", persona_id=self.persona["id"], level=50),
            self._node("product-modal-1", "product", "kit-modal-1", "Kit Modal 1", persona_id=self.persona["id"], level=60),
            self._node("product-modal-2", "product", "kit-modal-2", "Kit Modal 2", persona_id=self.persona["id"], level=60),
            self._node("copy-modal-1", "copy", "copy-kit-modal-1", "Copy Kit Modal 1", persona_id=self.persona["id"], level=70),
            self._node("copy-modal-2", "copy", "copy-kit-modal-2", "Copy Kit Modal 2", persona_id=self.persona["id"], level=70),
            self._node("faq-modal-1", "faq", "faq-kit-modal-1", "FAQ Kit Modal 1", persona_id=self.persona["id"], level=80),
            self._node("faq-modal-2", "faq", "faq-kit-modal-2", "FAQ Kit Modal 2", persona_id=self.persona["id"], level=80),
            self._node("embedded-tock", "embedded", "embedded", "Embedded", persona_id=self.persona["id"], level=90),
        ]
        self.edges: list[dict] = []
        self.source_index = {
            "persona-root": self.get_knowledge_node("persona-root"),
            "brand-tock": self.get_knowledge_node("brand-tock"),
            "briefing-tock": self.get_knowledge_node("briefing-tock"),
            "campaign-tock": self.get_knowledge_node("campaign-tock"),
            "audience-tock": self.get_knowledge_node("audience-tock"),
            "group-modais": self.get_knowledge_node("group-modais"),
            "product-modal-1": self.get_knowledge_node("product-modal-1"),
            "product-modal-2": self.get_knowledge_node("product-modal-2"),
            "copy-modal-1": self.get_knowledge_node("copy-modal-1"),
            "copy-modal-2": self.get_knowledge_node("copy-modal-2"),
            "faq-modal-1": self.get_knowledge_node("faq-modal-1"),
            "faq-modal-2": self.get_knowledge_node("faq-modal-2"),
        }

    def _node(self, node_id: str, node_type: str, slug: str, title: str, *, persona_id: str, level: int) -> dict:
        return {
            "id": node_id,
            "persona_id": persona_id,
            "node_type": node_type,
            "slug": slug,
            "title": title,
            "summary": title,
            "tags": [slug],
            "metadata": {},
            "status": "active",
            "level": level,
            "importance": 0.9 if node_type in {"persona", "brand", "product"} else 0.7,
            "confidence": 0.95,
        }

    def _rows(self, table: str) -> list[dict]:
        if table == "knowledge_nodes":
            return self.nodes
        if table == "knowledge_edges":
            return self.edges
        return []

    def table(self, table: str) -> _Query:
        return _Query(self, table)

    def get_personas(self) -> list[dict]:
        return [deepcopy(self.persona)]

    def get_persona(self, slug: str) -> dict | None:
        return deepcopy(self.persona) if slug == self.persona["slug"] else None

    def get_persona_by_id(self, persona_id: str) -> dict | None:
        return deepcopy(self.persona) if persona_id == self.persona["id"] else None

    def get_knowledge_node(self, node_id: str) -> dict | None:
        return deepcopy(next((node for node in self.nodes if node["id"] == node_id), None))

    def get_knowledge_node_by_slug(self, slug: str, persona_id: str | None = None, node_type: str | None = None) -> dict | None:
        for node in self.nodes:
            if node.get("slug") != slug:
                continue
            if persona_id and node.get("persona_id") != persona_id:
                continue
            if node_type and node.get("node_type") != node_type:
                continue
            return deepcopy(node)
        return None

    def get_knowledge_node_for_source(self, _table: str, source_id: str, persona_id: str | None = None) -> dict | None:
        node = self.source_index.get(source_id)
        if not node:
            return None
        if persona_id and node.get("persona_id") != persona_id:
            return None
        return deepcopy(node)

    def upsert_knowledge_node(self, payload: dict) -> dict:
        node_id = str(payload.get("id") or payload.get("slug") or payload.get("title") or "").strip()
        slug = str(payload.get("slug") or node_id).strip()
        node_type = str(payload.get("node_type") or "").strip() or "entity"
        existing = next((node for node in self.nodes if node["id"] == node_id or node["slug"] == slug), None)
        data = {
            "id": existing["id"] if existing else node_id,
            "persona_id": payload.get("persona_id") or (existing or {}).get("persona_id") or self.persona["id"],
            "node_type": node_type if not existing else existing["node_type"],
            "slug": slug,
            "title": payload.get("title") or (existing or {}).get("title") or slug,
            "summary": payload.get("summary") or (existing or {}).get("summary") or "",
            "tags": payload.get("tags") or (existing or {}).get("tags") or [slug],
            "metadata": {**((existing or {}).get("metadata") or {}), **(payload.get("metadata") or {})},
            "status": payload.get("status") or (existing or {}).get("status") or "active",
            "level": payload.get("level") or (existing or {}).get("level") or 50,
            "importance": payload.get("importance") or (existing or {}).get("importance") or 0.7,
            "confidence": payload.get("confidence") or (existing or {}).get("confidence") or 0.9,
        }
        if existing:
            existing.update(data)
            node = existing
        else:
            self.nodes.append(data)
            node = data
        self.source_index.setdefault(data["id"], node)
        return deepcopy(node)

    def update_knowledge_node(self, node_id: str, payload: dict) -> dict | None:
        node = next((item for item in self.nodes if item["id"] == node_id), None)
        if not node:
            return None
        node.update(payload)
        return deepcopy(node)

    def upsert_knowledge_edge(self, source_node_id: str, target_node_id: str, relation_type: str, persona_id: str | None = None, weight: float = 1, metadata: dict | None = None) -> dict:
        metadata = dict(metadata or {})
        existing = next(
            (edge for edge in self.edges if edge["source_node_id"] == source_node_id and edge["target_node_id"] == target_node_id and edge["relation_type"] == relation_type),
            None,
        )
        data = {
            "id": existing["id"] if existing else f"e-{len(self.edges) + 1}",
            "persona_id": persona_id or (existing or {}).get("persona_id") or self.persona["id"],
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "weight": weight,
            "metadata": {**((existing or {}).get("metadata") or {}), **metadata, "active": True},
        }
        if existing:
            existing.update(data)
            edge = existing
        else:
            self.edges.append(data)
            edge = data
        return deepcopy(edge)

    def ensure_embedded_node(self, persona_id: str):
        return self.get_knowledge_node("embedded-tock")

    def ensure_gallery_node(self, persona_id: str):
        return self._node("gallery-tock", "gallery", "gallery", "Gallery", persona_id=persona_id, level=95)

    def list_all_knowledge_graph(self, persona_id: str | None = None, limit_nodes: int = 1500):
        nodes = [node for node in self.nodes if not persona_id or node.get("persona_id") == persona_id][:limit_nodes]
        node_ids = {node["id"] for node in nodes}
        edges = [edge for edge in self.edges if edge["source_node_id"] in node_ids and edge["target_node_id"] in node_ids]
        return deepcopy(nodes), deepcopy(edges)

    def get_node_type_registry(self):
        return [
            {"node_type": node_type, "level": level, "importance": importance}
            for node_type, (level, importance) in {
                "persona": (0, 1.0),
                "brand": (10, 0.9),
                "briefing": (20, 0.85),
                "campaign": (30, 0.8),
                "audience": (40, 0.75),
                "product_group": (50, 0.7),
                "product": (60, 0.85),
                "copy": (70, 0.65),
                "faq": (80, 0.45),
                "embedded": (90, 0.95),
            }.items()
        ]

    def get_relation_type_registry(self):
        return [
            {"relation_type": relation_type, "tier": "structural"}
            for relation_type in [
                "belongs_to_persona",
                "contains",
                "briefed_by",
                "part_of_campaign",
                "manual",
                "about_product",
                "supports_copy",
                "answers_question",
                "published_to_rag",
            ]
        ]

    def list_approved_snapshots_for_nodes(self, _node_ids):
        return {}

    def count_knowledge_rag_chunks_by_entry_ids(self, _entry_ids):
        return {}


def _plan_slug(entry: dict) -> str:
    return str(entry["slug"])


def _build_complete_plan() -> tuple[list[dict], list[dict], list[dict]]:
    brand = _plan_slug({"slug": "brand-tock"})
    briefing = _plan_slug({"slug": "briefing-tock"})
    campaign = _plan_slug({"slug": "campaign-tock"})
    audience = _plan_slug({"slug": "audience-tock"})
    group = _plan_slug({"slug": "group-modais"})
    product_1 = _plan_slug({"slug": "product-modal-1"})
    product_2 = _plan_slug({"slug": "product-modal-2"})
    copy_1 = _plan_slug({"slug": "copy-modal-1"})
    copy_2 = _plan_slug({"slug": "copy-modal-2"})
    faq_1 = _plan_slug({"slug": "faq-modal-1"})
    faq_2 = _plan_slug({"slug": "faq-modal-2"})

    plan_entries = [
        {"content_type": "brand", "slug": brand, "title": "Tock Fatal", "metadata": {"parent_slug": "self"}},
        {"content_type": "briefing", "slug": briefing, "title": "Briefing Inverno", "metadata": {"parent_slug": brand}},
        {"content_type": "campaign", "slug": campaign, "title": "Campanha de Inverno Tock Fatal", "metadata": {"parent_slug": briefing}},
        {"content_type": "audience", "slug": audience, "title": "Audiencia Padrao", "metadata": {"parent_slug": campaign}},
        {"content_type": "product_group", "slug": group, "title": "Modais", "metadata": {"parent_slug": audience}},
        {"content_type": "product", "slug": product_1, "title": "Kit Modal 1", "metadata": {"parent_slug": group}},
        {"content_type": "product", "slug": product_2, "title": "Kit Modal 2", "metadata": {"parent_slug": group}},
        {"content_type": "copy", "slug": copy_1, "title": "Copy Kit Modal 1", "metadata": {"parent_slug": product_1}},
        {"content_type": "copy", "slug": copy_2, "title": "Copy Kit Modal 2", "metadata": {"parent_slug": product_2}},
        {"content_type": "faq", "slug": faq_1, "title": "FAQ Kit Modal 1", "metadata": {"parent_slug": copy_1}},
        {"content_type": "faq", "slug": faq_2, "title": "FAQ Kit Modal 2", "metadata": {"parent_slug": copy_2}},
    ]
    plan_links = [
        {"source_slug": brand, "target_slug": briefing, "relation_type": "brand_has_briefing"},
        {"source_slug": briefing, "target_slug": campaign, "relation_type": "briefing_has_campaign"},
        {"source_slug": campaign, "target_slug": audience, "relation_type": "campaign_has_audience"},
        {"source_slug": audience, "target_slug": group, "relation_type": "audience_has_product_group"},
        {"source_slug": group, "target_slug": product_1, "relation_type": "contains"},
        {"source_slug": group, "target_slug": product_2, "relation_type": "contains"},
        {"source_slug": product_1, "target_slug": copy_1, "relation_type": "supports_copy"},
        {"source_slug": product_2, "target_slug": copy_2, "relation_type": "supports_copy"},
        {"source_slug": copy_1, "target_slug": faq_1, "relation_type": "answers_question"},
        {"source_slug": copy_2, "target_slug": faq_2, "relation_type": "answers_question"},
    ]
    persisted_items = [
        {"id": entry["slug"], "persona_id": "persona-tock", "title": entry["title"], "metadata": {"slug": entry["slug"], "knowledge_node_id": entry["slug"]}}
        for entry in plan_entries
    ]
    return plan_entries, plan_links, persisted_items


def test_primary_tree_publication_and_graph_render(monkeypatch):
    graph_page = (ROOT / "dashboard" / "app" / "knowledge" / "graph" / "GraphPageClient.tsx").read_text(encoding="utf-8")
    _assert('const mode = (searchParams.get("mode") as ViewMode) || "semantic_tree";' in graph_page, "graph page defaults to semantic tree mode")

    store = _FakeStore()
    plan_entries, plan_links, persisted_items = _build_complete_plan()

    monkeypatch.setattr(supabase_client, "get_client", lambda: store)
    monkeypatch.setattr(supabase_client, "get_personas", store.get_personas)
    monkeypatch.setattr(supabase_client, "get_persona", store.get_persona)
    monkeypatch.setattr(supabase_client, "get_persona_by_id", store.get_persona_by_id)
    monkeypatch.setattr(supabase_client, "get_knowledge_node", store.get_knowledge_node)
    monkeypatch.setattr(supabase_client, "get_knowledge_node_by_slug", store.get_knowledge_node_by_slug)
    monkeypatch.setattr(supabase_client, "get_knowledge_node_for_source", store.get_knowledge_node_for_source)
    monkeypatch.setattr(supabase_client, "upsert_knowledge_node", store.upsert_knowledge_node)
    monkeypatch.setattr(supabase_client, "update_knowledge_node", store.update_knowledge_node)
    monkeypatch.setattr(supabase_client, "upsert_knowledge_edge", store.upsert_knowledge_edge)
    monkeypatch.setattr(supabase_client, "ensure_embedded_node", store.ensure_embedded_node)
    monkeypatch.setattr(supabase_client, "ensure_gallery_node", store.ensure_gallery_node)
    monkeypatch.setattr(supabase_client, "list_all_knowledge_graph", store.list_all_knowledge_graph)
    monkeypatch.setattr(supabase_client, "get_node_type_registry", store.get_node_type_registry)
    monkeypatch.setattr(supabase_client, "get_relation_type_registry", store.get_relation_type_registry)
    monkeypatch.setattr(supabase_client, "list_approved_snapshots_for_nodes", store.list_approved_snapshots_for_nodes)
    monkeypatch.setattr(supabase_client, "count_knowledge_rag_chunks_by_entry_ids", store.count_knowledge_rag_chunks_by_entry_ids)

    monkeypatch.setattr(auth_service, "current_user", lambda request: {"id": "u-1"})
    monkeypatch.setattr(auth_service, "allowed_access", lambda request: {})
    monkeypatch.setattr(auth_service, "filter_personas_for_user", lambda user, personas, access: personas)
    monkeypatch.setattr(auth_service, "assert_persona_access", lambda request, persona_id=None, persona_slug=None: True)
    monkeypatch.setattr(knowledge_graph, "_ensure_persona_root", lambda persona_id: store.get_knowledge_node("persona-root"))
    monkeypatch.setattr(knowledge_graph, "_normalize_uuid", lambda value: str(value).strip() or None)

    result = knowledge_graph.apply_plan_hierarchy(
        persona_id="persona-tock",
        persisted_items=persisted_items,
        plan_entries=plan_entries,
        plan_links=plan_links,
    )

    _assert(result["resolved_links"] == 11, f"expected 11 structural edges, got {result['resolved_links']}")
    _assert(not result["missing_links"], f"no missing links expected, got {result['missing_links']}")
    _assert(result["items"] and all(item.get("main_tree_edge_id") for item in result["items"]), "every saved node got a primary edge")
    repair = knowledge_graph.repair_primary_tree_connections("persona-tock")
    _assert(repair["repaired"] == 0, f"repair should not invent fallback parents, got {repair}")

    main_edges = [
        edge for edge in store.edges
        if edge.get("metadata", {}).get("primary_tree") is True and edge.get("target_node_id") != "embedded-tock"
    ]
    _assert(len(main_edges) == 11, f"expected 11 primary edges, got {len(main_edges)}")
    _assert(not any(edge["relation_type"] == "targets_audience" for edge in main_edges), "semantic relation never replaces the primary edge relation")
    brand_briefing = next(edge for edge in main_edges if edge["source_node_id"] == "brand-tock" and edge["target_node_id"] == "briefing-tock")
    _assert(brand_briefing["metadata"].get("primary_tree") is True, "brand->briefing is part of the primary tree")
    briefing_campaign = next(edge for edge in main_edges if edge["source_node_id"] == "briefing-tock" and edge["target_node_id"] == "campaign-tock")
    _assert(briefing_campaign["metadata"].get("primary_tree") is True, "briefing->campaign is part of the primary tree")
    campaign_audience = next(edge for edge in main_edges if edge["source_node_id"] == "campaign-tock" and edge["target_node_id"] == "audience-tock")
    _assert(campaign_audience["metadata"].get("primary_tree") is True, "campaign->audience is part of the primary tree")
    audience_group = next(edge for edge in main_edges if edge["source_node_id"] == "audience-tock" and edge["target_node_id"] == "group-modais")
    _assert(audience_group["metadata"].get("semantic_relation") == "audience_has_product_group", "audience->group keeps semantic_relation metadata")

    store.upsert_knowledge_edge("faq-modal-1", "embedded-tock", "published_to_rag", persona_id="persona-tock", metadata={"primary_tree": False, "active": True, "created_from": "test"})
    store.upsert_knowledge_edge("faq-modal-2", "embedded-tock", "published_to_rag", persona_id="persona-tock", metadata={"primary_tree": False, "active": True, "created_from": "test"})

    graph = graph_route.get_graph_data(
        request=SimpleNamespace(),
        persona_slug="tock-fatal",
        focus="product_group:modais",
        max_depth=6,
        include_tags=False,
        include_mentions=False,
        include_technical=True,
        include_embedded=True,
        mode="semantic_tree",
    )

    node_ids = {node["id"] for node in graph["nodes"]}
    for expected in {
        "persona:persona-tock",
        "gn:brand-tock",
        "gn:briefing-tock",
        "gn:campaign-tock",
        "gn:audience-tock",
        "gn:group-modais",
        "gn:product-modal-1",
        "gn:product-modal-2",
        "gn:copy-modal-1",
        "gn:copy-modal-2",
        "gn:faq-modal-1",
        "gn:faq-modal-2",
        "embedded:persona-tock",
    }:
        _assert(expected in node_ids, f"graph-data keeps node {expected}")

    graph_edges = graph["edges"]
    edge_pairs = {(edge.get("source"), edge.get("target")) for edge in graph_edges}
    for expected_pair in [
        ("persona:persona-tock", "gn:brand-tock"),
        ("gn:brand-tock", "gn:briefing-tock"),
        ("gn:briefing-tock", "gn:campaign-tock"),
        ("gn:campaign-tock", "gn:audience-tock"),
        ("gn:audience-tock", "gn:group-modais"),
        ("gn:group-modais", "gn:product-modal-1"),
        ("gn:group-modais", "gn:product-modal-2"),
        ("gn:product-modal-1", "gn:copy-modal-1"),
        ("gn:product-modal-2", "gn:copy-modal-2"),
        ("gn:copy-modal-1", "gn:faq-modal-1"),
        ("gn:copy-modal-2", "gn:faq-modal-2"),
        ("gn:faq-modal-1", "embedded:persona-tock"),
        ("gn:faq-modal-2", "embedded:persona-tock"),
    ]:
        _assert(expected_pair in edge_pairs, f"graph renders edge {expected_pair[0]} -> {expected_pair[1]}")

    primary_visible = [
        edge for edge in graph_edges
        if (edge.get("data") or {}).get("metadata", {}).get("primary_tree") is True
        or (edge.get("data") or {}).get("primary_tree") is True
    ]
    _assert(
        any(
            edge.get("data", {}).get("relation_type") in {"contains", "audience_has_product_group", "product_group_has_product"}
            for edge in primary_visible
        ),
        "graph-data keeps the structural primary chain",
    )

# -*- coding: utf-8 -*-
"""
Offline integration test for a complete Prime Higienizacao knowledge flow.

This test intentionally does not use WhatsApp, n8n, Supabase, or an LLM. It
loads a structured scenario fixture, registers persona + knowledge items through
the same graph bootstrap layer used by the app, then asks mocked chat questions
and validates graph distance/path, a deterministic bot reply, and sidebar data.

Run:
  python tests/integration_prime_higienizacao_mock.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_SCENARIO = ROOT / "tests" / "fixtures" / "knowledge_prime_higienizacao.json"
REPORT_PATH = ROOT / "test-artifacts" / "prime_higienizacao_mock_test.json"


def _slugify(value: str) -> str:
    from services.knowledge_graph import _slugify as graph_slugify

    return graph_slugify(value)


def _fold(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "")
    return text.encode("ascii", "ignore").decode("ascii").lower()


def _contains(haystack: object, needle: str) -> bool:
    return _fold(needle) in _fold(json.dumps(haystack, ensure_ascii=False, sort_keys=True))


def _currency_ok(meta: dict) -> bool:
    price = (meta or {}).get("price")
    if not isinstance(price, dict):
        return False
    if not price.get("currency") or not price.get("display"):
        return False
    amount = price.get("amount")
    return isinstance(amount, (int, float)) and amount > 0


class _FakeStore:
    """In-memory stand-in for the current Supabase-facing knowledge flow."""

    def __init__(self) -> None:
        self.personas_by_slug: dict[str, dict] = {}
        self.knowledge_items: dict[str, dict] = {}
        self.artifacts_by_key: dict[tuple[str, str, str], dict] = {}
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.kb_entries: dict[str, dict] = {}
        self.messages_by_ref: dict[str, list[dict]] = {}
        self._persona_no = 0
        self._item_no = 0
        self._artifact_no = 0
        self._node_no = 0
        self._edge_no = 0
        self._message_no = 0

    def upsert_persona(self, data: dict) -> dict:
        slug = data["slug"]
        existing = self.personas_by_slug.get(slug)
        if existing:
            existing.update({k: v for k, v in data.items() if v is not None})
            return existing
        self._persona_no += 1
        row = {
            "id": f"persona-{slug}",
            "slug": slug,
            "name": data.get("name") or slug,
            "active": True,
            "config": data.get("config") or {},
            "tone": data.get("tone"),
        }
        row.update(data)
        self.personas_by_slug[slug] = row
        return row

    def get_persona(self, slug: str) -> Optional[dict]:
        return self.personas_by_slug.get(slug)

    def _artifact_for_item(self, item: dict) -> dict:
        persona_id = item.get("persona_id") or ""
        content_type = item.get("content_type") or "knowledge_item"
        canonical_slug = item.get("slug") or _slugify(item.get("title") or item.get("id") or "")
        key = (persona_id, content_type, canonical_slug)
        artifact = self.artifacts_by_key.get(key)
        if not artifact:
            self._artifact_no += 1
            canonical_key = ":".join([persona_id or "global", content_type, canonical_slug])
            artifact = {
                "id": f"artifact-{self._artifact_no}",
                "persona_id": persona_id or None,
                "canonical_key": canonical_key,
                "canonical_hash": hashlib.md5(canonical_key.encode("utf-8")).hexdigest(),
                "title": item.get("title") or canonical_slug,
                "content_type": content_type,
                "curation_status": "pending",
                "metadata": deepcopy(item.get("metadata") or {}),
                "versions": [],
            }
            self.artifacts_by_key[key] = artifact
        if item.get("status") in {"approved", "embedded", "validated"}:
            artifact["curation_status"] = "validated"
        artifact["metadata"].update(deepcopy(item.get("metadata") or {}))
        known_versions = {v.get("source_id") for v in artifact["versions"]}
        if item.get("id") not in known_versions:
            artifact["versions"].append({
                "version_no": len(artifact["versions"]) + 1,
                "source_table": "knowledge_items",
                "source_id": item.get("id"),
                "title": item.get("title"),
                "content_type": content_type,
                "status": item.get("status"),
                "content_hash": hashlib.md5((item.get("content") or "").encode("utf-8")).hexdigest(),
            })
        return artifact

    def insert_knowledge_item(self, data: dict) -> dict:
        self._item_no += 1
        item_id = data.get("id") or f"ki-{self._item_no}"
        row = deepcopy(data)
        row["id"] = item_id
        row.setdefault("status", "pending")
        row.setdefault("metadata", {})
        row.setdefault("tags", [])
        artifact = self._artifact_for_item(row)
        row["artifact_id"] = artifact["id"]
        self.knowledge_items[item_id] = row
        return deepcopy(row)

    def update_knowledge_item(self, item_id: str, data: dict) -> None:
        row = self.knowledge_items[item_id]
        row.update(deepcopy(data))
        artifact = self._artifact_for_item(row)
        row["artifact_id"] = artifact["id"]

    def get_knowledge_item(self, item_id: str) -> Optional[dict]:
        row = self.knowledge_items.get(item_id)
        return deepcopy(row) if row else None

    def get_knowledge_items(
        self,
        status: Optional[str] = None,
        persona_id: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        rows = list(self.knowledge_items.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if persona_id:
            rows = [r for r in rows if r.get("persona_id") == persona_id]
        if content_type:
            rows = [r for r in rows if r.get("content_type") == content_type]
        return deepcopy(rows[offset: offset + limit])

    def insert_message(self, data: dict) -> dict:
        self._message_no += 1
        row = deepcopy(data)
        row.setdefault("id", f"msg-{self._message_no}")
        row.setdefault("message_id", f"mock_{self._message_no}")
        row.setdefault("canal", "mock")
        row.setdefault("status", "stored")
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        lead_ref = str(row.get("lead_ref") or row.get("lead_id") or "mock-lead")
        self.messages_by_ref.setdefault(lead_ref, []).insert(0, row)
        return deepcopy(row)

    def get_messages(self, lead_id: str, limit: int = 30) -> list[dict]:
        return deepcopy(self.messages_by_ref.get(str(lead_id), [])[:limit])

    def upsert_knowledge_node(self, data: dict) -> dict:
        key = (data.get("persona_id"), data["node_type"], data["slug"])
        for node in self.nodes.values():
            if (node.get("persona_id"), node.get("node_type"), node.get("slug")) == key:
                node["title"] = data.get("title") or node.get("title")
                node["summary"] = data.get("summary") or node.get("summary")
                node["tags"] = sorted(set((node.get("tags") or []) + (data.get("tags") or [])))
                node["metadata"] = {**(node.get("metadata") or {}), **(data.get("metadata") or {})}
                for field in ("source_table", "source_id", "status", "artifact_id"):
                    if data.get(field) is not None:
                        node[field] = data[field]
                return deepcopy(node)
        self._node_no += 1
        row = {
            "id": f"node-{self._node_no}",
            "persona_id": data.get("persona_id"),
            "source_table": data.get("source_table"),
            "source_id": data.get("source_id"),
            "node_type": data["node_type"],
            "slug": data["slug"],
            "title": data.get("title") or data["slug"],
            "summary": data.get("summary"),
            "tags": data.get("tags") or [],
            "metadata": data.get("metadata") or {},
            "status": data.get("status") or "active",
            "artifact_id": data.get("artifact_id"),
        }
        self.nodes[row["id"]] = row
        return deepcopy(row)

    def upsert_knowledge_edge(self, source_node_id: str, target_node_id: str, relation_type: str, **kw) -> dict:
        if not source_node_id or not target_node_id or source_node_id == target_node_id:
            return {}
        key = (source_node_id, target_node_id, relation_type)
        if key in self.edges:
            edge = self.edges[key]
            edge.update({k: v for k, v in kw.items() if v is not None})
            return deepcopy(edge)
        self._edge_no += 1
        row = {
            "id": f"edge-{self._edge_no}",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "weight": kw.get("weight", 1.0),
            "persona_id": kw.get("persona_id"),
        }
        self.edges[key] = row
        return deepcopy(row)

    def _matches_node(self, node: dict, norm: str) -> bool:
        meta = node.get("metadata") or {}
        aliases = meta.get("aliases") or meta.get("synonyms") or []
        if not isinstance(aliases, list):
            aliases = [aliases]
        values = [
            node.get("slug"),
            node.get("title"),
            " ".join(node.get("tags") or []),
            *[str(a) for a in aliases if a],
        ]
        blob = _fold(" ".join(str(v or "") for v in values))
        slug_norm = norm.replace(" ", "-")
        return norm in blob or slug_norm in blob

    def find_knowledge_nodes(self, term: str, persona_id=None, node_types=None, limit=25) -> list[dict]:
        norm = _fold(term).strip()
        if not norm:
            return []
        out = []
        for node in self.nodes.values():
            if persona_id and node.get("persona_id") != persona_id:
                continue
            if node_types and node.get("node_type") not in node_types:
                continue
            if self._matches_node(node, norm):
                out.append(deepcopy(node))
        return out[:limit]

    def get_knowledge_neighbors(self, node_ids: list[str], max_edges=200) -> tuple[list[dict], list[dict]]:
        ids = set(node_ids or [])
        edges = [
            deepcopy(e)
            for e in self.edges.values()
            if e.get("source_node_id") in ids or e.get("target_node_id") in ids
        ][:max_edges]
        related = set(ids)
        for edge in edges:
            related.add(edge["source_node_id"])
            related.add(edge["target_node_id"])
        nodes = [deepcopy(self.nodes[nid]) for nid in related if nid in self.nodes]
        return nodes, edges

    def list_knowledge_nodes_by_type(self, node_types, persona_id=None, limit=200) -> list[dict]:
        rows = []
        for node in self.nodes.values():
            if node.get("node_type") not in node_types:
                continue
            if persona_id and node.get("persona_id") != persona_id:
                continue
            rows.append(deepcopy(node))
        return rows[:limit]

    def list_all_knowledge_graph(self, persona_id=None, limit_nodes=1500) -> tuple[list[dict], list[dict]]:
        nodes = [
            deepcopy(n)
            for n in self.nodes.values()
            if not persona_id or n.get("persona_id") == persona_id
        ][:limit_nodes]
        node_ids = {n["id"] for n in nodes}
        edges = [
            deepcopy(e)
            for e in self.edges.values()
            if e.get("source_node_id") in node_ids or e.get("target_node_id") in node_ids
        ]
        return nodes, edges

    def get_kb_entries(self, persona_id: Optional[str] = None, status: str = "ATIVO") -> list[dict]:
        rows = list(self.kb_entries.values())
        if persona_id:
            rows = [r for r in rows if r.get("persona_id") == persona_id]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return deepcopy(rows)

    def get_kb_entry(self, entry_id: str) -> Optional[dict]:
        row = self.kb_entries.get(entry_id)
        return deepcopy(row) if row else None

    def get_kb_entries_by_ids(self, ids: list) -> dict:
        wanted = {str(i) for i in ids or []}
        return {
            str(entry_id): deepcopy(row)
            for entry_id, row in self.kb_entries.items()
            if str(entry_id) in wanted
        }

    def node_by_slug(self, slug: str, node_type: Optional[str] = None, persona_id: Optional[str] = None) -> Optional[dict]:
        for node in self.nodes.values():
            if node.get("slug") != slug:
                continue
            if node_type and node.get("node_type") != node_type:
                continue
            if persona_id and node.get("persona_id") != persona_id:
                continue
            return node
        return None


def _install_fake_supabase(store: _FakeStore) -> None:
    from services import supabase_client as sb

    sb.upsert_persona = store.upsert_persona  # type: ignore[attr-defined]
    sb.get_persona = store.get_persona  # type: ignore[attr-defined]
    sb.insert_knowledge_item = store.insert_knowledge_item  # type: ignore[attr-defined]
    sb.update_knowledge_item = store.update_knowledge_item  # type: ignore[attr-defined]
    sb.get_knowledge_item = store.get_knowledge_item  # type: ignore[attr-defined]
    sb.get_knowledge_items = store.get_knowledge_items  # type: ignore[attr-defined]
    sb.insert_message = store.insert_message  # type: ignore[attr-defined]
    sb.get_messages = store.get_messages  # type: ignore[attr-defined]
    sb.upsert_knowledge_node = store.upsert_knowledge_node  # type: ignore[attr-defined]
    sb.upsert_knowledge_edge = store.upsert_knowledge_edge  # type: ignore[attr-defined]
    sb.find_knowledge_nodes = store.find_knowledge_nodes  # type: ignore[attr-defined]
    sb.get_knowledge_neighbors = store.get_knowledge_neighbors  # type: ignore[attr-defined]
    sb.list_knowledge_nodes_by_type = store.list_knowledge_nodes_by_type  # type: ignore[attr-defined]
    sb.list_all_knowledge_graph = store.list_all_knowledge_graph  # type: ignore[attr-defined]
    sb.get_kb_entries = store.get_kb_entries  # type: ignore[attr-defined]
    sb.get_kb_entry = store.get_kb_entry  # type: ignore[attr-defined]
    sb.get_kb_entries_by_ids = store.get_kb_entries_by_ids  # type: ignore[attr-defined]


def _item_frontmatter(item: dict) -> dict:
    return {
        "slug": item["slug"],
        "type": item["node_type"],
        "tags": item.get("tags") or [],
        "aliases": item.get("aliases") or [],
        "metadata": item.get("metadata") or {},
    }


def _register_scenario(store: _FakeStore, scenario: dict) -> dict:
    from services import knowledge_graph

    persona = store.upsert_persona(scenario["persona"])
    persona_id = persona["id"]
    registered_items = []

    for src in scenario["items"]:
        payload = {
            "persona_id": persona_id,
            "title": src["title"],
            "slug": src["slug"],
            "content_type": src["node_type"],
            "content": src.get("content") or "",
            "tags": src.get("tags") or [],
            "metadata": {
                **deepcopy(src.get("metadata") or {}),
                "aliases": src.get("aliases") or [],
                "slug": src["slug"],
            },
            "status": "pending",
            "source": "mock_classifier_curator",
            "file_path": f"mock://prime-higienizacao/{src['node_type']}/{src['slug']}.md",
        }
        item = store.insert_knowledge_item(payload)
        fm = _item_frontmatter({**src, "metadata": item["metadata"]})
        knowledge_graph.bootstrap_from_item(item, fm, item["content"], persona_id=persona_id)

        store.update_knowledge_item(item["id"], {"status": "approved"})
        approved = store.get_knowledge_item(item["id"])
        assert approved is not None
        knowledge_graph.bootstrap_from_item(approved, fm, approved["content"], persona_id=persona_id)
        registered_items.append(approved)

    for edge in scenario["expected_edges"]:
        src = store.node_by_slug(edge["src_slug"], edge["src_type"], persona_id)
        tgt = store.node_by_slug(edge["tgt_slug"], edge["tgt_type"], persona_id)
        if src and tgt:
            store.upsert_knowledge_edge(
                src["id"],
                tgt["id"],
                edge["relation_type"],
                persona_id=persona_id,
                weight=1.0,
            )

    return {"persona": persona, "items": registered_items}


def _nodes_by_slug(ctx: dict) -> dict[str, dict]:
    return {n.get("slug"): n for n in ctx.get("nodes") or [] if n.get("slug")}


def _similar_by_slug(ctx: dict) -> dict[str, dict]:
    return {n.get("slug"): n for n in ctx.get("similar") or [] if n.get("slug")}


def _mock_bot_reply(ctx: dict, focus_slug: str, persona: dict) -> str:
    nodes = _nodes_by_slug(ctx)
    focus = nodes.get(focus_slug)
    products = [
        n for n in (ctx.get("nodes") or [])
        if n.get("node_type") == "product" and n.get("slug") in {focus_slug, "impermeabilizacao"}
    ]
    if focus and focus.get("node_type") == "product" and focus not in products:
        products.insert(0, focus)

    parts = []
    for product in products:
        price = (product.get("metadata") or {}).get("price") or {}
        display = price.get("display")
        unit = price.get("unit")
        if display:
            suffix = f" ({unit})" if unit else ""
            parts.append(f"{product.get('title')}: {display}{suffix}")

    region = (persona.get("config") or {}).get("region") or "regiao atendida"
    if not parts:
        return f"Prime Higienizacao atende {region}. Posso confirmar os detalhes do servico para voce."
    return (
        f"Prime Higienizacao atende {region}. "
        f"{'; '.join(parts)}. "
        "O atendimento segue um tom serio, direto e seguro."
    )


def _conversation_link(lead_ref: int, *, focus: Optional[str] = None, edge_id: Optional[str] = None) -> str:
    params = []
    if focus:
        params.append(f"focus={focus}")
    if edge_id:
        params.append(f"edge={edge_id}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"/messages/{lead_ref}{query}"


def _node_card(node: dict, lead_ref: int) -> dict:
    node_type = node.get("node_type") or "node"
    slug = node.get("slug") or node.get("id")
    metadata = node.get("metadata") or {}
    price = metadata.get("price") or {}
    return {
        "id": node.get("id"),
        "slug": slug,
        "node_type": node_type,
        "title": node.get("title"),
        "summary": node.get("summary"),
        "price": price.get("display"),
        "graph_distance": node.get("graph_distance"),
        "path": node.get("path_slugs") or [],
        "path_relations": node.get("path_relations") or [],
        "conversation_link": _conversation_link(lead_ref, focus=f"{node_type}:{slug}"),
        "knowledge_link": node.get("link_target") or f"/knowledge/graph?focus={node_type}:{slug}",
    }


def _sidebar_snapshot(store: _FakeStore, ctx: dict, persona_id: str, lead_ref: int) -> dict:
    def all_type(node_type: str) -> list[dict]:
        rows = store.list_knowledge_nodes_by_type([node_type], persona_id=persona_id, limit=100)
        return [r for r in rows if r.get("slug") != "self"]

    brand_rows = []
    for node in all_type("brand"):
        color = ((node.get("metadata") or {}).get("dominant_color") or {}).get("name")
        card = _node_card(node, lead_ref)
        card["dominant_color"] = color
        brand_rows.append(card)

    product_rows = []
    for node in all_type("product"):
        card = _node_card(node, lead_ref)
        card["unit"] = ((node.get("metadata") or {}).get("price") or {}).get("unit")
        product_rows.append(card)

    nodes_by_id = {node.get("id"): node for node in store.nodes.values()}
    relation_rows = []
    for edge in sorted(store.edges.values(), key=lambda e: (e.get("relation_type") or "", e.get("id") or "")):
        src = nodes_by_id.get(edge.get("source_node_id"))
        tgt = nodes_by_id.get(edge.get("target_node_id"))
        if not src or not tgt:
            continue
        relation_rows.append({
            "id": edge.get("id"),
            "relation_type": edge.get("relation_type"),
            "source": {
                "slug": src.get("slug"),
                "title": src.get("title"),
                "node_type": src.get("node_type"),
            },
            "target": {
                "slug": tgt.get("slug"),
                "title": tgt.get("title"),
                "node_type": tgt.get("node_type"),
            },
            "conversation_link": _conversation_link(
                lead_ref,
                focus=f"{src.get('node_type')}:{src.get('slug')}",
                edge_id=edge.get("id"),
            ),
        })

    return {
        "Brand": brand_rows,
        "Briefing": [
            _node_card(n, lead_ref)
            for n in all_type("briefing")
            if n.get("slug") == "briefing-geral-prime-higienizacao"
        ],
        "Produtos": product_rows,
        "Tom/Regras": [
            _node_card(n, lead_ref)
            for n in all_type("tone") + all_type("rule")
        ],
        "Todas as relacoes": relation_rows,
        "Busca por similaridade": [
            {
                "slug": item.get("slug"),
                "title": item.get("title"),
                "node_type": item.get("node_type"),
                "graph_distance": item.get("graph_distance"),
                "path": item.get("path_slugs"),
                "path_relations": item.get("path_relations"),
                "conversation_link": _conversation_link(
                    lead_ref,
                    focus=f"{item.get('node_type')}:{item.get('slug')}",
                ),
            }
            for item in ctx.get("similar") or []
        ],
    }


def _validate_expected_edges(store: _FakeStore, scenario: dict, persona_id: str, report: dict) -> None:
    for edge in scenario["expected_edges"]:
        src = store.node_by_slug(edge["src_slug"], edge["src_type"], persona_id)
        tgt = store.node_by_slug(edge["tgt_slug"], edge["tgt_type"], persona_id)
        ok = bool(src and tgt and (src["id"], tgt["id"], edge["relation_type"]) in store.edges)
        report["checks"].append({
            "ok": ok,
            "check": f"edge {edge['src_slug']} -[{edge['relation_type']}]-> {edge['tgt_slug']}",
        })


def _validate_registration(store: _FakeStore, scenario: dict, persona_id: str, report: dict) -> None:
    expected_item_count = len(scenario["items"])
    report["checks"].append({
        "ok": len(store.knowledge_items) == expected_item_count,
        "check": "all fixture items registered as knowledge_items",
        "actual": len(store.knowledge_items),
        "expected": expected_item_count,
    })
    report["checks"].append({
        "ok": len(store.artifacts_by_key) == expected_item_count,
        "check": "each fixture item converged to one canonical artifact",
        "actual": len(store.artifacts_by_key),
        "expected": expected_item_count,
    })
    for artifact in store.artifacts_by_key.values():
        report["checks"].append({
            "ok": bool(artifact.get("versions")),
            "check": f"artifact {artifact['canonical_key']} has versions",
        })

    expected_slugs = {item["slug"] for item in scenario["items"]}
    actual_slugs = {
        n.get("slug")
        for n in store.nodes.values()
        if n.get("persona_id") == persona_id and n.get("node_type") not in {"tag", "persona", "mention"}
    }
    report["checks"].append({
        "ok": expected_slugs.issubset(actual_slugs),
        "check": "all fixture knowledge items have graph nodes",
        "missing": sorted(expected_slugs - actual_slugs),
    })

    for node in store.list_knowledge_nodes_by_type(["product"], persona_id=persona_id, limit=100):
        if node.get("slug") in {"self"}:
            continue
        report["checks"].append({
            "ok": _currency_ok(node.get("metadata") or {}),
            "check": f"product {node.get('slug')} has structured price",
        })

    brand = store.node_by_slug("prime-higienizacao", "brand", persona_id)
    color = (((brand or {}).get("metadata") or {}).get("dominant_color") or {}).get("name")
    report["checks"].append({
        "ok": color == "azul",
        "check": "brand carries predominant blue color",
        "actual": color,
    })
    _validate_expected_edges(store, scenario, persona_id, report)


def _validate_message_flow(store: _FakeStore, scenario: dict, persona: dict, report: dict, lead_ref: int) -> None:
    from services import knowledge_graph

    persona_id = persona["id"]
    for idx, message in enumerate(scenario["test_messages"], start=1):
        inbound = store.insert_message({
            "lead_ref": lead_ref,
            "direcao": "in",
            "direction": "inbound",
            "remetente": "cliente",
            "sender_type": "client",
            "texto": message["text"],
        })
        ctx = knowledge_graph.get_chat_context(
            lead_ref=lead_ref,
            persona_id=persona_id,
            user_text=message["text"],
            limit=20,
        )
        nodes = _nodes_by_slug(ctx)
        similar = _similar_by_slug(ctx)
        focus_slug = message["expected_focus_slug"]
        focus = nodes.get(focus_slug)
        report["checks"].append({
            "ok": bool(focus and focus.get("graph_distance") == 0),
            "check": f"message {idx} focus node {focus_slug} detected at graph_distance 0",
            "query_terms": ctx.get("query_terms"),
        })

        for slug in message["expected_related_slugs"]:
            node = nodes.get(slug)
            sim = similar.get(slug)
            graph_distance = (node or sim or {}).get("graph_distance")
            path = (node or sim or {}).get("path") or []
            report["checks"].append({
                "ok": bool((node or sim) and graph_distance is not None),
                "check": f"message {idx} related node {slug} returned with graph_distance",
                "graph_distance": graph_distance,
                "path": path,
            })

        reply = _mock_bot_reply(ctx, focus_slug, persona)
        outbound = store.insert_message({
            "lead_ref": lead_ref,
            "direcao": "out",
            "direction": "outbound",
            "remetente": "mock_bot",
            "sender_type": "assistant",
            "texto": reply,
            "metadata": {
                "mock": True,
                "focus_slug": focus_slug,
                "query_terms": ctx.get("query_terms") or [],
                "similar_slugs": [item.get("slug") for item in (ctx.get("similar") or [])],
            },
        })
        for term in message["expected_reply_terms"]:
            report["checks"].append({
                "ok": _fold(term) in _fold(reply),
                "check": f"message {idx} mock bot reply contains {term}",
                "reply": reply,
            })

        sidebar = _sidebar_snapshot(store, ctx, persona_id, lead_ref)
        for section, terms in scenario["expected_sidebar"].items():
            for term in terms:
                report["checks"].append({
                    "ok": _contains(sidebar, term),
                    "check": f"sidebar section {section} contains {term}",
                })

        expected_relation_count = len(store.edges)
        sidebar_relation_count = len(sidebar.get("Todas as relacoes") or [])
        report["checks"].append({
            "ok": sidebar_relation_count == expected_relation_count,
            "check": f"message {idx} sidebar exposes all graph relations",
            "actual": sidebar_relation_count,
            "expected": expected_relation_count,
        })
        card_blob = json.dumps(sidebar, ensure_ascii=False)
        report["checks"].append({
            "ok": f"/messages/{lead_ref}" in card_blob,
            "check": f"message {idx} sidebar cards link to real conversation",
        })
        report["checks"].append({
            "ok": bool(inbound and outbound and len(store.messages_by_ref.get(str(lead_ref), [])) >= idx * 2),
            "check": f"message {idx} inbound and outbound messages stored in mock database",
            "stored_messages": len(store.messages_by_ref.get(str(lead_ref), [])),
        })

        report["message_runs"].append({
            "inbound_message": inbound,
            "outbound_message": outbound,
            "query_terms": ctx.get("query_terms"),
            "focus": {
                "slug": focus_slug,
                "graph_distance": (focus or {}).get("graph_distance"),
                "path_slugs": (focus or {}).get("path_slugs"),
            },
            "similar": ctx.get("similar"),
            "reply": reply,
            "sidebar": sidebar,
        })


def _validate_idempotency(scenario: dict, report: dict) -> None:
    store = _FakeStore()
    _install_fake_supabase(store)
    first = _register_scenario(store, scenario)
    counts_1 = (len(store.artifacts_by_key), len(store.nodes), len(store.edges))
    _register_scenario(store, scenario)
    counts_2 = (len(store.artifacts_by_key), len(store.nodes), len(store.edges))
    report["checks"].append({
        "ok": counts_1[0] == counts_2[0],
        "check": "rerunning scenario does not duplicate canonical artifacts",
        "first": counts_1[0],
        "second": counts_2[0],
    })
    report["checks"].append({
        "ok": counts_2[1] >= counts_1[1] and counts_2[2] >= counts_1[2],
        "check": "rerunning scenario keeps graph stable or additive only",
        "first": counts_1,
        "second": counts_2,
        "persona": first["persona"]["slug"],
    })


def run(scenario_path: Path, lead_ref: int) -> int:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    store = _FakeStore()
    _install_fake_supabase(store)

    report = {
        "scenario": str(scenario_path),
        "mode": "offline_mock_no_whatsapp_no_n8n",
        "checks": [],
        "message_runs": [],
        "counts": {},
    }

    registration = _register_scenario(store, scenario)
    persona = registration["persona"]
    _validate_registration(store, scenario, persona["id"], report)
    _validate_message_flow(store, scenario, persona, report, lead_ref)
    _validate_idempotency(scenario, report)

    report["counts"] = {
        "personas": len(store.personas_by_slug),
        "knowledge_items": len(store.knowledge_items),
        "artifacts": len(store.artifacts_by_key),
        "nodes": len(store.nodes),
        "edges": len(store.edges),
        "messages": sum(len(v) for v in store.messages_by_ref.values()),
    }
    expected_messages = len(scenario["test_messages"]) * 2
    report["checks"].append({
        "ok": report["counts"]["messages"] == expected_messages,
        "check": "all simulated conversation messages are stored in the mock database",
        "actual": report["counts"]["messages"],
        "expected": expected_messages,
    })
    report["ok"] = all(check.get("ok") for check in report["checks"])

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for check in report["checks"]:
        prefix = "ok" if check.get("ok") else "FAIL"
        print(f"  {prefix} {check['check']}")
    print(f"\nWROTE {REPORT_PATH}")
    if report["ok"]:
        print("PASS: Prime Higienizacao mock knowledge graph flow")
        return 0
    print("FAIL: Prime Higienizacao mock knowledge graph flow")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--lead-ref", type=int, default=91002)
    args = parser.parse_args()
    return run(Path(args.scenario), args.lead_ref)


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
Offline integration test for legacy knowledge -> knowledge_rag_* backfill.

Run:
  python tests/integration_knowledge_rag_backfill.py
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeStore:
    def __init__(self) -> None:
        self.personas = {
            "tock-fatal": {"id": "persona-tock", "slug": "tock-fatal", "name": "Tock Fatal"},
            "prime-higienizacao": {
                "id": "persona-prime",
                "slug": "prime-higienizacao",
                "name": "Prime Higienizacao",
            },
        }
        self.items: dict[str, dict] = {}
        self.kb: dict[str, dict] = {}
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.rag_entries: dict[tuple[str, str], dict] = {}
        self.rag_chunks: dict[str, list[dict]] = {}
        self.rag_links: dict[tuple[str, str, str], dict] = {}
        self.messages: dict[str, list[dict]] = {}
        self.leads = {
            101: {"id": 101, "persona_id": "persona-tock", "interesse_produto": "Modal"},
            202: {
                "id": 202,
                "persona_id": "persona-prime",
                "interesse_produto": "Higienizacao de Cadeiras Prime",
            },
        }
        self._node_no = 0
        self._edge_no = 0
        self._rag_no = 0
        self._chunk_no = 0
        self._link_no = 0

    def seed(self) -> None:
        self.items["ki-tock-product"] = {
            "id": "ki-tock-product",
            "persona_id": "persona-tock",
            "title": "Modal",
            "content_type": "product",
            "content": "Produto Modal da Tock Fatal com catalogo proprio.",
            "tags": ["product", "modal"],
            "metadata": {"slug": "modal", "aliases": ["modais"]},
            "status": "approved",
            "artifact_id": "artifact-modal",
        }
        self.items["ki-prime-product"] = {
            "id": "ki-prime-product",
            "persona_id": "persona-prime",
            "title": "Higienizacao de Cadeiras Prime",
            "content_type": "product",
            "content": "Servico de higienizacao de cadeiras. Valor de R$ 100,00 por cadeira.",
            "tags": ["product", "cadeiras"],
            "metadata": {
                "slug": "higienizacao-cadeiras-prime",
                "aliases": ["cadeira", "cadeiras"],
            },
            "status": "approved",
            "artifact_id": "artifact-cadeiras",
        }
        self.kb["kb-tock-faq"] = {
            "id": "kb-tock-faq",
            "persona_id": "persona-tock",
            "tipo": "faq",
            "categoria": "faq",
            "produto": "Modal",
            "titulo": "FAQ Catalogo Modal",
            "conteudo": (
                "Pergunta: Onde vejo o catalogo do Modal?\n"
                "Resposta: O catalogo do Modal esta disponivel no site da Tock Fatal."
            ),
            "status": "ATIVO",
            "tags": ["faq", "modal"],
        }
        self.kb["kb-prime-faq"] = {
            "id": "kb-prime-faq",
            "persona_id": "persona-prime",
            "tipo": "faq",
            "categoria": "faq",
            "produto": "Higienizacao de Cadeiras Prime",
            "titulo": "FAQ Preco Cadeiras Prime",
            "conteudo": (
                "Pergunta: Quanto custa Higienizacao de Cadeiras Prime?\n"
                "Resposta: Custa R$ 100,00 por cadeira em Novo Hamburgo."
            ),
            "status": "ATIVO",
            "tags": ["faq", "cadeiras"],
        }

    def get_persona(self, slug: str) -> dict | None:
        return deepcopy(self.personas.get(slug))

    def get_knowledge_items(self, status=None, persona_id=None, content_type=None, limit=100, offset=0):
        rows = list(self.items.values())
        if persona_id:
            rows = [r for r in rows if r.get("persona_id") == persona_id]
        if content_type:
            rows = [r for r in rows if r.get("content_type") == content_type]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return deepcopy(rows[offset:offset + limit])

    def get_kb_entries(self, persona_id=None, status="ATIVO"):
        rows = list(self.kb.values())
        if persona_id:
            rows = [r for r in rows if r.get("persona_id") == persona_id]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return deepcopy(rows)

    def get_kb_entries_by_ids(self, ids: list) -> dict:
        wanted = {str(i) for i in ids or []}
        return {k: deepcopy(v) for k, v in self.kb.items() if k in wanted}

    def upsert_knowledge_node(self, data: dict) -> dict:
        key = (data.get("persona_id"), data.get("node_type"), data.get("slug"))
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
            "node_type": data.get("node_type"),
            "slug": data.get("slug"),
            "title": data.get("title"),
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
            return deepcopy(self.edges[key])
        self._edge_no += 1
        row = {
            "id": f"edge-{self._edge_no}",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": kw.get("persona_id"),
            "weight": kw.get("weight", 1),
            "confidence": kw.get("confidence", 0.6),
        }
        self.edges[key] = row
        return deepcopy(row)

    def list_all_knowledge_graph(self, persona_id=None, limit_nodes=1500):
        nodes = [
            deepcopy(n)
            for n in self.nodes.values()
            if not persona_id or n.get("persona_id") == persona_id
        ][:limit_nodes]
        node_ids = {n["id"] for n in nodes}
        edges = [
            deepcopy(e)
            for e in self.edges.values()
            if e["source_node_id"] in node_ids or e["target_node_id"] in node_ids
        ]
        return nodes, edges

    def list_knowledge_nodes_by_type(self, node_types, persona_id=None, limit=500):
        rows = []
        for node in self.nodes.values():
            if node.get("node_type") not in node_types:
                continue
            if persona_id and node.get("persona_id") != persona_id:
                continue
            rows.append(deepcopy(node))
        return rows[:limit]

    def find_knowledge_nodes(self, term: str, persona_id=None, node_types=None, limit=25):
        folded = term.lower()
        rows = []
        for node in self.nodes.values():
            if persona_id and node.get("persona_id") != persona_id:
                continue
            if node_types and node.get("node_type") not in node_types:
                continue
            values = " ".join([
                str(node.get("slug") or ""),
                str(node.get("title") or ""),
                " ".join(node.get("tags") or []),
                " ".join(str(x) for x in (node.get("metadata") or {}).get("aliases", [])),
            ]).lower()
            if folded in values or folded.replace(" ", "-") in values:
                rows.append(deepcopy(node))
        return rows[:limit]

    def get_knowledge_neighbors(self, node_ids: list[str], max_edges=200):
        ids = set(node_ids or [])
        edges = [
            deepcopy(e)
            for e in self.edges.values()
            if e["source_node_id"] in ids or e["target_node_id"] in ids
        ][:max_edges]
        related = set(ids)
        for edge in edges:
            related.add(edge["source_node_id"])
            related.add(edge["target_node_id"])
        return [deepcopy(self.nodes[nid]) for nid in related if nid in self.nodes], edges

    def get_lead_by_ref(self, lead_ref: int):
        return deepcopy(self.leads.get(int(lead_ref)))

    def get_messages(self, lead_id: str, limit=30):
        return deepcopy(self.messages.get(str(lead_id), [])[:limit])

    def upsert_knowledge_rag_entry(self, data: dict) -> dict:
        key = (data["persona_id"], data["canonical_key"])
        existing = self.rag_entries.get(key)
        if existing:
            existing.update(deepcopy(data))
            return deepcopy(existing)
        self._rag_no += 1
        row = {**deepcopy(data), "id": f"rag-{self._rag_no}"}
        self.rag_entries[key] = row
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id: str, persona_id: str, chunks: list[dict]):
        rows = []
        for chunk in chunks:
            self._chunk_no += 1
            rows.append({
                **deepcopy(chunk),
                "id": f"chunk-{self._chunk_no}",
                "rag_entry_id": rag_entry_id,
                "persona_id": persona_id,
            })
        self.rag_chunks[rag_entry_id] = rows
        return deepcopy(rows)

    def upsert_knowledge_rag_link(self, data: dict):
        key = (data["source_entry_id"], data["target_entry_id"], data["relation_type"])
        if key in self.rag_links:
            self.rag_links[key].update(deepcopy(data))
            return deepcopy(self.rag_links[key])
        self._link_no += 1
        row = {**deepcopy(data), "id": f"rag-link-{self._link_no}"}
        self.rag_links[key] = row
        return deepcopy(row)


def _install(store: FakeStore):
    from services import supabase_client as sb

    originals = {
        name: getattr(sb, name)
        for name in [
            "get_persona",
            "get_knowledge_items",
            "get_kb_entries",
            "get_kb_entries_by_ids",
            "upsert_knowledge_node",
            "upsert_knowledge_edge",
            "list_all_knowledge_graph",
            "list_knowledge_nodes_by_type",
            "find_knowledge_nodes",
            "get_knowledge_neighbors",
            "get_lead_by_ref",
            "get_messages",
            "upsert_knowledge_rag_entry",
            "replace_knowledge_rag_chunks",
            "upsert_knowledge_rag_link",
        ]
    }
    sb.get_persona = store.get_persona
    sb.get_knowledge_items = store.get_knowledge_items
    sb.get_kb_entries = store.get_kb_entries
    sb.get_kb_entries_by_ids = store.get_kb_entries_by_ids
    sb.upsert_knowledge_node = store.upsert_knowledge_node
    sb.upsert_knowledge_edge = store.upsert_knowledge_edge
    sb.list_all_knowledge_graph = store.list_all_knowledge_graph
    sb.list_knowledge_nodes_by_type = store.list_knowledge_nodes_by_type
    sb.find_knowledge_nodes = store.find_knowledge_nodes
    sb.get_knowledge_neighbors = store.get_knowledge_neighbors
    sb.get_lead_by_ref = store.get_lead_by_ref
    sb.get_messages = store.get_messages
    sb.upsert_knowledge_rag_entry = store.upsert_knowledge_rag_entry
    sb.replace_knowledge_rag_chunks = store.replace_knowledge_rag_chunks
    sb.upsert_knowledge_rag_link = store.upsert_knowledge_rag_link
    return originals


def _restore(originals: dict):
    from services import supabase_client as sb

    for name, fn in originals.items():
        setattr(sb, name, fn)


def main() -> int:
    from services import knowledge_graph
    from services.knowledge_rag_backfill import backfill_knowledge_rag

    store = FakeStore()
    store.seed()
    originals = _install(store)
    try:
        for item in store.items.values():
            knowledge_graph.bootstrap_from_item(
                item,
                frontmatter={**(item.get("metadata") or {}), "slug": item["metadata"]["slug"]},
                body=item.get("content") or "",
                persona_id=item["persona_id"],
            )
        for kb in store.kb.values():
            knowledge_graph.bootstrap_from_item(
                {
                    "id": kb["id"],
                    "persona_id": kb["persona_id"],
                    "title": kb["titulo"],
                    "content_type": "faq",
                    "content": kb["conteudo"],
                    "tags": kb["tags"],
                    "status": kb["status"],
                },
                frontmatter={"product": kb["produto"], "tags": kb["tags"]},
                body=kb["conteudo"],
                persona_id=kb["persona_id"],
                source_table="kb_entries",
            )

        vault = ROOT / "test-artifacts" / "rag_backfill_vault"
        vault.mkdir(parents=True, exist_ok=True)
        doc = vault / "prime-faq.md"
        doc.write_text(
            "---\n"
            "cliente: prime-higienizacao\n"
            "type: faq\n"
            "title: FAQ Vault Prime\n"
            "product: Higienizacao de Cadeiras Prime\n"
            "---\n"
            "Pergunta: A Prime atende cadeiras?\n"
            "Resposta: Sim, a Prime atende cadeiras em Novo Hamburgo.\n",
            encoding="utf-8",
        )
        counts = backfill_knowledge_rag(include_vault=True, vault_path=str(vault))

        assert counts["errors"] == [], counts
        assert counts["by_source"]["knowledge_items"] == 2, counts
        assert counts["by_source"]["kb_entries"] == 2, counts
        assert counts["by_source"]["knowledge_nodes"] >= 4, counts
        assert counts["by_source"]["obsidian_vault"] == 1, counts
        assert counts["by_type"]["product"] >= 2, counts
        assert counts["by_type"]["faq"] >= 3, counts
        assert store.rag_chunks and all(store.rag_chunks.values()), store.rag_chunks
        assert store.rag_links, "semantic RAG links were not created"

        entries = list(store.rag_entries.values())
        tock_products = [e for e in entries if e["persona_id"] == "persona-tock" and e["content_type"] == "product"]
        tock_faqs = [e for e in entries if e["persona_id"] == "persona-tock" and e["content_type"] == "faq"]
        prime_products = [e for e in entries if e["persona_id"] == "persona-prime" and e["content_type"] == "product"]
        prime_faqs = [e for e in entries if e["persona_id"] == "persona-prime" and e["content_type"] == "faq"]
        assert tock_products and tock_faqs, entries
        assert prime_products and prime_faqs, entries
        assert any(e.get("question") for e in tock_faqs + prime_faqs), entries

        ctx_tock = knowledge_graph.get_chat_context(101, user_text="Onde vejo o catalogo do Modal?")
        ctx_prime = knowledge_graph.get_chat_context(202, user_text="Quanto custa Higienizacao de Cadeiras Prime?")
        assert any(n.get("node_type") == "product" and n.get("slug") == "modal" for n in ctx_tock["nodes"]), ctx_tock
        assert any(n.get("node_type") == "faq" for n in ctx_tock["nodes"]), ctx_tock
        assert any(
            n.get("node_type") == "product" and n.get("slug") == "higienizacao-cadeiras-prime"
            for n in ctx_prime["nodes"]
        ), ctx_prime
        assert any(n.get("node_type") == "faq" for n in ctx_prime["nodes"]), ctx_prime
        assert ctx_tock["edges"] and ctx_prime["edges"], (ctx_tock, ctx_prime)
    finally:
        _restore(originals)

    print("PASS knowledge RAG backfill: legacy sources -> entries/chunks/links, graph/sidebar context intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

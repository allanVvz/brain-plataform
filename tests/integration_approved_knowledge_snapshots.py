# -*- coding: utf-8 -*-
"""
Offline validation for approved_knowledge_snapshots -> knowledge_rag_* bridge.

Run:
  python tests/integration_approved_knowledge_snapshots.py
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class FakeStore:
    def __init__(self) -> None:
        self.persona = {"id": "persona-tock", "slug": "tock-fatal", "name": "Tock Fatal"}
        self.nodes = [
            self.node("n-persona", "persona", "self", "Tock Fatal"),
            self.node("n-brand", "brand", "tock-fatal", "Tock Fatal", "Marca feminina de venda direta."),
            self.node("n-briefing", "briefing", "campanha-inverno-modal", "Campanha de inverno", "Foco em modais de fabricacao propria."),
            self.node("n-audience", "audience", "empreendedoras", "Empreendedoras", "Revendedoras que compram kits."),
            self.node("n-product", "product", "kit-modal-1", "Kit Modal 1", "Kit Modal 1 para revenda."),
            self.node(
                "n-faq",
                "faq",
                "preco-kit-modal-1",
                "Qual o preco do Kit Modal 1?",
                "Pergunta: Qual o preco do Kit Modal 1?\nResposta: O Kit Modal 1 esta disponivel por R$ 59,90.",
                source_table="knowledge_items",
                source_id="item-faq",
                metadata={"rules": ["Nao prometer estoque sem confirmacao."], "tone": "direto e acolhedor"},
            ),
        ]
        self.edges = [
            self.edge("e1", "n-persona", "n-brand", "contains"),
            self.edge("e2", "n-brand", "n-briefing", "contains"),
            self.edge("e3", "n-briefing", "n-audience", "contains"),
            self.edge("e4", "n-audience", "n-product", "contains"),
            self.edge("e5", "n-product", "n-faq", "contains"),
        ]
        self.item = {
            "id": "item-faq",
            "persona_id": self.persona["id"],
            "content_type": "faq",
            "title": "Qual o preco do Kit Modal 1?",
            "content": "Pergunta: Qual o preco do Kit Modal 1?\nResposta: O Kit Modal 1 esta disponivel por R$ 59,90.",
            "metadata": {},
            "tags": ["kit-modal-1"],
            "status": "approved",
        }
        self.snapshots: list[dict] = []
        self.rag_entries: list[dict] = []
        self.chunks: list[dict] = []
        self.embedded_edges: list[dict] = []
        self.updated_nodes: list[dict] = []
        self.updated_items: list[dict] = []

    def node(self, node_id, node_type, slug, title, summary="", source_table=None, source_id=None, metadata=None):
        return {
            "id": node_id,
            "persona_id": self.persona["id"],
            "node_type": node_type,
            "slug": slug,
            "title": title,
            "summary": summary,
            "source_table": source_table,
            "source_id": source_id,
            "tags": [slug],
            "metadata": metadata or {},
            "status": "validated" if node_type != "faq" else "pending",
            "level": 75 if node_type == "faq" else 40,
            "importance": 0.8,
            "confidence": 0.9,
        }

    def edge(self, edge_id, src, tgt, rel):
        return {
            "id": edge_id,
            "persona_id": self.persona["id"],
            "source_node_id": src,
            "target_node_id": tgt,
            "relation_type": rel,
            "metadata": {"primary_tree": True, "active": True},
            "weight": 1,
        }

    def get_knowledge_node(self, node_id):
        return deepcopy(next((n for n in self.nodes if n["id"] == node_id), None))

    def get_persona_by_id(self, persona_id):
        return deepcopy(self.persona) if persona_id == self.persona["id"] else None

    def get_knowledge_item(self, item_id):
        return deepcopy(self.item) if item_id == self.item["id"] else None

    def list_all_knowledge_graph(self, persona_id=None, limit_nodes=2500):
        return deepcopy(self.nodes), deepcopy(self.edges)

    def upsert_approved_knowledge_snapshot(self, data):
        row = {**deepcopy(data), "id": "snapshot-1"}
        self.snapshots = [row]
        return deepcopy(row)

    def update_approved_knowledge_snapshot(self, snapshot_id, data):
        self.snapshots[0].update(deepcopy(data))
        return deepcopy(self.snapshots[0])

    def upsert_knowledge_rag_entry(self, data):
        row = {**deepcopy(data), "id": "rag-entry-1"}
        self.rag_entries = [row]
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id, persona_id, chunks):
        self.chunks = [
            {**deepcopy(chunk), "id": f"chunk-{idx}", "rag_entry_id": rag_entry_id, "persona_id": persona_id}
            for idx, chunk in enumerate(chunks)
        ]
        return deepcopy(self.chunks)

    def update_knowledge_node(self, node_id, data):
        self.updated_nodes.append({"node_id": node_id, "data": deepcopy(data)})
        return {"id": node_id, **deepcopy(data)}

    def update_knowledge_item(self, item_id, data):
        self.updated_items.append({"item_id": item_id, "data": deepcopy(data)})
        return {"id": item_id, **deepcopy(data)}

    def ensure_embedded_node(self, persona_id):
        return self.node("n-embedded", "embedded", "embedded-default", "Embedded")

    def upsert_knowledge_edge(self, source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        row = {
            "id": "edge-embedded-1",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": metadata or {},
        }
        self.embedded_edges = [row]
        return deepcopy(row)


def main() -> int:
    from services import approved_knowledge_snapshots, knowledge_graph, supabase_client

    store = FakeStore()
    originals = {
        name: getattr(supabase_client, name)
        for name in [
            "get_knowledge_node",
            "get_persona_by_id",
            "get_knowledge_item",
            "list_all_knowledge_graph",
            "upsert_approved_knowledge_snapshot",
            "update_approved_knowledge_snapshot",
            "upsert_knowledge_rag_entry",
            "replace_knowledge_rag_chunks",
            "update_knowledge_node",
            "update_knowledge_item",
            "ensure_embedded_node",
            "upsert_knowledge_edge",
        ]
    }
    original_root = knowledge_graph._ensure_persona_root
    try:
        for name in originals:
            setattr(supabase_client, name, getattr(store, name))
        knowledge_graph._ensure_persona_root = lambda _pid: store.get_knowledge_node("n-persona")
        result = approved_knowledge_snapshots.publish_approved_node("n-faq", approved_by=None)
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)
        knowledge_graph._ensure_persona_root = original_root

    assert result["success"] is True, result
    assert result["approved_snapshot_id"] == "snapshot-1", result
    assert result["rag_entry_id"] == "rag-entry-1", result
    assert result["rag_chunk_ids"] == ["chunk-0"], result
    assert store.snapshots[0]["status"] == "active", store.snapshots
    assert store.rag_entries[0]["status"] == "active", store.rag_entries
    chunk = store.chunks[0]
    assert "Marca: Marca feminina" in chunk["chunk_text"], chunk["chunk_text"]
    assert "Briefing: Foco em modais" in chunk["chunk_text"], chunk["chunk_text"]
    assert "Publico: Revendedoras" in chunk["chunk_text"], chunk["chunk_text"]
    assert "Produto: Kit Modal 1" in chunk["chunk_text"], chunk["chunk_text"]
    assert chunk["metadata"]["approved_snapshot_id"] == "snapshot-1", chunk
    assert chunk["metadata"]["source_node_id"] == "n-faq", chunk
    assert chunk["metadata"]["content_type"] == "faq", chunk
    assert chunk["metadata"]["status"] == "active", chunk
    print("PASS approved snapshot bridge: graph FAQ -> snapshot -> rag entry -> contextual chunk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

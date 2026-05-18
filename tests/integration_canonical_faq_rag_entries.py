#!/usr/bin/env python3
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


FAQ_MARKDOWN = """# FAQ Golden Dataset - Copy Modal 2

## Perguntas e respostas

### 1. Qual preco posso informar sobre Modal 2?

**Resposta:** O dado comercial confirmado no galho cita R$ 59,90. Qualquer variacao por quantidade, desconto, frete ou condicao de pagamento precisa ser validada antes de responder.

### 2. Tem estoque ou prazo confirmado para Modal 2?

**Resposta:** Estoque, prazo e disponibilidade nao estao confirmados neste galho. Esses dados precisam ser verificados antes de prometer ao cliente.

### 3. Como responder de forma curta no WhatsApp sobre Modal 2?

**Resposta:** Modal 2 pode fazer sentido para mulheres que buscam beleza e mudanca. Para preco final, estoque e prazo, confirmo com o atendimento antes de te passar.
"""


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


class CanonicalFaqStore:
    def __init__(self, snapshot_enabled: bool = True, weak_answer: bool = False) -> None:
        self.snapshot_enabled = snapshot_enabled
        self.persona = {"id": "persona-tock", "slug": "tock-fatal", "name": "Tock Fatal"}
        faq_text = FAQ_MARKDOWN
        if weak_answer:
            faq_text = "### 1. Qual preco posso informar?\n\n**Resposta:** Qual preco posso informar?"
        self.nodes = [
            self.node("n-persona", "persona", "self", "Tock Fatal", "Tock Fatal"),
            self.node("n-briefing", "briefing", "campanha-modais-10", "Campanha Modais 10", "Campanha de Modais com foco em venda e validacao comercial."),
            self.node("n-audience", "audience", "mulheres-que-aspiram-mudancas", "Mulheres que aspiram mudancas", "Mulheres que aspiram mudancas na vida e buscam beleza."),
            self.node("n-product", "product", "modal-2-branch-1", "Modal 2", "Produto Modal 2. Informacao confirmada no galho: produtos a partir de R$ 59,90."),
            self.node("n-copy", "copy", "copy-campanha-modais-modal-2-branch-1", "Copy Modal 2", "Descubra a beleza que voce pode alcancar com nossos modais."),
            self.node(
                "n-faq",
                "faq",
                "faq-golden-dataset-copy-campanha-modais-modal-2-branch-1",
                "FAQ Golden Dataset - Copy Modal 2",
                faq_text,
                source_table="knowledge_items",
                source_id="item-faq",
                metadata={
                    "faq_document_type": "golden_dataset",
                    "golden_dataset": True,
                    "question_count": 3,
                    "session_id": "dd143c25-3c55-40fa-b36b-065f6874178b",
                },
            ),
        ]
        self.edges = [
            self.edge("e1", "n-persona", "n-briefing", "contains"),
            self.edge("e2", "n-briefing", "n-audience", "contains"),
            self.edge("e3", "n-audience", "n-product", "offers_product"),
            self.edge("e4", "n-product", "n-copy", "supports_copy"),
            self.edge("e5", "n-copy", "n-faq", "answers_question"),
        ]
        self.item = {
            "id": "item-faq",
            "persona_id": self.persona["id"],
            "content_type": "faq",
            "title": "FAQ Golden Dataset - Copy Modal 2",
            "content": faq_text,
            "metadata": {},
            "tags": ["modal-2"],
            "status": "approved",
        }
        self.snapshots: list[dict] = []
        self.rag_entries: list[dict] = []
        self.chunks: list[dict] = []
        self.updated_nodes: list[dict] = []
        self.updated_items: list[dict] = []
        self.embedded_edges: list[dict] = []

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
            "status": "validated",
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
        if not self.snapshot_enabled:
            return {}
        row = {**deepcopy(data), "id": "snapshot-1"}
        self.snapshots = [row]
        return deepcopy(row)

    def update_approved_knowledge_snapshot(self, snapshot_id, data):
        self.snapshots[0].update(deepcopy(data))
        return deepcopy(self.snapshots[0])

    def upsert_knowledge_rag_entry(self, data):
        row = {**deepcopy(data), "id": f"rag-entry-{len(self.rag_entries) + 1}"}
        self.rag_entries.append(row)
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id, persona_id, chunks):
        rows = [
            {**deepcopy(chunk), "id": f"chunk-{len(self.chunks) + idx + 1}", "rag_entry_id": rag_entry_id, "persona_id": persona_id}
            for idx, chunk in enumerate(chunks)
        ]
        self.chunks.extend(rows)
        return deepcopy(rows)

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


def with_store(store: CanonicalFaqStore):
    from services import approved_knowledge_snapshots, knowledge_graph, supabase_client

    patched = [
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
    originals = {name: getattr(supabase_client, name) for name in patched}
    original_root = knowledge_graph._ensure_persona_root
    try:
        for name in patched:
            setattr(supabase_client, name, getattr(store, name))
        knowledge_graph._ensure_persona_root = lambda _pid: store.get_knowledge_node("n-persona")
        return approved_knowledge_snapshots.publish_approved_node("n-faq")
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)
        knowledge_graph._ensure_persona_root = original_root


def test_no_entry_without_snapshot() -> None:
    store = CanonicalFaqStore(snapshot_enabled=False)
    try:
        with_store(store)
    except RuntimeError as exc:
        _assert("Approved snapshot was not created" in str(exc), "missing snapshot blocks RAG publication")
    else:
        raise AssertionError("publication should fail without snapshot")
    _assert(not store.rag_entries, "no RAG entry is created without snapshot")


def test_golden_dataset_becomes_canonical_entries_and_chunks() -> None:
    store = CanonicalFaqStore()
    result = with_store(store)
    _assert(result["success"] is True, "publication succeeds")
    _assert(result["approved_snapshot_id"] == "snapshot-1", "snapshot is created first")
    _assert(len(store.rag_entries) == 3, "three FAQ questions become three RAG entries")
    _assert(len(store.chunks) == 3, "three FAQ questions become three chunks")
    _assert(result["rag_entry_ids"] == ["rag-entry-1", "rag-entry-2", "rag-entry-3"], "result returns all canonical entry ids")
    _assert(result["rag_chunk_ids"] == ["chunk-1", "chunk-2", "chunk-3"], "result returns all chunk ids")
    for entry in store.rag_entries:
        _assert(entry["source_snapshot_id"] == "snapshot-1", "entry has source_snapshot_id")
        _assert(entry["source_node_id"] == "n-faq", "entry has source_node_id")
        _assert(entry["session_id"] == "dd143c25-3c55-40fa-b36b-065f6874178b", "entry has session_id")
        _assert(entry["question"] and entry["answer"] and entry["question"] != entry["answer"], "entry has specific question and answer")
        _assert(len(entry["answer"]) < len(FAQ_MARKDOWN), "entry answer is not the whole markdown")
        _assert(entry["summary"] and len(entry["summary"]) < 320, "entry has short summary")
        _assert((entry["metadata"] or {}).get("branch_context", {}).get("path"), "entry metadata has branch_context")
    for chunk in store.chunks:
        text = chunk["chunk_text"]
        meta = chunk["metadata"]
        for label in ["Tipo:", "Marca/Persona:", "Brand:", "Briefing:", "Publico:", "Produto:", "Copy/Oferta:", "Pergunta:", "Resposta aprovada:", "Regras:", "Tom:", "Caminho da branch:", "Relacoes:"]:
            _assert(label in text, f"chunk contains {label}")
        _assert(meta["chunk_status"] == "pending_embedding", "chunk waits for embedding")
        _assert(meta["ready_for_production"] is False, "chunk is not production ready before embedding")
        _assert(meta["session_id"] == "dd143c25-3c55-40fa-b36b-065f6874178b", "chunk has session_id")
        _assert(meta["branch_context"]["path"], "chunk metadata has branch_context")
        _assert(meta["hierarchy_path"][0] == "self", "chunk hierarchy starts at persona/root slug")
        _assert(meta["branch_types"] == ["persona", "briefing", "audience", "product", "copy", "faq"], "chunk branch types are canonical")


def test_weak_answer_blocks_active_chunks() -> None:
    store = CanonicalFaqStore(weak_answer=True)
    result = with_store(store)
    _assert(result["success"] is False, "weak answer blocks publication")
    _assert(result["status"] == "needs_review", "weak answer marks snapshot needs_review")
    _assert(not store.rag_entries, "weak answer does not create RAG entries")
    _assert(not store.chunks, "weak answer does not create chunks")


def main() -> int:
    test_no_entry_without_snapshot()
    test_golden_dataset_becomes_canonical_entries_and_chunks()
    test_weak_answer_blocks_active_chunks()
    print("PASS canonical FAQ RAG entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

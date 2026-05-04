# -*- coding: utf-8 -*-
"""
Offline integration test for database-first KB RAG intake.

Validates the deterministic first version of the intake pipeline without
Supabase, n8n, or an LLM.

Run:
  python tests/integration_knowledge_rag_intake.py
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
        self.persona = {
            "id": "persona-prime",
            "slug": "prime-higienizacao",
            "name": "Prime Higienizacao",
        }
        self.intakes: list[dict] = []
        self.entries: list[dict] = []
        self.chunks: list[dict] = []
        self.graph_calls: list[dict] = []
        self.products = [
            {
                "id": "node-product-chair",
                "persona_id": self.persona["id"],
                "node_type": "product",
                "slug": "higienizacao-cadeiras-prime",
                "title": "Higienizacao-Cadeiras-Prime",
                "tags": ["higienizacao-cadeiras-prime", "cadeiras"],
                "metadata": {"aliases": ["Higienizacao de Cadeiras Prime"]},
            }
        ]

    def get_persona(self, slug: str) -> dict | None:
        return deepcopy(self.persona) if slug == self.persona["slug"] else None

    def list_knowledge_nodes_by_type(self, node_types, persona_id=None, limit=500):
        if "product" not in node_types or persona_id != self.persona["id"]:
            return []
        return deepcopy(self.products[:limit])

    def insert_knowledge_intake_message(self, data: dict) -> dict:
        row = {**deepcopy(data), "id": f"intake-{len(self.intakes) + 1}"}
        self.intakes.append(row)
        return deepcopy(row)

    def update_knowledge_intake_message(self, intake_id: str, data: dict) -> None:
        for row in self.intakes:
            if row["id"] == intake_id:
                row.update(deepcopy(data))
                return
        raise AssertionError(f"missing intake {intake_id}")

    def upsert_knowledge_rag_entry(self, data: dict) -> dict:
        row = {**deepcopy(data), "id": "rag-entry-1"}
        self.entries.append(row)
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id: str, persona_id: str, chunks: list[dict]) -> list[dict]:
        self.chunks = [
            {**deepcopy(chunk), "id": f"chunk-{idx + 1}", "rag_entry_id": rag_entry_id, "persona_id": persona_id}
            for idx, chunk in enumerate(chunks)
        ]
        return deepcopy(self.chunks)


def main() -> int:
    from services import knowledge_graph, knowledge_rag_intake, supabase_client

    store = FakeStore()

    originals = {
        "get_persona": supabase_client.get_persona,
        "list_knowledge_nodes_by_type": supabase_client.list_knowledge_nodes_by_type,
        "insert_knowledge_intake_message": supabase_client.insert_knowledge_intake_message,
        "update_knowledge_intake_message": supabase_client.update_knowledge_intake_message,
        "upsert_knowledge_rag_entry": supabase_client.upsert_knowledge_rag_entry,
        "replace_knowledge_rag_chunks": supabase_client.replace_knowledge_rag_chunks,
        "bootstrap_from_item": knowledge_graph.bootstrap_from_item,
    }

    def fake_bootstrap(item, frontmatter=None, body="", persona_id=None, source_table="knowledge_items"):
        call = {
            "item": deepcopy(item),
            "frontmatter": deepcopy(frontmatter or {}),
            "body": body,
            "persona_id": persona_id,
            "source_table": source_table,
        }
        store.graph_calls.append(call)
        return {
            "id": "graph-node-1",
            "node_type": item["content_type"],
            "slug": frontmatter.get("slug"),
            "title": item["title"],
        }

    try:
        supabase_client.get_persona = store.get_persona
        supabase_client.list_knowledge_nodes_by_type = store.list_knowledge_nodes_by_type
        supabase_client.insert_knowledge_intake_message = store.insert_knowledge_intake_message
        supabase_client.update_knowledge_intake_message = store.update_knowledge_intake_message
        supabase_client.upsert_knowledge_rag_entry = store.upsert_knowledge_rag_entry
        supabase_client.replace_knowledge_rag_chunks = store.replace_knowledge_rag_chunks
        knowledge_graph.bootstrap_from_item = fake_bootstrap

        result = knowledge_rag_intake.process_intake(
            persona_slug="prime-higienizacao",
            source="manual",
            raw_text=(
                "Pergunta: Quanto custa Higienizacao de Cadeiras Prime?\n"
                "Resposta: A Higienizacao de Cadeiras Prime custa R$ 100,00 por cadeira em Novo Hamburgo."
            ),
            validate=True,
        )
    finally:
        for name, fn in originals.items():
            if name == "bootstrap_from_item":
                knowledge_graph.bootstrap_from_item = fn
            else:
                setattr(supabase_client, name, fn)

    cls = result["classification"]
    entry = result["rag_entry"]
    assert cls["content_type"] == "faq", cls
    assert cls["question"] == "Quanto custa Higienizacao de Cadeiras Prime?", cls
    assert cls["answer"].startswith("A Higienizacao de Cadeiras Prime custa"), cls
    assert cls["products"] == ["higienizacao-cadeiras-prime"], cls
    assert cls["metadata"]["price"]["display"] == "R$ 100,00 por cadeira", cls
    assert entry["status"] == "validated", entry
    assert entry["canonical_key"] == "faq:quanto-custa-higienizacao-de-cadeiras-prime", entry
    assert len(result["chunks"]) == 1, result["chunks"]
    assert "Pergunta:" in result["chunks"][0]["chunk_text"], result["chunks"]
    assert store.intakes[0]["status"] == "rag_created", store.intakes
    assert store.graph_calls[0]["source_table"] == "knowledge_rag_entries", store.graph_calls
    assert store.graph_calls[0]["frontmatter"]["product"] == ["higienizacao-cadeiras-prime"], store.graph_calls

    print("PASS knowledge RAG intake: FAQ -> RAG entry -> chunk -> graph mirror")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
Smoke test for the FAQ-only RAG gate.

Validates the architectural rule that ONLY content_type='faq' generates
records in knowledge_rag_entries / knowledge_rag_chunks. Other content
types (product, copy, rule, brand, tone, entity, ...) still produce a
graph node but must NOT touch the vector RAG layer.

Single helper of truth: services.knowledge_rag_intake.is_rag_eligible.

Run:
  python tests/smoke_rag_faq_only_gate.py
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
        self.persona = {
            "id": "persona-test",
            "slug": "test-persona",
            "name": "Test Persona",
        }
        self.intakes: list[dict] = []
        self.entries: list[dict] = []
        self.chunks: list[dict] = []
        self.graph_calls: list[dict] = []

    def get_persona(self, slug: str) -> dict | None:
        return deepcopy(self.persona) if slug == self.persona["slug"] else None

    def list_knowledge_nodes_by_type(self, node_types, persona_id=None, limit=500):
        return []

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
        row = {**deepcopy(data), "id": f"rag-entry-{len(self.entries) + 1}"}
        self.entries.append(row)
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id: str, persona_id: str, chunks: list[dict]) -> list[dict]:
        new_chunks = [
            {**deepcopy(chunk), "id": f"chunk-{len(self.chunks) + idx + 1}", "rag_entry_id": rag_entry_id, "persona_id": persona_id}
            for idx, chunk in enumerate(chunks)
        ]
        self.chunks.extend(new_chunks)
        return deepcopy(new_chunks)


def _patch(store: FakeStore):
    from services import knowledge_graph, supabase_client

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
            "source_table": source_table,
            "content_type": item.get("content_type"),
        }
        store.graph_calls.append(call)
        return {
            "id": f"graph-node-{len(store.graph_calls)}",
            "node_type": item.get("content_type"),
            "slug": (frontmatter or {}).get("slug"),
            "title": item.get("title"),
        }

    def fake_ensure(_node, **_kwargs):
        return None

    def fake_repair(_persona_id, _node_ids):
        return {"fallback_nodes": []}

    supabase_client.get_persona = store.get_persona
    supabase_client.list_knowledge_nodes_by_type = store.list_knowledge_nodes_by_type
    supabase_client.insert_knowledge_intake_message = store.insert_knowledge_intake_message
    supabase_client.update_knowledge_intake_message = store.update_knowledge_intake_message
    supabase_client.upsert_knowledge_rag_entry = store.upsert_knowledge_rag_entry
    supabase_client.replace_knowledge_rag_chunks = store.replace_knowledge_rag_chunks
    knowledge_graph.bootstrap_from_item = fake_bootstrap
    originals["ensure_main_tree_connection"] = knowledge_graph.ensure_main_tree_connection
    originals["repair_primary_tree_connections"] = knowledge_graph.repair_primary_tree_connections
    knowledge_graph.ensure_main_tree_connection = fake_ensure
    knowledge_graph.repair_primary_tree_connections = fake_repair

    def restore():
        for name, fn in originals.items():
            if name in {"bootstrap_from_item", "ensure_main_tree_connection", "repair_primary_tree_connections"}:
                setattr(knowledge_graph, name, fn)
            else:
                setattr(supabase_client, name, fn)

    return restore


def test_helper():
    from services.knowledge_rag_intake import is_rag_eligible

    assert is_rag_eligible("faq") is True
    assert is_rag_eligible("FAQ") is True
    assert is_rag_eligible(" faq ") is True
    for noisy in ("product", "copy", "rule", "brand", "tone", "entity", "campaign", "briefing", "general_note", None, ""):
        assert is_rag_eligible(noisy) is False, f"is_rag_eligible({noisy!r}) should be False"
    print("PASS is_rag_eligible: only 'faq' is RAG-eligible today")


def test_faq_goes_to_rag():
    from services import knowledge_rag_intake

    store = FakeStore()
    restore = _patch(store)
    try:
        result = knowledge_rag_intake.process_intake(
            persona_slug=store.persona["slug"],
            source="smoke",
            raw_text="Pergunta: Qual o frete?\nResposta: Gratis acima de R$ 200.",
            content_type="faq",
            validate=True,
        )
    finally:
        restore()

    assert result["rag_eligible"] is True, result
    assert result["rag_entry"] is not None, result
    assert len(store.entries) == 1, store.entries
    assert len(store.chunks) == 1, store.chunks
    assert store.intakes[0]["status"] == "rag_created", store.intakes
    assert store.graph_calls and store.graph_calls[0]["source_table"] == "knowledge_rag_entries"
    print("PASS process_intake(content_type=faq): writes RAG entry + chunk + graph mirror")


def test_non_faq_skips_rag():
    from services import knowledge_rag_intake

    for noisy_type in ("product", "copy", "rule", "brand", "tone"):
        store = FakeStore()
        restore = _patch(store)
        try:
            result = knowledge_rag_intake.process_intake(
                persona_slug=store.persona["slug"],
                source="smoke",
                raw_text=f"Conteudo bruto de {noisy_type} aprovado pelo operador.",
                content_type=noisy_type,
                title=f"Item {noisy_type}",
                validate=True,
            )
        finally:
            restore()

        assert result["rag_eligible"] is False, (noisy_type, result)
        assert result["rag_entry"] is None, (noisy_type, result)
        assert store.entries == [], (noisy_type, store.entries)
        assert store.chunks == [], (noisy_type, store.chunks)
        assert store.intakes[0]["status"] == "graph_only", (noisy_type, store.intakes)
        # Graph mirror must STILL happen — the rule is "RAG=FAQ", not "graph=FAQ".
        assert store.graph_calls, (noisy_type, store.graph_calls)
        assert store.graph_calls[0]["source_table"] == "knowledge_intake_messages", (noisy_type, store.graph_calls)
    print("PASS process_intake(non-FAQ types): graph mirror but NO RAG entry/chunk")


if __name__ == "__main__":
    test_helper()
    test_faq_goes_to_rag()
    test_non_faq_skips_rag()
    print("OK all FAQ-only RAG gate smoke checks passed")

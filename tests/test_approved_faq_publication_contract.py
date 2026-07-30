from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class _Result:
    def __init__(self, data):
        self.data = data


class _ItemsQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters: list[tuple[str, str, object]] = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        self.filters.append(("eq", _args[0], _args[1]))
        return self

    def in_(self, *_args, **_kwargs):
        self.filters.append(("in", _args[0], set(_args[1])))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = list(self.rows)
        for mode, key, value in self.filters:
            if mode == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif mode == "in":
                rows = [row for row in rows if row.get(key) in value]
        return _Result(deepcopy(rows))


class _Client:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        if name == "knowledge_items":
            return _ItemsQuery(self.store.items)
        if name == "knowledge_nodes":
            return _ItemsQuery(self.store.nodes)
        raise AssertionError(f"unexpected table {name}")


class _Store:
    def __init__(self, *, create_edge: bool = True, existing_edge: bool = True, existing_chunks: int = 1):
        self.create_edge = create_edge
        self.persona = {"id": "persona-1", "slug": "brand-one", "name": "Brand One"}
        self.items = [
            {
                "id": "item-faq",
                "persona_id": "persona-1",
                "content_type": "faq",
                "title": "Como comprar?",
                "content": "Pergunta: Como comprar?\nResposta: Chame o atendimento e informe o produto desejado para receber disponibilidade, preco final e forma de envio confirmados.",
                "metadata": {},
                "tags": ["faq"],
                "status": "approved",
            }
        ]
        self.nodes = [
            self.node("n-persona", "persona", "self", "Brand One", "Marca principal."),
            self.node("n-product", "product", "produto-a", "Produto A", "Produto A confirmado."),
            self.node(
                "n-faq",
                "faq",
                "como-comprar",
                "Como comprar?",
                self.items[0]["content"],
                source_table="knowledge_items",
                source_id="item-faq",
            ),
        ]
        self.embedded = self.node("n-embedded", "embedded", "embedded-default", "Embedded")
        self.edges = [
            self.edge("e-product", "n-persona", "n-product", "contains", primary=True),
            self.edge("e-faq", "n-product", "n-faq", "contains", primary=True),
        ]
        if existing_edge:
            self.edges.append(self.edge("e-embedded", "n-faq", "n-embedded", "manual", primary=False))
        self.snapshots = [
            {
                "id": "snapshot-1",
                "source_node_id": "n-faq",
                "rag_entry_id": "rag-1",
                "metadata": {"rag_entry_ids": ["rag-1"]},
            }
        ]
        self.rag_entries: list[dict] = []
        self.chunks: list[dict] = []
        self.chunk_counts = existing_chunks
        self.markdown_rebuilt: list[str] = []

    def node(self, node_id, node_type, slug, title, summary="", source_table=None, source_id=None):
        return {
            "id": node_id,
            "persona_id": "persona-1",
            "node_type": node_type,
            "slug": slug,
            "title": title,
            "summary": summary,
            "source_table": source_table,
            "source_id": source_id,
            "tags": [slug],
            "metadata": {},
            "status": "validated",
            "level": 75 if node_type == "faq" else 40,
            "importance": 0.8,
            "confidence": 0.9,
        }

    def edge(self, edge_id, src, tgt, rel, *, primary):
        return {
            "id": edge_id,
            "persona_id": "persona-1",
            "source_node_id": src,
            "target_node_id": tgt,
            "relation_type": rel,
            "metadata": {"primary_tree": primary, "active": True},
            "weight": 1,
        }

    def get_client(self):
        return _Client(self)

    def get_knowledge_node(self, node_id):
        if node_id == "n-embedded":
            return deepcopy(self.embedded)
        return deepcopy(next((n for n in self.nodes if n["id"] == node_id), None))

    def get_persona_by_id(self, persona_id):
        return deepcopy(self.persona) if persona_id == "persona-1" else None

    def get_knowledge_item(self, item_id):
        return deepcopy(next((item for item in self.items if item["id"] == item_id), None))

    def get_knowledge_node_for_source(self, source_table, source_id, persona_id=None):
        return deepcopy(next((n for n in self.nodes if n.get("source_table") == source_table and n.get("source_id") == source_id), None))

    def list_all_knowledge_graph(self, persona_id=None, limit_nodes=2500):
        return deepcopy([*self.nodes, self.embedded]), deepcopy(self.edges)

    def list_edges_for_nodes(self, node_ids):
        ids = set(node_ids)
        return deepcopy([e for e in self.edges if e["source_node_id"] in ids or e["target_node_id"] in ids])

    def ensure_embedded_node(self, persona_id):
        return deepcopy(self.embedded)

    def upsert_knowledge_edge(self, source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        if not self.create_edge:
            return None
        edge = self.edge("e-embedded-new", source_node_id, target_node_id, relation_type, primary=False)
        edge["metadata"] = metadata or {}
        self.edges.append(edge)
        return deepcopy(edge)

    def upsert_approved_knowledge_snapshot(self, data):
        row = {**deepcopy(data), "id": "snapshot-1"}
        self.snapshots = [row]
        return deepcopy(row)

    def update_approved_knowledge_snapshot(self, snapshot_id, data):
        self.snapshots[0].update(deepcopy(data))
        return deepcopy(self.snapshots[0])

    def list_approved_snapshots_for_nodes(self, node_ids):
        return {row["source_node_id"]: deepcopy(row) for row in self.snapshots if row.get("source_node_id") in node_ids}

    def upsert_knowledge_rag_entry(self, data):
        row = {**deepcopy(data), "id": "rag-1"}
        self.rag_entries.append(row)
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id, persona_id, chunks):
        self.chunk_counts = len(chunks)
        self.chunks = [
            {**deepcopy(chunk), "id": "chunk-1", "rag_entry_id": rag_entry_id, "persona_id": persona_id}
            for chunk in chunks
        ]
        return deepcopy(self.chunks)

    def count_knowledge_rag_chunks_by_entry_ids(self, entry_ids):
        return {entry_id: self.chunk_counts for entry_id in entry_ids}

    def update_knowledge_node(self, node_id, data):
        return {"id": node_id, **deepcopy(data)}

    def update_knowledge_item(self, item_id, data):
        return {"id": item_id, **deepcopy(data)}


def _patch(monkeypatch, store: _Store):
    from services import approved_knowledge_snapshots, embedded_markdown, knowledge_graph, supabase_client

    for name in [
        "get_client",
        "get_knowledge_node",
        "get_persona_by_id",
        "get_knowledge_item",
        "get_knowledge_node_for_source",
        "list_all_knowledge_graph",
        "list_edges_for_nodes",
        "ensure_embedded_node",
        "upsert_knowledge_edge",
        "upsert_approved_knowledge_snapshot",
        "update_approved_knowledge_snapshot",
        "list_approved_snapshots_for_nodes",
        "upsert_knowledge_rag_entry",
        "replace_knowledge_rag_chunks",
        "count_knowledge_rag_chunks_by_entry_ids",
        "update_knowledge_node",
        "update_knowledge_item",
    ]:
        monkeypatch.setattr(supabase_client, name, getattr(store, name))
    monkeypatch.setattr(knowledge_graph, "_ensure_persona_root", lambda _pid: store.get_knowledge_node("n-persona"))
    monkeypatch.setattr(embedded_markdown, "rebuild_embedded_markdown", lambda pid: store.markdown_rebuilt.append(pid) or "# Embedded\n")
    return approved_knowledge_snapshots


def test_publish_approved_faq_requires_embedded_edge(monkeypatch):
    service = _patch(monkeypatch, _Store(create_edge=False, existing_edge=False, existing_chunks=0))

    try:
        service.publish_approved_node("n-faq", require_rag_for_faq=True)
    except RuntimeError as exc:
        assert "FAQ -> Embedded edge was not created" in str(exc)
    else:
        raise AssertionError("publication should fail when embedded edge is missing")


def test_publish_approved_faq_rebuilds_embedded_markdown(monkeypatch):
    store = _Store(existing_edge=False, existing_chunks=0)
    service = _patch(monkeypatch, store)

    result = service.publish_approved_node("n-faq", require_rag_for_faq=True)

    assert result["success"] is True
    assert result["embedded_edge_id"] == "e-embedded-new"
    assert result["rag_chunk_ids"] == ["chunk-1"]
    assert store.markdown_rebuilt == ["persona-1"]
    assert store.edges[-1]["relation_type"] == "visible_to_agent"


def test_publish_approved_faq_reuses_existing_embedded_edge(monkeypatch):
    store = _Store(existing_edge=True, existing_chunks=0)
    service = _patch(monkeypatch, store)
    before = len(store.edges)

    result = service.publish_approved_node("n-faq", require_rag_for_faq=True)

    assert result["embedded_edge_id"] == "e-embedded"
    assert len(store.edges) == before


def test_publish_approved_faq_populates_rag_branch_columns(monkeypatch):
    store = _Store(existing_edge=False, existing_chunks=0)
    service = _patch(monkeypatch, store)

    service.publish_approved_node("n-faq", require_rag_for_faq=True)

    entry = store.rag_entries[0]
    chunk = store.chunks[0]
    assert entry["embedding_model"] == "faq"
    assert chunk["embedding_model"] == "faq"
    for row in (entry, chunk):
        assert row["connected_node_type"] == "faq"
        assert row["connected_node_title"] == "Como comprar?"
        assert row["branch_persona_md"] == "Marca principal."
        assert row["branch_brand_md"] == "Marca principal."
        assert row["branch_product_md"] == "Produto A confirmado."
        assert row["branch_copy_md"]
    assert entry["metadata"]["branch_markdown_columns"]["connected_node_type"] == "faq"
    assert chunk["metadata"]["branch_markdown_columns"]["branch_product_md"] == "Produto A confirmado."


def test_validate_approved_faq_publications_detects_missing_artifacts(monkeypatch):
    service = _patch(monkeypatch, _Store(existing_edge=False, existing_chunks=0))

    result = service.validate_approved_faq_publications(repair=False)

    assert result["ok"] is False
    assert result["checked"] == 1
    assert result["failures"][0]["missing"] == ["faq_embedded_edge", "knowledge_rag_chunks"]


def test_validate_approved_faq_publications_repairs_missing_artifacts(monkeypatch):
    store = _Store(existing_edge=False, existing_chunks=0)
    service = _patch(monkeypatch, store)

    result = service.validate_approved_faq_publications(repair=True)

    assert result["ok"] is True
    assert result["checked"] == 1
    assert result["repaired"] == 1
    assert result["items"][0]["repaired"] is True
    assert store.markdown_rebuilt


def test_validate_approved_faq_publications_repairs_missing_rag_context_columns(monkeypatch):
    store = _Store(existing_edge=True, existing_chunks=1)
    service = _patch(monkeypatch, store)

    def quality(node_id, *, expected_node_type="faq"):
        if not store.rag_entries:
            return {"entry_ids": ["rag-1"], "chunk_count": 1, "missing": ["entry_embedding_model"]}
        return {"entry_ids": ["rag-1"], "chunk_count": 1, "missing": []}

    monkeypatch.setattr(service, "_rag_publication_quality_for_node", quality)

    result = service.validate_approved_faq_publications(repair=True)

    assert result["ok"] is True
    assert result["checked"] == 1
    assert result["repaired"] == 1
    assert result["items"][0]["repaired"] is True
    assert store.rag_entries[0]["embedding_model"] == "faq"


def test_validate_approved_faq_publications_repairs_missing_node(monkeypatch):
    from services import knowledge_lifecycle

    store = _Store(existing_edge=False, existing_chunks=0)
    faq_node = next(node for node in store.nodes if node["id"] == "n-faq")
    store.nodes = [node for node in store.nodes if node["id"] != "n-faq"]
    service = _patch(monkeypatch, store)

    def promote(item_id, *, promote_to_kb=False):
        store.nodes.append(faq_node)
        return {"item": store.get_knowledge_item(item_id), "evidence": {"knowledge_node_id": "n-faq"}}

    monkeypatch.setattr(knowledge_lifecycle, "promote_knowledge_item", promote)

    result = service.validate_approved_faq_publications(repair=True)

    assert result["ok"] is True
    assert result["checked"] == 1
    assert result["repaired"] == 1
    assert result["items"][0]["knowledge_node_id"] == "n-faq"


def test_validate_approved_faq_publications_repairs_node_only_faq(monkeypatch):
    store = _Store(existing_edge=True, existing_chunks=1)
    store.nodes.append(
        store.node(
            "n-node-only-faq",
            "faq",
            "node-only-faq",
            "Como comprar node-only?",
            "Resposta aprovada node-only com detalhes suficientes para virar chunk.",
        )
    )
    store.nodes[-1]["status"] = "approved"
    service = _patch(monkeypatch, store)

    result = service.validate_approved_faq_publications(repair=True)

    node_only = [item for item in result["items"] if item.get("knowledge_node_id") == "n-node-only-faq"]
    assert result["ok"] is True
    assert node_only
    assert node_only[0]["source"] == "knowledge_nodes"
    assert node_only[0]["repaired"] is True

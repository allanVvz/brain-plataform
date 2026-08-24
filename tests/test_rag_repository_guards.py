import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import supabase_client  # noqa: E402


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters = {}
        self.query_limit = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.filters[key] = list(values)
        if key == "rag_entry_id":
            self.client.chunk_batches.append(list(values))
        return self

    def limit(self, value):
        self.query_limit = value
        self.client.limits.append((self.table_name, value))
        return self

    def text_search(self, column, query, options=None):
        self.client.searches.append((self.table_name, column, query, options or {}))
        return self

    def execute(self):
        if self.table_name == "knowledge_rag_entries":
            rows = self.client.entries
            if "id" in self.filters:
                entry_ids = set(self.filters["id"])
                rows = [row for row in rows if row["id"] in entry_ids]
            return SimpleNamespace(data=rows[: self.query_limit])
        if "rag_entry_id" not in self.filters:
            return SimpleNamespace(data=self.client.chunks[: self.query_limit])
        entry_ids = set(self.filters["rag_entry_id"])
        return SimpleNamespace(
            data=[row for row in self.client.chunks if row["rag_entry_id"] in entry_ids]
        )


class _Client:
    def __init__(self, entries, chunks):
        self.entries = entries
        self.chunks = chunks
        self.chunk_batches = []
        self.limits = []
        self.searches = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, _name, _params):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))


def test_active_rag_candidates_are_bounded_before_entry_details(monkeypatch):
    entries = [
        {
            "id": f"entry-{index}",
            "title": f"Opções do grupo {index}",
            "slug": f"grupo-{index}",
            "status": "approved",
            "metadata": {"agent_slug": "vitoria"},
        }
        for index in range(160)
    ]
    chunks = [
        {
            "id": f"chunk-{index}",
            "rag_entry_id": f"entry-{index}",
            "persona_id": "tock",
            "chunk_index": 0,
            "chunk_text": f"Opções de produtos do grupo {index}",
            "chunk_summary": "",
            "metadata": {"agent_slug": "vitoria"},
        }
        for index in range(160)
    ]
    client = _Client(entries, chunks)
    monkeypatch.setattr(supabase_client, "get_client", lambda: client)

    rows = supabase_client.search_active_rag_chunks(
        persona_id="tock", query="quais opções tem", limit=12,
        agent_slug="vitoria",
    )

    assert len(rows) == 12
    assert client.chunk_batches == []
    assert client.searches[0][0:2] == (
        "knowledge_rag_chunks", "search_document",
    )
    assert ("knowledge_rag_chunks", 96) in client.limits
    assert ("knowledge_rag_entries", 96) in client.limits


def test_rag_agent_scope_allows_shared_rows_and_rejects_other_agent():
    assert supabase_client._rag_row_matches_agent({"metadata": {}}, "vitoria")
    assert supabase_client._rag_row_matches_agent(
        {"metadata": {"agent_slug": "vitoria"}}, "vitoria"
    )
    assert not supabase_client._rag_row_matches_agent(
        {"metadata": {"agent_slug": "aurora"}}, "vitoria"
    )


def test_accent_insensitive_rag_prefers_catalog_over_arbitrary_product():
    candidates = supabase_client._accent_insensitive_rag_candidates(
        [
            {
                "id": "product",
                "source_graph_node_id": "faq:product",
                "chunk_text": "Veja opções desta blusa.",
                "metadata": {},
            },
            {
                "id": "catalog",
                "source_graph_node_id": "faq:catalog-groups",
                "chunk_text": "Quais opções vocês têm? Estes são os grupos de produtos.",
                "metadata": {},
            },
        ],
        "quais opcoes tem",
        limit=2,
    )

    assert candidates[0]["source_node_id"] == "faq:catalog-groups"
    assert candidates[0]["adapter_lexical_score"] == 1.0


def test_graph_rag_recovers_group_overview_for_unaccented_broad_query(monkeypatch):
    client = _Client(
        [],
        [
            {
                "id": "product",
                "rag_entry_id": "entry-product",
                "persona_id": "tock",
                "chunk_text": "Veja opções desta blusa.",
                "chunk_summary": "",
                "metadata": {},
                "source_graph_node_id": "faq:product",
                "branch_anchor_node_id": "audience:retail",
                "chunk_kind": "faq",
                "projection_status": "ready",
            },
            {
                "id": "catalog",
                "rag_entry_id": "entry-catalog",
                "persona_id": "tock",
                "chunk_text": "Quais opções vocês têm? Estes são os grupos de produtos.",
                "chunk_summary": "",
                "metadata": {},
                "source_graph_node_id": "faq:catalog-groups",
                "branch_anchor_node_id": "audience:retail",
                "chunk_kind": "faq",
                "projection_status": "ready",
            },
        ],
    )
    monkeypatch.setattr(supabase_client, "get_client", lambda: client)

    rows = supabase_client.search_graph_rag_v3(
        persona_id="tock",
        publication_id="publication",
        branch_node_id="audience:retail",
        query="quais opcoes tem",
        query_embedding=None,
        agent_slug="vitoria",
        limit=12,
    )

    assert rows[0]["source_node_id"] == "faq:catalog-groups"
    assert client.searches[0][2] == "opcoes OR quais OR tem"
    assert ("knowledge_rag_chunks", 64) in client.limits

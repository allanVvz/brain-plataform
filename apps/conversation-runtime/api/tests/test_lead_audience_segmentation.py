"""Lead -> audience segmentation from graph taxonomy edges (Bug 5).

`audience_has_product_group` (audience -> product_group) and
`offers_product` (audience -> product) were declared in
knowledge_taxonomy.PRIMARY_CHAIN as validation rules only -- nothing read
them live before this. graph_agent_runtime_v3.resolve_audience_node_ids /
sync_lead_audience_memberships wire them up: after a v3 turn commits, the
turn's active branch/product focus is resolved against these edges and the
lead becomes a 'shared' member of any audience found.

No real Tock Fatal content declares these edges yet (the persona's
interest-based audience nodes -- audience:tock-ctx-conforto,
audience:tock-ctx-plus-size, audience:tock-ctx-preco-oportunidade,
audience:tock-ctx-tendencia -- exist and are wired into the site/campaign
tree, but none of them has an audience_has_product_group/offers_product
edge to any product yet; that content authoring is Sofia/the operator's
follow-up, not something to fabricate here). So every test below uses a
synthetic fixture document instead of the real bundle.
"""
from __future__ import annotations

from typing import Any

import pytest

from schemas.conversation import AgentResponse, ConversationContext, ConversationDecision, ConversationRoute
from services import conversation_runtime, graph_agent_runtime_v3


def _fixture_document() -> dict[str, Any]:
    """Persona -> product_group -> product spine, plus two audiences:

    - audience:test-price-sensitive --audience_has_product_group--> product_group:test-group
      product_group:test-group --product_group_has_product--> product:test-blusa
      (the indirect, "resolve the product's group upward" case)
    - audience:test-direct --offers_product--> product:test-blusa-direct
      (the direct audience->product case)
    """
    return {
        "node_by_id": {
            "product:test-blusa": {
                "id": "product:test-blusa", "node_type": "product",
                "slug": "test-blusa", "title": "Blusa Teste",
            },
            "product:test-blusa-direct": {
                "id": "product:test-blusa-direct", "node_type": "product",
                "slug": "test-blusa-direct", "title": "Blusa Direta",
            },
            "product_group:test-group": {
                "id": "product_group:test-group", "node_type": "product_group",
                "slug": "test-group", "title": "Grupo Teste",
            },
            "audience:test-price-sensitive": {
                "id": "audience:test-price-sensitive", "node_type": "audience",
                "slug": "test-price-sensitive", "title": "Sensivel a preco",
                "summary": "Audiencia sintetica de teste.",
            },
            "audience:test-direct": {
                "id": "audience:test-direct", "node_type": "audience",
                "slug": "test-direct", "title": "Audiencia direta",
            },
        },
        "edges": [
            {
                "source": "product_group:test-group", "target": "product:test-blusa",
                "relation_type": "product_group_has_product",
            },
            {
                "source": "audience:test-price-sensitive", "target": "product_group:test-group",
                "relation_type": "audience_has_product_group",
            },
            {
                "source": "audience:test-direct", "target": "product:test-blusa-direct",
                "relation_type": "offers_product",
            },
        ],
    }


# ── resolve_audience_node_ids: pure edge-walking, no I/O ─────────────────

def test_resolves_audience_via_product_group_upward():
    document = _fixture_document()
    assert graph_agent_runtime_v3.resolve_audience_node_ids(
        document, ["product:test-blusa"],
    ) == ["audience:test-price-sensitive"]


def test_resolves_audience_via_direct_offers_product_edge():
    document = _fixture_document()
    assert graph_agent_runtime_v3.resolve_audience_node_ids(
        document, ["product:test-blusa-direct"],
    ) == ["audience:test-direct"]


def test_resolves_audience_from_product_group_node_directly():
    document = _fixture_document()
    assert graph_agent_runtime_v3.resolve_audience_node_ids(
        document, ["product_group:test-group"],
    ) == ["audience:test-price-sensitive"]


def test_unknown_or_unrelated_node_ids_resolve_to_nothing():
    document = _fixture_document()
    assert graph_agent_runtime_v3.resolve_audience_node_ids(
        document, ["node-not-in-document", "audience:test-direct"],
    ) == []


# ── sync_lead_audience_memberships: DB-facing, exercised against fakes ───

class _FakeAudienceStore:
    """Stands in for the `audiences` / `lead_audience_memberships` tables.

    Mirrors the real contract exactly where it matters for this feature:
    `create_audience` is keyed by (persona_id, slug) like the real unique
    constraint, and a membership row already present for (lead_id,
    audience_id) is never overwritten -- so a pre-existing 'primary' row
    (manual/import/CRM) stays 'primary' even when the graph-driven sync
    runs against the same lead+audience pair.
    """

    def __init__(self) -> None:
        self.audiences: dict[tuple[str, str], dict[str, Any]] = {}
        self.memberships: dict[tuple[int, str], dict[str, Any]] = {}
        self.ensure_calls: list[tuple[int, str]] = []
        self._next_id = 1

    def get_audience_by_slug(self, persona_id: str, slug: str) -> dict[str, Any] | None:
        return self.audiences.get((persona_id, slug))

    def create_audience(self, data: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": f"aud-{self._next_id}",
            "persona_id": data["persona_id"],
            "slug": data["slug"],
            "name": data.get("name"),
            "description": data.get("description"),
            "source_type": data.get("source_type"),
        }
        self._next_id += 1
        self.audiences[(data["persona_id"], data["slug"])] = row
        return row

    def ensure_shared_lead_membership(self, lead_id: int, audience_id: str) -> dict[str, Any]:
        self.ensure_calls.append((lead_id, audience_id))
        key = (lead_id, audience_id)
        existing = self.memberships.get(key)
        if existing:
            return existing
        row = {"lead_id": lead_id, "audience_id": audience_id, "membership_type": "shared"}
        self.memberships[key] = row
        return row


@pytest.fixture()
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeAudienceStore:
    store = _FakeAudienceStore()
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_audience_by_slug", store.get_audience_by_slug)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "create_audience", store.create_audience)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "ensure_shared_lead_membership", store.ensure_shared_lead_membership,
    )
    return store


def test_turn_resolving_to_a_connected_product_creates_membership(fake_store: _FakeAudienceStore):
    document = _fixture_document()
    joined = graph_agent_runtime_v3.sync_lead_audience_memberships(
        persona_id="persona-1", lead_id=42, document=document,
        candidate_node_ids=["product:test-blusa"],
    )
    assert joined == ["aud-1"]
    assert fake_store.memberships[(42, "aud-1")]["membership_type"] == "shared"
    created = fake_store.audiences[("persona-1", "test-price-sensitive")]
    assert created["source_type"] == "graph"


def test_running_twice_for_the_same_lead_does_not_duplicate(fake_store: _FakeAudienceStore):
    document = _fixture_document()
    kwargs = dict(
        persona_id="persona-1", lead_id=42, document=document,
        candidate_node_ids=["product:test-blusa"],
    )
    first = graph_agent_runtime_v3.sync_lead_audience_memberships(**kwargs)
    second = graph_agent_runtime_v3.sync_lead_audience_memberships(**kwargs)
    assert first == second == ["aud-1"]
    # One audience row (matched by slug on the second pass, not recreated)...
    assert len(fake_store.audiences) == 1
    # ...and one membership row, not two.
    assert len(fake_store.memberships) == 1
    assert fake_store.ensure_calls == [(42, "aud-1"), (42, "aud-1")]


def test_never_downgrades_an_existing_primary_membership(fake_store: _FakeAudienceStore):
    document = _fixture_document()
    # Simulate a lead already linked to this audience manually/via import,
    # before any graph-driven turn ever touched it.
    audience_row = fake_store.create_audience({
        "persona_id": "persona-1", "slug": "test-price-sensitive", "name": "x", "source_type": "graph",
    })
    fake_store.memberships[(7, audience_row["id"])] = {
        "lead_id": 7, "audience_id": audience_row["id"], "membership_type": "primary",
    }
    graph_agent_runtime_v3.sync_lead_audience_memberships(
        persona_id="persona-1", lead_id=7, document=document,
        candidate_node_ids=["product:test-blusa"],
    )
    assert fake_store.memberships[(7, audience_row["id"])]["membership_type"] == "primary"


def test_no_candidate_nodes_resolve_to_no_membership(fake_store: _FakeAudienceStore):
    document = _fixture_document()
    joined = graph_agent_runtime_v3.sync_lead_audience_memberships(
        persona_id="persona-1", lead_id=42, document=document,
        candidate_node_ids=["node-with-no-audience-edge"],
    )
    assert joined == []
    assert not fake_store.audiences
    assert not fake_store.memberships


def test_sync_step_never_raises_when_one_audience_lookup_fails(monkeypatch: pytest.MonkeyPatch):
    """A failure resolving/joining one audience must not lose the others and
    must never bubble out of sync_lead_audience_memberships itself."""
    document = _fixture_document()

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_audience_by_slug", _boom)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "create_audience", _boom)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "ensure_shared_lead_membership", _boom)

    joined = graph_agent_runtime_v3.sync_lead_audience_memberships(
        persona_id="persona-1", lead_id=42, document=document,
        candidate_node_ids=["product:test-blusa"],
    )
    assert joined == []


# ── commit(): the sync step must never affect the turn's own success ────

def _minimal_v3_context(*, publication_id: str, active_branch_node_id: str) -> ConversationContext:
    return ConversationContext(
        persona_slug="tock-fatal-test",
        agent_slug="tock-fatal-agent",
        graph_version=1,
        graph_checksum="checksum-1",
        messages=[{"role": "user", "content": "oi", "message_id": "in-1"}],
        cart={},
        rag_nodes=[],
        rag_paths=[],
        publication_id=publication_id,
        runtime_version=graph_agent_runtime_v3.RUNTIME_VERSION,
        journey_id="journey-1",
        active_branch_node_id=active_branch_node_id,
    )


def _minimal_v3_response(*, active_branch_node_id: str) -> AgentResponse:
    return AgentResponse(
        reply_text=None,
        role=ConversationRoute.SDR,
        cart_state={
            "active_branch_node_id": active_branch_node_id,
            "active_branch_node_ids": [active_branch_node_id],
            "facts": {},
            "commercial_note_projection": {"version": 1},
        },
        proof={"journey_action": "none"},
        handoff_required=False,
    )


def test_commit_succeeds_even_when_audience_sync_raises(monkeypatch: pytest.MonkeyPatch):
    """The wiring step sits right after the turn's own commit succeeds.
    A failure inside it (mocked here as sync_lead_audience_memberships
    raising) must be logged and swallowed -- never turn a successful commit
    into a failed one, and never touch the reply already prepared."""
    document = _fixture_document()
    lead_row = {
        "id": 1001, "persona_id": "persona-1", "channel_binding_id": "binding-1",
        "metadata": {},
    }
    binding_row = {
        "id": "binding-1", "persona_id": "persona-1", "active": True,
        "metadata": {}, "whatsapp_phone_number_id": None,
    }
    persona_row = {"id": "persona-1", "slug": "tock-fatal-test"}
    publication_row = {"id": "pub-1", "document_json": document}

    monkeypatch.setattr(conversation_runtime.supabase_client, "get_lead_by_ref", lambda lead_ref: lead_row)
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_workflow_binding_by_id", lambda binding_id: binding_row,
    )
    monkeypatch.setattr(conversation_runtime.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        conversation_runtime.supabase_client, "get_graph_publication_by_id", lambda pub_id: publication_row,
    )
    monkeypatch.setattr(conversation_runtime.supabase_client, "insert_agent_log", lambda payload: None)
    monkeypatch.setattr(conversation_runtime.supabase_client, "insert_event", lambda payload, source=None: None)
    monkeypatch.setattr(
        conversation_runtime, "_commit_graph_turn_and_outbox_or_raise",
        lambda **_kwargs: {"graph_turn": {"id": "turn-1"}},
    )

    def _raise_sync(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("audience sync exploded")

    monkeypatch.setattr(graph_agent_runtime_v3, "sync_lead_audience_memberships", _raise_sync)

    result = conversation_runtime.commit(
        lead_ref=1001,
        context=_minimal_v3_context(publication_id="pub-1", active_branch_node_id="product:test-blusa"),
        decision=ConversationDecision(
            classifier="graph_agent_runtime_v3", intent="collect_graph_fields",
            route=ConversationRoute.SDR, confidence=1, lead_stage="engajado",
        ),
        response=_minimal_v3_response(active_branch_node_id="product:test-blusa"),
        correlation_id="correlation-1",
        phone_number_id=None,
        channel_binding_id="binding-1",
    )

    assert result["ok"] is True
    assert result["reply_text"] is None
    assert result["graph_turn"] == {"id": "turn-1"}

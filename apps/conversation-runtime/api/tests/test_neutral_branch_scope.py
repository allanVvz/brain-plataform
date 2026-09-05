"""A customer who has not chosen a branch is told nothing brand-specific.

Tock Fatal publishes one catalogue under two brands at two prices:
`brand:tock-fatal-varejo` and `brand:tock-fatal-atacado`, anchored on
`audience:tock-retail` and `audience:tock-reseller`. On 2026-09-05 lead 208
arrived with no declared profile, `active_branch_node_id` stayed null, and the
turn retrieved the *reseller* package: the agent offered the Conjunto canelado
at "R$ 69,93 a peca a partir de 3 pecas" and cited
`faq:tock-conjuntos-conjunto-canelado-atacado-duvida-indireta-proxima-acao`.
Retail for the same item is R$ 99,90. The model was faithful to what it was
given; retrieval gave it the wrong brand.

These tests run against the real published bundle, not a fixture, because what
is under test is whether the actual Tock graph isolates. They fail if a null
branch ever means "both brands visible" again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_agent_runtime_v3  # noqa: E402
from services import graph_compiler_v3  # noqa: E402

BUNDLE_PATH = (
    REPO_ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v16-voice-reachable.json"
)

RETAIL = "audience:tock-retail"
RESELLER = "audience:tock-reseller"

# The nodes that carry the wholesale offer the branchless lead was quoted.
RESELLER_ONLY = [
    "brand:tock-fatal-atacado",
    "rule:tock-desconto-atacado-30",
    "faq:tock-reseller-stage",
    "offer:tock-conjuntos-conjunto-canelado-atacado",
    "faq:tock-conjuntos-conjunto-canelado-atacado-duvida-indireta-proxima-acao",
]
# Null is null: retail is not the safe default either.
RETAIL_ONLY = [
    "brand:tock-fatal-varejo",
    "faq:tock-retail-need",
    "offer:tock-conjuntos-conjunto-canelado-varejo",
]
# What has to survive so the agent can still talk and still ask the question
# that ends the ambiguity.
NEUTRAL_REQUIRED = [
    "faq:tock-purchase-profile",
    "campaign:tock-whatsapp-qualification",
    "product_group:tock-conjuntos",
    "product:tock-conjuntos-conjunto-canelado",
]


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def document(bundle) -> dict:
    """Compile with the runtime's own compiler: that is what production runs."""
    return graph_compiler_v3.compile_graph(
        persona={"id": bundle["persona"]["id"], "slug": bundle["persona"]["slug"]},
        node_rows=[
            {
                "id": node["id"],
                "persona_id": bundle["persona"]["id"],
                "node_type": node["node_type"],
                "slug": node.get("slug"),
                "title": node.get("title"),
                "summary": node.get("summary"),
                "tags": node.get("tags") or [],
                "status": node.get("status"),
                "metadata": {"graph_json_node_id": node["id"], **(node.get("data") or {})},
            }
            for node in bundle["nodes"]
        ],
        edge_rows=[
            {
                "id": edge["id"],
                "persona_id": bundle["persona"]["id"],
                "source_node_id": edge["source"],
                "target_node_id": edge["target"],
                "relation_type": edge["relation_type"],
                "weight": edge.get("weight"),
                "metadata": edge.get("metadata") or {},
            }
            for edge in bundle["edges"]
        ],
        embedding_profile=bundle["metadata"]["embedding_profile"],
    )


@pytest.fixture(scope="module")
def neutral(document) -> set[str]:
    return graph_agent_runtime_v3.neutral_scope_node_ids(document)


@pytest.mark.unit
def test_the_bundle_still_carries_the_two_competing_brands(document):
    """Guard the guard: without both branches these tests prove nothing."""
    memberships = document["branch_memberships"]
    assert set(memberships) == {RETAIL, RESELLER}
    for node_id in [*RESELLER_ONLY, *RETAIL_ONLY, *NEUTRAL_REQUIRED]:
        assert node_id in document["node_by_id"], node_id


@pytest.mark.unit
def test_a_null_branch_never_reaches_a_reseller_only_node(neutral, document):
    """The 2026-09-05 leak, node by node."""
    for node_id in RESELLER_ONLY:
        assert node_id in document["branch_memberships"][RESELLER], node_id
        assert node_id not in document["branch_memberships"][RETAIL], node_id
        assert node_id not in neutral, (
            f"{node_id} is wholesale-only and reachable with no branch chosen; "
            "this is how R$ 69,93 was quoted to a retail customer"
        )


@pytest.mark.unit
def test_a_null_branch_is_not_retail_by_default_either(neutral, document):
    for node_id in RETAIL_ONLY:
        assert node_id in document["branch_memberships"][RETAIL], node_id
        assert node_id not in document["branch_memberships"][RESELLER], node_id
        assert node_id not in neutral, (
            f"{node_id} is retail-only and reachable with no branch chosen; "
            "a null branch means no brand, not the cheaper brand"
        )


@pytest.mark.unit
def test_no_node_exclusive_to_one_branch_survives_a_null_branch(neutral, document):
    """The general rule, not the five nodes we happen to remember.

    Fails the moment anyone widens the branchless scope back to "everything
    published", for any persona-shaped graph with competing branches.
    """
    memberships = document["branch_memberships"]
    exclusive = {
        node_id
        for anchor, members in memberships.items()
        for node_id in members
        if any(node_id not in other for name, other in memberships.items() if name != anchor)
    }
    assert exclusive, "the bundle no longer isolates anything between branches"
    assert not (neutral & exclusive)


@pytest.mark.unit
def test_the_agent_keeps_enough_neutral_content_to_speak(neutral, document):
    """Withholding both brands must not make the agent mute.

    111 nodes with the v16 bundle: persona, both campaigns, the seven product
    groups, the shared catalogue and the navigation FAQs. The floor is a
    tripwire -- if a graph change guts the neutral scope, the agent stops
    answering an unqualified lead entirely, which is worse in operation than
    the leak.
    """
    assert len(neutral) >= 50, sorted(neutral)
    for node_id in NEUTRAL_REQUIRED:
        assert node_id in neutral, node_id
    types = {document["node_by_id"][node_id]["node_type"] for node_id in neutral}
    assert {"faq", "product_group", "campaign"} <= types
    assert "offer" not in types, "a price is always brand-scoped"
    assert "brand" not in types


@pytest.mark.unit
def test_neutral_scope_falls_back_to_the_common_contract(document):
    """A publication compiled before memberships existed still cannot leak."""
    legacy = {
        "common_contract": {"closure_node_ids": ["persona:tock-fatal", "faq:tock-purchase-profile"]},
    }
    assert graph_agent_runtime_v3.neutral_scope_node_ids(legacy) == {
        "persona:tock-fatal", "faq:tock-purchase-profile",
    }


@pytest.mark.unit
def test_contract_narrowed_to_the_neutral_scope_keeps_its_identity(document):
    """The checker still validates the same contract; only reach shrinks."""
    contract = document["branch_contracts"][RESELLER]
    neutral = graph_agent_runtime_v3.neutral_scope_node_ids(document)
    scoped = graph_agent_runtime_v3._contract_scoped_to_neutral(contract, neutral)

    assert scoped["branch_path_checksum"] == contract["branch_path_checksum"]
    assert scoped["fields"] == contract["fields"]
    assert set(scoped["closure_node_ids"]) <= neutral
    assert "rule:tock-desconto-atacado-30" in contract["closure_node_ids"]
    assert "rule:tock-desconto-atacado-30" not in scoped["closure_node_ids"]
    assert scoped["brand_scope_withheld"] is True


def _chunk(node_id: str, text: str) -> dict:
    return {
        "chunk_id": f"chunk:{node_id}",
        "source_node_id": node_id,
        "chunk_kind": "content",
        "chunk_text": text,
        "hybrid_score": 0.9,
    }


@pytest.fixture
def branchless_turn(monkeypatch, document):
    """A real build_context() turn for a lead with no declared profile.

    Retrieval is stubbed to return exactly what production returned on
    2026-09-05: wholesale chunks, because the fallback anchor sorts first.
    """
    publication = {
        "id": "pub-1", "version": 13, "status": "active",
        "checksum": "sha256:ba91e7b1c31f6eadf8ea6decd6fa57f58dddd1b1c58b64e0b7317dea8d3aa66d",
        "document_json": document,
    }
    served = [
        _chunk("offer:tock-conjuntos-conjunto-canelado-atacado", "R$ 69,93 a peca a partir de 3 pecas"),
        _chunk("rule:tock-desconto-atacado-30", "30% de desconto no atacado"),
        _chunk("brand:tock-fatal-atacado", "Tock Fatal Atacado"),
        _chunk("faq:tock-purchase-profile", "Voce compra para uso proprio ou para revender?"),
        _chunk("product_group:tock-conjuntos", "Conjuntos"),
    ]
    client = graph_agent_runtime_v3.supabase_client
    monkeypatch.setattr(client, "get_persona", lambda slug: {"id": "persona-1", "slug": slug, "config": {}})
    monkeypatch.setattr(client, "get_lead_by_ref", lambda ref: {"id": "lead-1", "persona_id": "persona-1", "metadata": {}})
    monkeypatch.setattr(
        client, "get_graph_turn_context_batch_v4",
        lambda **kwargs: {"publication": publication, "messages": [], "branches": []},
    )
    monkeypatch.setattr(client, "get_messages", lambda *a, **k: [])
    monkeypatch.setattr(client, "get_conversation_ledger", lambda *a, **k: None)
    monkeypatch.setattr(client, "get_current_conversation_journey", lambda *a, **k: None)
    monkeypatch.setattr(client, "get_latest_conversation_journey", lambda *a, **k: {})
    monkeypatch.setattr(client, "rank_graph_branches_v3", lambda **kwargs: [])
    monkeypatch.setattr(client, "search_graph_rag_v3", lambda **kwargs: list(served))
    monkeypatch.setattr(client, "search_graph_faq_v3", lambda **kwargs: [])
    monkeypatch.setattr(
        client, "get_graph_branch_package_v3",
        lambda **kwargs: {"chunks": list(served)},
    )
    monkeypatch.setattr(graph_agent_runtime_v3.graph_compiler_v3, "query_embeddings", lambda texts: [[0.0] * 8 for _ in texts])
    return graph_agent_runtime_v3.build_context(
        persona_slug="tock-fatal", lead_ref=208,
        message="oi, tudo bem?", message_id="msg-1",
    )


@pytest.mark.unit
def test_branchless_turn_drops_the_wholesale_package_it_was_served(branchless_turn):
    """The end of the 2026-09-05 leak, through the real code path.

    Retrieval still runs against a fallback anchor -- `branch_anchors` sorts
    `audience:tock-reseller` first, which is why wholesale was what came back
    -- but nothing exclusive to it survives into the model's package.
    """
    context = branchless_turn
    assert context.active_branch_node_id is None
    card_ids = {card.id for card in context.context_cards}
    for node_id in RESELLER_ONLY[:3]:
        assert node_id not in card_ids, f"{node_id} reached the model with no branch chosen"
    assert "69,93" not in "\n".join(card.rendered_content for card in context.context_cards)
    assert card_ids  # and the agent is not mute
    assert "faq:tock-purchase-profile" in card_ids


@pytest.mark.unit
def test_branchless_turn_scopes_evidence_expansion_to_the_neutral_set(branchless_turn, neutral):
    """`branch_node_ids` is the scope a cited node may be expanded from.

    Left at the fallback branch's closure it would re-admit the wholesale
    offer after the model call, one card at a time.
    """
    context = branchless_turn
    assert set(context.branch_node_ids) <= neutral
    assert "rule:tock-desconto-atacado-30" not in set(context.branch_node_ids)
    assert context.retrieval_trace["brand_scope_withheld"] is True
    assert context.retrieval_trace["neutral_scope_node_count"] == len(neutral)

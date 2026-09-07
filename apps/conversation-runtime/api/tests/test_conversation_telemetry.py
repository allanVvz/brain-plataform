from schemas.conversation import (
    AgentResponse,
    ConversationContext,
    ConversationDecision,
    ConversationProposal,
    ConversationRoute,
)
from services import conversation_runtime


def _context() -> ConversationContext:
    return ConversationContext(
        persona_slug="persona",
        agent_slug="sdr",
        graph_version=7,
        graph_checksum="sha256:published",
        messages=[],
        cart={},
        rag_nodes=[{"id": "node-retrieved"}],
        rag_paths=[],
        rag_chunks=[{"chunk_id": "chunk-retrieved"}],
        publication_id="publication-7",
        retrieval_trace={
            "source_node_ids": ["node-retrieved", "node-not-cited"],
            "chunk_ids": ["chunk-retrieved", "chunk-not-cited"],
        },
    )


def _decision() -> ConversationDecision:
    return ConversationDecision(
        intent="answer",
        route=ConversationRoute.SDR,
        confidence=1,
        lead_stage="engajado",
        evidence_node_ids=["node-retrieved"],
    )


def test_turn_evidence_projection_keeps_categories_distinct():
    response = AgentResponse(
        reply_text="Resposta",
        role=ConversationRoute.SDR,
        cart_state={},
        proposal=ConversationProposal(
            cited_node_ids=["node-retrieved"],
            cited_chunk_ids=["chunk-retrieved"],
        ),
        proof={"valid": True, "delivery_authorized": True},
    )

    projection = conversation_runtime._turn_evidence_projection(
        context=_context(), response=response, decision=_decision(),
        graph_turn={"proof_id": "proof-real"},
    )

    assert projection["proof_id"] == "proof-real"
    assert projection["decision_id"] is None
    assert projection["retrieved"] == {
        "node_ids": ["node-retrieved", "node-not-cited"],
        "chunk_ids": ["chunk-retrieved", "chunk-not-cited"],
    }
    assert projection["cited"] == {
        "node_ids": ["node-retrieved"],
        "chunk_ids": ["chunk-retrieved"],
    }
    assert projection["proof_authorized"]["node_ids"] == ["node-retrieved"]


def test_turn_evidence_projection_never_invents_ids_or_authorization():
    response = AgentResponse(
        reply_text=None,
        role=ConversationRoute.HUMAN,
        cart_state={},
        proposal=ConversationProposal(cited_node_ids=["node-retrieved"]),
        proof={"valid": False, "delivery_authorized": False},
    )

    projection = conversation_runtime._turn_evidence_projection(
        context=_context(), response=response, decision=_decision(), graph_turn=None,
    )

    assert projection["proof_id"] is None
    assert projection["decision_id"] is None
    assert projection["cited"]["node_ids"] == ["node-retrieved"]
    assert projection["proof_authorized"] == {
        "delivery": False,
        "node_ids": [],
        "chunk_ids": [],
        "decisive_node_ids": [],
    }


def test_validator_origin_requires_canonical_lead_markers():
    spoofed = {
        "lead_id": "customer-1",
        "metadata": {"validation": {"is_validation": True, "session_id": "session-1"}},
    }
    canonical = {
        "lead_id": "validator_session-1",
        "metadata": {"validation": {"is_validation": True, "session_id": "session-1"}},
    }

    assert conversation_runtime._validation_evidence_origin(spoofed) == (
        "conversation", None,
    )
    assert conversation_runtime._validation_evidence_origin(canonical) == (
        "wa_validator", "session-1",
    )

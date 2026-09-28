from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from schemas.conversation import (
    AgentResponse, ConversationContext, ConversationDecision,
    ConversationReplyV1, ResolvedUnderstandingV1, TurnUnderstandingV1,
)
from services import conversation_runtime, graph_agent_runtime_v3, graph_proof_checker_v3
from repositories import runtime as repository


NAME_FIELD = {
    "key": "customer_identity", "owner_node_id": "persona:fixture",
    "scope": "persona", "required": False,
    "collection_mode": "ask_once_optional",
    "question_node_id": "faq:identity",
    "validation": {"semantic_type": "human_full_name", "min_tokens": 1, "max_tokens": 3},
}


def test_tock_source_bundle_publishes_optional_name_contract():
    root = Path(__file__).resolve().parents[4]
    bundle = json.loads((root / "data/graph_bundles/tock-fatal/unified-message-queue-v38.json")
                        .read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in bundle["nodes"]}
    persona = nodes["persona:tock-fatal"]
    field = next(item for item in persona["data"]["qualification"]["fields"]
                 if (item.get("validation") or {}).get("semantic_type") == "human_full_name")
    question = nodes[field["question_node_id"]]
    assert field["owner_node_id"] == persona["id"]
    assert field["collection_mode"] == "ask_once_optional"
    assert field["depends_on"] == ["purchase_profile"]
    assert question["data"]["field_key"] == field["key"]
    assert question["data"]["question"] == "Como você prefere que eu te chame?"


def _context(messages=None, cart=None) -> ConversationContext:
    return ConversationContext(
        persona_slug="fixture", agent_slug="agent", agent_role="sdr",
        execution_strategy="interpret_then_respond", graph_version=1,
        graph_checksum="sha256:fixture", publication_id="publication:fixture",
        runtime_version=graph_agent_runtime_v3.RUNTIME_VERSION,
        messages=messages or [{"role": "user", "message_id": "in:1", "content": "sim"}],
        cart=cart or {"facts": {}, "facts_by_key": {}, "asked_question_node_ids": []},
        rag_nodes=[], rag_paths=[], graph_contract={"fields": [NAME_FIELD]},
    )


def test_crm_name_is_provisional_and_uses_published_validation():
    contract = {"fields": [NAME_FIELD]}
    result = graph_agent_runtime_v3._profile_name_reference(
        lead={"nome": "Ana"}, contract=contract, facts={},
        asked_question_node_ids=[], journey_sequence=1,
    )
    assert result["candidate"] == "Ana"
    assert result["state"] == "confirm_once"
    assert result["field_key"] == "customer_identity"
    assert graph_agent_runtime_v3._profile_name_reference(
        lead={"nome": "x9@@"}, contract=contract, facts={},
        asked_question_node_ids=[], journey_sequence=1,
    ) is None
    assert graph_agent_runtime_v3._profile_name_reference(
        lead={"nome": ""}, contract=contract, facts={},
        asked_question_node_ids=[], journey_sequence=1,
    ) is None
    assert graph_agent_runtime_v3._profile_name_reference(
        lead={"nome": "Ana"}, contract=contract, facts={},
        asked_question_node_ids=[], journey_sequence=3,
    )["state"] == "reference"


def test_confirmed_or_declined_ledger_fact_beats_crm_name():
    for status in ("known", "declined"):
        result = graph_agent_runtime_v3._profile_name_reference(
            lead={"nome": "Ana"}, contract={"fields": [NAME_FIELD]},
            facts={"customer_identity": {
                "status": status, "value": "Beatriz" if status == "known" else None,
                "owner_node_id": "persona:fixture",
            }}, asked_question_node_ids=[], journey_sequence=1,
        )
        assert result is None


def test_optional_name_waits_for_published_dependency():
    selector = {
        "key": "purchase_profile", "owner_node_id": "audience:fixture",
        "required": True, "question_node_id": "faq:profile",
    }
    name = {**NAME_FIELD, "depends_on": ["purchase_profile"]}
    contract = {"fields": [selector, name]}
    assert [field["key"] for field in graph_proof_checker_v3.askable_pending_fields(
        contract, {},
    )] == ["purchase_profile"]
    assert [field["key"] for field in graph_proof_checker_v3.askable_pending_fields(
        contract, {"purchase_profile": {
            "status": "known", "value": "retail", "owner_node_id": "audience:fixture",
        }},
    )] == ["customer_identity"]


def test_affirmation_reads_exact_candidate_from_last_outbound(monkeypatch):
    context = _context(messages=[
        {"role": "assistant", "message_id": "out:1", "content": "Posso te chamar de Ana?",
         "metadata": {"profile_name_candidate": {
             "field_key": "customer_identity", "owner_node_id": "persona:fixture",
             "candidate": "Ana",
         }}},
        {"role": "user", "message_id": "in:1", "content": "sim"},
    ])
    context = context.model_copy(update={
        "retrieval_trace": {"profile_name": {"candidate": "Beatriz"}},
    })
    monkeypatch.setattr(graph_agent_runtime_v3, "_context_scoped_to_understanding_branch",
                        lambda value, _branch: value)
    monkeypatch.setattr(graph_agent_runtime_v3, "_resolved_commercial_interests",
                        lambda **_kwargs: [])
    monkeypatch.setattr(graph_agent_runtime_v3, "decide", lambda *_args, **_kwargs: (
        ConversationDecision(intent="collect_graph_fields", route="SDR", confidence=1,
                             lead_stage="engajado"),
        AgentResponse(reply_text=None, role="SDR", cart_state=context.cart,
                      proof={"valid": True, "delivery_authorized": True,
                             "accepted_facts": []}),
    ))
    understanding = TurnUnderstandingV1(confirmation={
        "state": "affirm", "target_ref": "out:1", "evidence_span": "sim",
    })
    resolved = graph_agent_runtime_v3.resolve_understanding(context, understanding)
    fact = resolved.resolution_proof["accepted_facts"][0]
    assert fact["value"] == "Ana"
    assert fact["source_message_id"] == "in:1"
    assert fact["metadata"]["confirmed_candidate_message_id"] == "out:1"
    assert resolved.prospective_state["facts"]["customer_identity"]["status"] == "known"


def test_qualification_question_requires_valid_field_and_kind(monkeypatch):
    context = _context()
    resolved = ResolvedUnderstandingV1(
        understanding=TurnUnderstandingV1(), context=context,
        prospective_state={}, eligible_fields=[NAME_FIELD],
        conversation_brief={"profile_name": {
            "state": "confirm_once", "candidate": "Ana",
            "field_key": "customer_identity",
        }}, resolution_proof={"valid": True, "accepted_facts": []},
    )
    monkeypatch.setattr(graph_agent_runtime_v3, "decide", lambda *_args, **_kwargs: (
        ConversationDecision(intent="collect_graph_fields", route="SDR", confidence=1,
                             lead_stage="engajado"),
        AgentResponse(reply_text="Posso te chamar de Ana?", role="SDR", cart_state={},
                      proof={"valid": True, "delivery_authorized": True,
                             "question_kind": "qualification"}),
    ))
    def decide(reply):
        return conversation_runtime.decide_agentic(
            context, resolved_understanding=resolved, conversation_reply=reply,
        )
    with pytest.raises(RuntimeError, match="question_kind_required"):
        decide(ConversationReplyV1(reply="Qual é seu nome?"))
    with pytest.raises(RuntimeError, match="field_not_eligible"):
        decide(ConversationReplyV1(reply="Qual é seu nome?", question_kind="qualification",
                                   asked_field_key="wrong"))
    with pytest.raises(RuntimeError, match="must_quote_candidate"):
        decide(ConversationReplyV1(reply="Qual é seu nome?", question_kind="qualification",
                                   asked_field_key="customer_identity"))
    _, response = decide(ConversationReplyV1(reply="Posso te chamar de Ana?",
                                               question_kind="qualification",
                                               asked_field_key="customer_identity"))
    assert response.proof["question_kind"] == "qualification"


def test_crm_name_write_is_compare_and_swap(monkeypatch):
    class Query:
        def __init__(self, current):
            self.current = current
            self.expected = None
            self.updated = None
        def update(self, value):
            self.updated = value["nome"]
            return self
        def eq(self, key, value):
            if key == "nome":
                self.expected = value
            return self
        def is_(self, key, value):
            if key == "nome" and value == "null":
                self.expected = None
            return self
        def select(self, _value):
            return self
        def execute(self):
            return SimpleNamespace(data=[{"id": 7}] if self.current == self.expected else [])
    query = Query("Edited by operator")
    monkeypatch.setattr(repository, "get_client", lambda: SimpleNamespace(table=lambda _name: query))
    assert repository.update_lead_name_if_unchanged(
        7, expected_name="Ana", new_name="Beatriz",
    ) is False
    assert query.updated == "Beatriz"
    query.current = "Ana"
    assert repository.update_lead_name_if_unchanged(
        7, expected_name="Ana", new_name="Beatriz",
    ) is True

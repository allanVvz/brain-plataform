from __future__ import annotations

import pytest

from schemas.conversation import AgentResponse, ConversationContext, ConversationDecision, ConversationProposal, ConversationRoute
from services import graph_agent_runtime_v3 as runtime, reply_metadata

FIELDS = [{"key": "purpose", "question_node_id": "faq:purpose", "required": True},
          {"key": "identity", "question_node_id": "faq:identity", "required": False}]
CONTRACT = {"fields": FIELDS, "questions": {
    "faq:purpose": {"text": "Qual é o objetivo?"},
    "faq:identity": {"text": "Qual é seu nome?"},
}}


def reconcile(text, kind=None, key=None, fields=FIELDS, **kwargs):
    return reply_metadata.reconcile_question_metadata(
        reply=text, question_kind=kind, asked_field_key=key,
        eligible_fields=fields, contract=CONTRACT, **kwargs,
    )


@pytest.mark.parametrize("text", ["Me conte o que você quer alcançar", "O que faria diferença para você?", "Conte-me seu objetivo."])
def test_model_field_survives_unfamiliar_wording_and_no_question_mark(text):
    result = reconcile(text, "qualification", "purpose")
    assert result["asked_field_key"] == "purpose"
    assert result["warnings"] == []
    assert result["audit"]["candidate_reply"] == text


def test_explicit_model_field_is_not_overwritten_by_matching_another_example():
    result = reconcile("Qual é seu nome?", "qualification", "purpose")
    assert result["asked_field_key"] == "purpose"


def test_missing_metadata_recovers_only_exact_unambiguous_example():
    assert reconcile("Qual é o objetivo?")["asked_field_key"] == "purpose"
    assert reconcile("Qual é o objetivo? Qual é seu nome?")["asked_field_key"] is None
    assert "question_metadata_ambiguous" in reconcile("Qual é o objetivo? Qual é seu nome?")["warnings"]
    # Lexical resemblance never invents a field pointer.
    assert reconcile("Qual é teu principal objetivo?")["asked_field_key"] is None


@pytest.mark.parametrize("kind", ["confirmation", "consultative"])
def test_semantic_kind_is_preserved_even_without_punctuation(kind):
    assert reconcile("Me diga se esse resumo está certo", kind)["question_kind"] == kind


def test_invalid_or_already_collected_field_detaches_pointer_without_dropping_reply():
    result = reconcile("Essa opção atende sua dúvida?", "qualification", "purpose", fields=[])
    assert result["asked_field_key"] is None
    assert result["question_kind"] == "consultative"
    assert result["audit"]["candidate_reply"] == "Essa opção atende sua dúvida?"
    assert "question_field_not_eligible" in result["warnings"]


def test_handoff_never_consumes_an_optional_question_attempt():
    result = reconcile("Vou encaminhar à equipe.", "qualification", "identity", handoff_required=True)
    assert result["asked_field_key"] is None
    assert result["question_kind"] == "none"


def final_context(monkeypatch, *, messages=None, facts=None):
    context = ConversationContext(
        persona_slug="fixture", agent_slug="agent", agent_role="sdr",
        execution_strategy="interpret_then_respond", graph_version=1,
        graph_checksum="sha256:fixture", publication_id="publication:fixture",
        runtime_version=runtime.RUNTIME_VERSION, graph_contract=CONTRACT,
        messages=messages or [{"role": "user", "message_id": "in:1", "content": "Tenho uma dúvida"}],
        cart={"facts": facts or {}, "facts_by_key": {}, "asked_question_node_ids": []},
        rag_nodes=[], rag_paths=[],
    )
    decision = ConversationDecision(intent="collect_graph_fields", route="SDR", confidence=1, lead_stage="engajado")
    response = AgentResponse(reply_text=None, role="SDR", cart_state={}, proof={"valid": True})
    context.retrieval_trace.update(resolved_decision=decision.model_dump(mode="json"),
                                   resolved_response=response.model_dump(mode="json"))
    monkeypatch.setattr(runtime, "_turn_publication", lambda _: {
        "id": context.publication_id, "checksum": context.graph_checksum, "status": "active",
        "document_json": {"nodes": [], "branch_contracts": {}},
    })
    return context


def observation(reply, kind="qualification", key="purpose"):
    proposal = ConversationProposal(reply=reply)
    return {"proposal": proposal.model_dump(mode="json"),
            "interpretation": {"question_kind": kind, "asked_field_key": key}}


def test_real_proof_preserves_doubt_answer_with_inconsistent_metadata(monkeypatch):
    context = final_context(monkeypatch)
    text = "A equipe pode esclarecer os detalhes. O que você quer alcançar?"
    _, result = runtime._finalize_resolved_reply(context, observation(text, key="wrong"))
    assert result.reply_text == text
    assert result.proof["technical_pass"] is True
    assert result.proof["quality_pass"] is False
    assert result.proof["asked_field_key"] is None
    assert result.cart_state["asked_question_node_ids"] == []
    assert result.proof["reply_metadata_audit"]["candidate_reply"] == text


def test_repeated_wording_is_quality_warning_and_does_not_block_send(monkeypatch):
    text = "Qual é o objetivo?"
    context = final_context(monkeypatch, messages=[
        {"role": "assistant", "content": text},
        {"role": "user", "message_id": "in:1", "content": "Pode explicar?"},
    ])
    _, result = runtime._finalize_resolved_reply(context, observation(text))
    assert result.reply_text == text
    assert result.proof["technical_pass"] is True
    assert "repeated_public_question" in result.proof["quality_warnings"]


def test_confirm_summary_remains_confirmation_with_real_proof(monkeypatch):
    context = final_context(monkeypatch)
    _, result = runtime._finalize_resolved_reply(context, observation("Esse resumo está certo?", "confirmation", None))
    assert result.proof["question_kind"] == "confirmation"
    assert result.proof["asked_field_key"] is None
    assert result.proof["valid"] is True


def test_empty_reply_still_blocks_and_publication_change_still_raises(monkeypatch):
    context = final_context(monkeypatch)
    _, result = runtime._finalize_resolved_reply(context, observation(""))
    assert result.reply_text is None
    assert "empty_reply" in result.proof["gating_errors"]
    monkeypatch.setattr(runtime, "_turn_publication", lambda _: {"id": "different"})
    with pytest.raises(RuntimeError, match="publication changed"):
        runtime._finalize_resolved_reply(context, observation("Texto útil"))


def test_confirmation_with_stray_eligible_field_keeps_confirmation():
    result = reconcile("Confere o resumo?", "confirmation", "purpose")
    assert result["question_kind"] == "confirmation"
    assert result["asked_field_key"] is None
    assert "confirmation_field_pointer_detached" in result["warnings"]


def test_same_field_on_different_owners_does_not_spend_arbitrary_branch_attempt():
    fields = [{**FIELDS[0], "owner_node_id": "branch:a"},
              {**FIELDS[0], "owner_node_id": "branch:b"}]
    result = reconcile("Conte seu objetivo", "qualification", "purpose", fields=fields)
    assert result["asked_field_key"] is None
    assert "question_field_owner_ambiguous" in result["warnings"]


def test_finalization_never_recovers_pointer_detached_by_first_pass(monkeypatch):
    context = final_context(monkeypatch)
    text = "Qual é o objetivo?"
    first = reconcile(text, "qualification", "wrong")
    observed = observation(text, first["question_kind"], first["asked_field_key"])
    observed["reply_metadata_audit"] = first["audit"]
    observed["reply_metadata_warnings"] = first["warnings"]
    _, result = runtime._finalize_resolved_reply(context, observed)
    assert result.reply_text == text
    assert result.proof["asked_field_key"] is None
    assert result.cart_state["asked_question_node_ids"] == []
    assert result.proof["reply_metadata_audit"]["original"]["asked_field_key"] == "wrong"


def test_finalizer_handoff_updates_original_audit_and_consumes_no_field(monkeypatch):
    context = final_context(monkeypatch)
    resolved = AgentResponse.model_validate(context.retrieval_trace["resolved_response"])
    resolved = resolved.model_copy(update={"handoff_required": True, "role": ConversationRoute.HUMAN})
    context.retrieval_trace["resolved_response"] = resolved.model_dump(mode="json")
    text = "Vou encaminhar à equipe."
    first = reconcile(text, "qualification", "purpose")
    observed = observation(text, first["question_kind"], first["asked_field_key"])
    observed["reply_metadata_audit"] = first["audit"]
    _, result = runtime._finalize_resolved_reply(context, observed)
    assert result.reply_text == text
    assert result.handoff_required is True
    assert result.proof["asked_field_key"] is None
    assert result.cart_state["asked_question_node_ids"] == []
    audit = result.proof["reply_metadata_audit"]
    assert audit["original"] == {"question_kind": "qualification", "asked_field_key": "purpose"}
    assert audit["normalized"] == {"question_kind": "none", "asked_field_key": None}
    assert audit["status"] == "corrected"

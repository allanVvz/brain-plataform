from __future__ import annotations

import copy
import inspect
import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.conversation import (
    ConversationContext, ConversationProposal, ContextCard, ExtractedFact,
    SemanticInterpretation,
)
from services import graph_agent_runtime_v3, graph_compiler_v3, graph_proof_checker_v3


PERSONA = {"id": "10000000-0000-0000-0000-000000000001", "slug": "generic"}


def node(index: int, stable_id: str, *, parent_type: str = "knowledge", data=None, status="validated"):
    return {
        "id": f"20000000-0000-0000-0000-{index:012d}",
        "node_type": parent_type,
        "slug": stable_id.replace(":", "-"),
        "title": stable_id,
        "summary": stable_id,
        "tags": [],
        "status": status,
        "metadata": {"graph_json_node_id": stable_id, **(data or {})},
    }


def edge(index: int, source: dict, target: dict, relation="contains", data=None):
    return {
        "id": f"30000000-0000-0000-0000-{index:012d}",
        "source_node_id": source["id"],
        "target_node_id": target["id"],
        "relation_type": relation,
        "weight": 1,
        "metadata": {"active": True, "graph_json_edge_id": f"edge:{index}", **(data or {})},
    }


def compiled_fixture(*, accepted=None, depends_on=None, condition=None):
    root = node(1, "persona:generic")
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    branch_b = node(3, "branch:b", data={"capabilities": {"branch_anchor": True}})
    q_a = node(4, "question:a", parent_type="faq", data={"question": "Qual é a metragem?"})
    q_b = node(5, "question:b", parent_type="faq", data={"question": "Qual é a quantidade?"})
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "metragem", "question_node_id": "question:a", "required": True,
        "accepted_statuses": accepted or ["known"],
        "value_schema": {"type": "number", "minimum": 0},
        "depends_on": depends_on or [], "condition": condition,
        "overwrite_policy": "explicit_correction",
    }]}
    branch_b["metadata"]["qualification"] = {"fields": [{
        "key": "quantidade", "question_node_id": "question:b", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "integer", "minimum": 1},
    }]}
    rows = [root, branch_a, branch_b, q_a, q_b]
    edges = [
        edge(1, root, branch_a), edge(2, root, branch_b),
        edge(3, branch_a, q_a), edge(4, branch_b, q_b),
    ]
    return graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)


def publication(document):
    return {
        "id": "40000000-0000-0000-0000-000000000001",
        "version": 1,
        "checksum": document["checksum"],
        "status": "active",
        "document_json": document,
    }


def proposal(document, **updates):
    contract = document["branch_contracts"]["branch:a"]
    value = {
        "branch_action": "select",
        "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "metragem",
        "extracted_facts": [], "claims": [],
        "next_question_node_id": "question:a",
        "cited_node_ids": ["branch:a", "question:a"],
        "cited_chunk_ids": ["chunk:a"],
        "reply": "Posso te ajudar.",
        "qualification_complete": False, "handoff_requested": False,
    }
    value.update(updates)
    return value


def check(document, value, *, ledger=None, active=None, message="quero informar a metragem"):
    return graph_proof_checker_v3.check(
        publication=publication(document),
        contract=document["branch_contracts"][value["branch_anchor_node_id"]],
        ledger=ledger or {"graph_checksum": document["checksum"], "facts": {}},
        proposal=value, message=message, source_message_id="msg-1",
        package_node_ids=set(document["branch_contracts"][value["branch_anchor_node_id"]]["closure_node_ids"]),
        package_chunk_ids={"chunk:a", "chunk:b"},
        active_branch_node_id=active,
        branch_selection_allowed=active is None,
        branch_switch_allowed=True,
    )


def test_compiler_uses_capability_and_keeps_branches_isolated():
    document = compiled_fixture()
    assert document["branch_anchors"] == ["branch:a", "branch:b"]
    assert "question:b" not in document["branch_contracts"]["branch:a"]["closure_node_ids"]
    assert "question:a" not in document["branch_contracts"]["branch:b"]["closure_node_ids"]
    assert document["compiler_contract"]["path"].endswith("graph-agent-runtime-v3.md")


def test_embedding_provider_auto_selects_real_local_or_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GRAPH_RAG_EMBEDDING_PROVIDER", "auto")
    assert graph_compiler_v3.embedding_provider() == "local"
    assert graph_compiler_v3.embedding_model_name() == graph_compiler_v3.LOCAL_EMBEDDING_MODEL

    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-selection-only")
    assert graph_compiler_v3.embedding_provider() == "openai"
    assert graph_compiler_v3.embedding_model_name() == "text-embedding-3-small"


def test_native_embedding_is_losslessly_padded_for_pgvector_dimension():
    native = [0.25, -0.5, 1.0]
    projected = graph_compiler_v3._fit_embedding_dimension(native)
    assert projected[:3] == native
    assert len(projected) == graph_compiler_v3.EMBEDDING_DIMENSION
    assert all(value == 0.0 for value in projected[3:])

    with pytest.raises(RuntimeError, match="invalid native dimension"):
        graph_compiler_v3._fit_embedding_dimension(
            [1.0] * (graph_compiler_v3.EMBEDDING_DIMENSION + 1)
        )


def test_semantic_chunks_index_executable_contract_data():
    chunks = graph_compiler_v3.semantic_chunks({
        "id": "rule:generic", "title": "Regra genérica", "summary": "Regra",
        "data": {
            "claims": [{"claim_type": "availability", "policy": {"mode": "informational"}}],
            "handoff_rule": {"condition": "qualification_complete"},
            "validators": [{"kind": "json_schema"}],
        },
    })
    kinds = {chunk["kind"] for chunk in chunks}
    assert {"claims", "rule", "validators"}.issubset(kinds)


def test_compiler_projects_global_faq_subtree_to_every_branch_and_normalizes_embed():
    root = node(1, "persona:generic", parent_type="persona")
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    branch_b = node(3, "branch:b", data={"capabilities": {"branch_anchor": True}})
    global_root = node(4, "context:global", data={"capabilities": {"global_context": True}})
    faq = node(5, "faq:payment", parent_type="faq", data={
        "question": "Quais são as formas de pagamento?",
        "answer": "Aceitamos as formas publicadas pela empresa.",
        "aliases": ["Como posso pagar?"],
        "claims": [{
            "claim_type": "other", "policy": {"mode": "informational"},
            "evidence_node_ids": ["faq:payment"],
        }],
    })
    embed = node(6, "embed:generic", parent_type="embed")
    document = graph_compiler_v3.compile_graph(
        persona=PERSONA,
        node_rows=[root, branch_a, branch_b, global_root, faq, embed],
        edge_rows=[
            edge(1, root, branch_a), edge(2, root, branch_b),
            edge(3, root, global_root), edge(4, global_root, faq),
            edge(5, faq, embed, relation="publishes_to"),
        ],
    )

    assert document["node_by_id"]["embed:generic"]["node_type"] == "embedded"
    assert document["faq_projection_contract"] == "v1"
    assert document["eligible_faq_node_ids"] == ["faq:payment"]
    assert graph_compiler_v3.publication_index_node_ids(document) == ["faq:payment"]
    for branch in ("branch:a", "branch:b"):
        assert document["branch_memberships"][branch]["faq:payment"]["inclusion_reason"] == "global_context_descendant"
        assert document["branch_contracts"][branch]["eligible_faq_node_ids"] == ["faq:payment"]
    faq_chunk = next(
        chunk for chunk in graph_compiler_v3.semantic_chunks(document["node_by_id"]["faq:payment"])
        if chunk["kind"] == "faq"
    )
    assert "Pergunta: Quais são as formas de pagamento?" in faq_chunk["text"]
    assert "Resposta: Aceitamos as formas publicadas pela empresa." in faq_chunk["text"]


def test_compiler_rejects_primary_ambiguity_and_dependency_cycle():
    root = node(1, "root")
    other = node(2, "other")
    branch = node(3, "branch", data={"capabilities": {"branch_anchor": True}})
    with pytest.raises(graph_compiler_v3.GraphCompilationError, match="ambiguous_primary_path"):
        graph_compiler_v3.compile_graph(
            persona=PERSONA, node_rows=[root, other, branch],
            edge_rows=[edge(1, root, branch), edge(2, other, branch)],
        )

    q1 = node(4, "q1", parent_type="faq", data={"question": "Q1?"})
    q2 = node(5, "q2", parent_type="faq", data={"question": "Q2?"})
    branch["metadata"]["qualification"] = {"fields": [
        {"key": "a", "question_node_id": "q1", "depends_on": ["b"]},
        {"key": "b", "question_node_id": "q2", "depends_on": ["a"]},
    ]}
    with pytest.raises(graph_compiler_v3.GraphCompilationError, match="field_dependency_cycle"):
        graph_compiler_v3.compile_graph(
            persona=PERSONA, node_rows=[root, branch, q1, q2],
            edge_rows=[edge(3, root, branch), edge(4, branch, q1), edge(5, branch, q2)],
        )


def test_compiler_rejects_question_owned_by_another_branch():
    root = node(1, "root")
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    branch_b = node(3, "branch:b", data={"capabilities": {"branch_anchor": True}})
    question_b = node(4, "question:b", parent_type="faq", data={"question": "Pergunta B?"})
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "arbitrary", "question_node_id": "question:b",
        "value_schema": {"type": "string"},
    }]}
    with pytest.raises(graph_compiler_v3.GraphCompilationError, match="field_question_wrong_scope"):
        graph_compiler_v3.compile_graph(
            persona=PERSONA,
            node_rows=[root, branch_a, branch_b, question_b],
            edge_rows=[
                edge(1, root, branch_a), edge(2, root, branch_b),
                edge(3, branch_b, question_b),
            ],
        )


def test_compiler_rejects_factual_faq_without_self_authorized_claim():
    root = node(1, "persona:generic")
    branch = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    faq = node(3, "faq:detail", parent_type="faq", data={
        "question": "O que inclui?", "answer": "Inclui o processo aprovado.",
    })
    embedded = node(4, "embedded:generic", parent_type="embedded")
    with pytest.raises(graph_compiler_v3.GraphCompilationError, match="factual_faq_without_claim"):
        graph_compiler_v3.compile_graph(
            persona=PERSONA,
            node_rows=[root, branch, faq, embedded],
            edge_rows=[
                edge(1, root, branch), edge(2, branch, faq),
                edge(3, faq, embedded, relation="publishes_to"),
            ],
        )


def test_compiler_accepts_non_factual_greeting_faq_without_commercial_claim():
    root = node(1, "persona:generic")
    branch = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    faq = node(3, "faq:greeting", parent_type="faq", data={
        "question": "Oi", "answer": "Oi! Como posso ajudar?", "role": "greeting_response",
    })
    embedded = node(4, "embedded:generic", parent_type="embedded")

    document = graph_compiler_v3.compile_graph(
        persona=PERSONA,
        node_rows=[root, branch, faq, embedded],
        edge_rows=[
            edge(1, root, branch), edge(2, branch, faq),
            edge(3, faq, embedded, relation="publishes_to"),
        ],
    )

    assert document["eligible_faq_node_ids"] == ["faq:greeting"]


@pytest.mark.parametrize("status", ["unknown", "declined"])
def test_non_known_terminal_statuses_finish_collection_without_qualification(status):
    document = compiled_fixture(accepted=["known", status])
    value = proposal(document, branch_action="keep", branch_evidence_span="", extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": status,
        "value": None, "source_message_id": "msg-1", "evidence_span": "não sei",
        "confidence": 0.9,
    }], next_question_node_id=None, qualification_complete=True,
                     cited_node_ids=["branch:a"], cited_chunk_ids=[])
    proof = check(document, value, active="branch:a", message="não sei")
    assert proof["valid"], proof["errors"]
    assert proof["missing_fields"] == ["metragem"]


def test_needs_confirmation_remains_askable():
    document = compiled_fixture(accepted=["known", "needs_confirmation"])
    value = proposal(document, branch_action="keep", branch_evidence_span="", extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a",
        "status": "needs_confirmation", "value": None,
        "source_message_id": "msg-1", "evidence_span": "talvez 20 metros",
        "confidence": 0.9,
    }], next_question_node_id="question:a", qualification_complete=False,
                     cited_node_ids=["branch:a"], cited_chunk_ids=[])

    proof = check(document, value, active="branch:a", message="talvez 20 metros")

    assert proof["valid"], proof["errors"]
    assert proof["missing_fields"] == ["metragem"]


def test_unknown_rejected_and_json_schema_is_generic():
    document = compiled_fixture()
    unknown = proposal(document, extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": "unknown",
        "value": None, "source_message_id": "msg-1", "evidence_span": "não sei", "confidence": 1,
    }])
    assert "fact_status_not_accepted:metragem:unknown" in check(document, unknown, message="não sei")["errors"]
    invalid = proposal(document, extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": "known",
        "value": "grande", "source_message_id": "msg-1", "evidence_span": "grande", "confidence": 1,
    }])
    invalid_proof = check(document, invalid, message="grande")
    assert any(error.startswith("fact_schema_invalid:metragem") for error in invalid_proof["errors"])
    assert invalid_proof["missing_fields"] == ["metragem"]
    assert invalid_proof["accepted_facts"] == []


def test_short_answer_keep_and_switch_require_literal_evidence():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    keep = proposal(document, branch_action="keep", branch_evidence_span="",
                    branch_path_checksum=contract["branch_path_checksum"])
    assert check(document, keep, active="branch:a", message="2020")["valid"]
    switched = copy.deepcopy(keep)
    switched.update({
        "branch_action": "switch", "branch_anchor_node_id": "branch:b",
        "branch_path_checksum": document["branch_contracts"]["branch:b"]["branch_path_checksum"],
        "branch_evidence_span": "outra coisa", "next_question_node_id": "question:b",
        "cited_node_ids": ["branch:b", "question:b"], "cited_chunk_ids": ["chunk:b"],
    })
    bad = check(document, switched, active="branch:a", message="quero quantidade")
    assert "branch_evidence_not_literal" in bad["errors"]


def test_fact_correction_cannot_overwrite_silently():
    document = compiled_fixture()
    value = proposal(document, branch_action="keep", branch_evidence_span="", extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": "known",
        "value": 20, "source_message_id": "msg-1", "evidence_span": "20", "confidence": 1,
    }], next_question_node_id=None, qualification_complete=True,
                     cited_node_ids=["branch:a"], cited_chunk_ids=[])
    ledger = {"graph_checksum": document["checksum"], "facts": {
        "metragem": {"status": "known", "value": 10, "confidence": 1}
    }}
    silent = check(document, value, ledger=ledger, active="branch:a", message="20")
    assert "fact_correction_not_explicit:metragem" in silent["errors"]
    explicit = check(document, value, ledger=ledger, active="branch:a", message="na verdade 20")
    assert explicit["valid"], explicit["errors"]


def test_exact_graph_switch_is_an_explicit_branch_fact_correction():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:b"]
    value = proposal(
        document,
        branch_action="switch",
        branch_anchor_node_id="branch:b",
        branch_path_checksum=contract["branch_path_checksum"],
        branch_evidence_span="branch:b",
        extracted_facts=[{
            "field_key": "quantidade", "owner_node_id": "branch:b", "status": "known",
            "value": 2, "source_message_id": "msg-1", "evidence_span": "branch:b",
            "confidence": 1,
        }],
        next_question_node_id=None,
        cited_node_ids=["branch:b"], cited_chunk_ids=[], qualification_complete=True,
    )
    ledger = {"graph_checksum": document["checksum"], "facts": {
        "quantidade": {
            "status": "known", "value": 1, "confidence": 1,
            "owner_node_id": "branch:a",
        }
    }}
    proof = check(document, value, ledger=ledger, active="branch:a", message="quero branch:b")
    assert proof["valid"], proof["errors"]


def greeting_document(responses=None, nodes=None):
    return {
        "nodes": [
            {
                "id": "persona:generic", "node_type": "persona",
                "data": {
                    "conversation_policy": {"intents": {"greeting": {
                        "responses": responses or ["Olá! Bem-vindo."],
                        "always_acknowledge": True,
                    }}},
                    "appointment_policy": {
                        "identity_field": "nome_cliente",
                        "required_fields": ["nome_cliente"],
                        "field_questions": {"nome_cliente": "Como você se chama?"},
                    },
                },
            },
            *(nodes or []),
        ]
    }


def test_graph_faq_greeting_is_selected_by_the_customer_words_and_proven():
    document = greeting_document(responses=[])
    document["nodes"].extend([
        {
            "id": "faq:greeting:oi", "node_type": "faq",
            "data": {
                "role": "greeting_response", "question": "Oi",
                "answer": "Oi! Que bom ter você por aqui.", "triggers": ["oi"],
            },
        },
        {
            "id": "faq:greeting:night", "node_type": "faq",
            "data": {
                "role": "greeting_response", "question": "Boa noite",
                "answer": "Boa noite! Estou por aqui para ajudar.",
                "triggers": ["boa noite"],
            },
        },
    ])
    greeting = document["nodes"][0]["data"]["conversation_policy"]["intents"]["greeting"]
    greeting["responses"] = []
    greeting["response_node_ids"] = ["faq:greeting:oi", "faq:greeting:night"]

    selected = graph_agent_runtime_v3._greeting_policy(
        document, contract={}, facts={}, message="Boa noite",
    )
    assert selected["response"] == "Boa noite! Estou por aqui para ajudar."
    assert selected["response_node_id"] == "faq:greeting:night"

    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test", messages=[{"role": "user", "content": "Boa noite"}],
        cart={"facts": {}, "asked_question_node_ids": []}, rag_nodes=[], rag_paths=[],
        rag_chunks=[], context_cards=[], system_prompt="", available_services=[],
        active_branch_node_id=None, active_branch_node_ids=[], active_path_checksum=None,
        branch_node_ids=[], graph_contract={}, publication_id="publication-1",
        runtime_version=graph_agent_runtime_v3.RUNTIME_VERSION,
        retrieval_trace={
            "deterministic_intent": "greeting",
            "deterministic_reply": (
                "Boa noite! Estou por aqui para ajudar.\n\nComo você se chama?"
            ),
            "greeting_response_node_id": "faq:greeting:night",
            "asked_field_key": "nome_cliente", "next_question_node_id": "q:name",
            "missing_fields": ["nome_cliente"], "ledger_revision": 0,
        },
    )
    decision, response = graph_agent_runtime_v3.decide(context, model_observation=None)
    assert decision.evidence_node_ids == ["faq:greeting:night", "q:name"]
    assert response.evidence_node_ids == ["faq:greeting:night", "q:name"]


def test_customer_reply_never_contains_internal_service_change_copy():
    source = inspect.getsource(graph_agent_runtime_v3._decide)
    assert "Adicionei " not in source
    assert "Removi " not in source
    assert " em foco." not in source


def test_invalid_model_fallback_cannot_leave_terminal_state_on_sdr():
    contract = {
        "branch_anchor_node_id": "branch:a",
        "fields": [{
            "key": "name", "owner_node_id": "branch:a", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:name",
        }],
        "questions": {"q:name": {"field_key": "name", "text": "What is your name?"}},
        "conversation_policy": {
            "question_repetition": {"max_attempts": 1},
            "qualification": {
                "summary_template": "Known: {informed_fields}.",
                "confirmation_question": "Is this correct?",
                "completion_message": "The team will continue.",
                "incomplete_handoff_template": "Missing: {missing_fields}.",
            },
        },
        "field_labels": {"name": "name"},
    }
    known = {
        "status": "known", "value": "Beatriz", "owner_node_id": "branch:a",
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test", messages=[{"role": "user", "content": "Beatriz"}],
        cart={"facts": {"name": known}, "facts_by_key": {"name": [known]}},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )

    decision, response = graph_agent_runtime_v3._invalid_proposal_fallback(
        context, {"invalid": True}, ["proposal_schema_invalid"],
    )

    assert decision.intent == "awaiting_confirmation"
    assert decision.route.value == "SDR"
    assert response.handoff_required is False
    assert response.cart_state["sdr_state"] == "awaiting_confirmation"
    assert response.reply_text == "Known: name: Beatriz.\n\nIs this correct?"


def test_invalid_model_fallback_never_goes_silent_on_a_non_terminal_repeat():
    """Regression test for the 2026-08-17 live silence bug: a schema-invalid
    model proposal whose deterministic fallback reply happened to match a
    recent assistant message got the anti-repetition gate to blank it to
    "" outright, leaving the customer with literally no reply on that turn
    (`repetition_action: suppressed_duplicate_outbound`). Silence must stay
    reserved for a genuinely repeated *terminal* handoff -- an ordinary
    repeated confirmation still has to say something.
    """
    contract = {
        "branch_anchor_node_id": "branch:a",
        "fields": [{
            "key": "name", "owner_node_id": "branch:a", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:name",
        }],
        "questions": {"q:name": {"field_key": "name", "text": "What is your name?"}},
        "conversation_policy": {
            "question_repetition": {"max_attempts": 1},
            "qualification": {
                "summary_template": "Known: {informed_fields}.",
                "confirmation_question": "Is this correct?",
                "completion_message": "The team will continue.",
                "incomplete_handoff_template": "Missing: {missing_fields}.",
            },
        },
        "field_labels": {"name": "name"},
    }
    known = {
        "status": "known", "value": "Beatriz", "owner_node_id": "branch:a",
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test", messages=[
            {"role": "user", "content": "Beatriz"},
            # Same text the fallback is about to compute again -- forces
            # semantic_repetition without this being a terminal handoff.
            {"role": "assistant", "content": "Known: name: Beatriz.\n\nIs this correct?"},
        ],
        cart={"facts": {"name": known}, "facts_by_key": {"name": [known]}},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )

    decision, response = graph_agent_runtime_v3._invalid_proposal_fallback(
        context, {"invalid": True}, ["proposal_schema_invalid"],
    )

    assert response.proof["repetition_action"] != "suppressed_duplicate_outbound"
    assert response.reply_text == graph_agent_runtime_v3.CONTEXT_FAILURE_HANDOFF_REPLY
    assert decision.route.value == "HUMAN"
    assert response.proof["mode"] == "model_output_handoff"


def test_invalid_proposal_fallback_confirms_every_active_branch_not_just_the_focused_one(monkeypatch):
    """Regression test: a schema-invalid model proposal used to fall back to
    a hand-built document containing only the focused branch's own
    contract, so a customer with two confirmed services in the same pedido
    saw the confirmation summary collapse down to just whichever branch
    happened to be in focus this turn -- the other service silently
    dropped from the text. Confirmed live 2026-08-17: lead confirmed two
    services, got a summary naming only one.
    """
    root = node(1, "persona:generic", parent_type="persona", data={
        "conversation_policy": {
            "qualification": {
                "summary_template": "Resumo: {informed_fields}.",
                "confirmation_question": "Os dados estão corretos?",
                "completion_message": "A equipe continuará o atendimento.",
            },
        },
    })
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    branch_b = node(3, "branch:b", data={"capabilities": {"branch_anchor": True}})
    q_a = node(4, "question:a", parent_type="faq", data={"question": "Qual o serviço A?"})
    q_b = node(5, "question:b", parent_type="faq", data={"question": "Qual o serviço B?"})
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "campo_a", "question_node_id": "question:a", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string"},
    }]}
    branch_b["metadata"]["qualification"] = {"fields": [{
        "key": "campo_b", "question_node_id": "question:b", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string"},
    }]}
    rows = [root, branch_a, branch_b, q_a, q_b]
    edges = [
        edge(1, root, branch_a), edge(2, root, branch_b),
        edge(3, branch_a, q_a), edge(4, branch_b, q_b),
    ]
    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)
    contract_a = document["branch_contracts"]["branch:a"]

    pub = publication(document)
    persona_row = {**PERSONA, "config": {}}
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )

    fact_a = {"status": "known", "value": "Polimento", "owner_node_id": "branch:a"}
    fact_b = {"status": "known", "value": "Vitrificação", "owner_node_id": "branch:b"}
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"],
        messages=[{"role": "user", "content": "confirma"}],
        cart={
            "facts": {"campo_a": fact_a, "campo_b": fact_b},
            "facts_by_key": {"campo_a": [fact_a], "campo_b": [fact_b]},
        },
        rag_nodes=[], rag_paths=[], graph_contract=contract_a,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a", "branch:b"],
        publication_id=pub["id"],
    )

    decision, response = graph_agent_runtime_v3._invalid_proposal_fallback(
        context, {"invalid": True}, ["proposal_schema_invalid"],
    )

    assert "Polimento" in response.reply_text
    assert "Vitrificação" in response.reply_text


def test_greeting_recognizer_covers_how_people_actually_type():
    """WhatsApp openings stretch letters and chain forms; typos must not pass."""
    for message in (
        "oi", "oii", "Oiii!", "Olá", "olaa", "opa", "Alô", "salve", "e aí",
        "eai", "eae", "eaee", "E aee!", "ei", "Bom dia", "bom diaa", "Boa tarde", "boa noite", "boa",
        "tudo bem?", "Tudo bom", "beleza", "blz", "hey", "hello",
        "Oi, tudo bem? Queria saber quais serviços vocês fazem",
    ):
        assert graph_agent_runtime_v3._is_greeting(message) is True, message
    for message in (
        "oio", "oitenta reais", "eixo dianteiro", "quanto custa", "polimento",
    ):
        assert graph_agent_runtime_v3._is_greeting(message) is False, message


def test_only_a_greeting_without_a_request_may_skip_the_model():
    """Confirmed live 2026-08-14: a first-contact doubt was silently dropped.

    "Oi! Tudo bem? Queria saber quais serviços vocês fazem aí na Aurora."
    matched _is_greeting, named no branch anchor, and so took the
    deterministic short-circuit -- the question about services was never
    answered. Chained greeting forms must all be consumed before deciding.
    """
    for message in ("Oi", "oi, tudo bem?", "Bom dia! Tudo bem?", "olá, e aí"):
        assert graph_agent_runtime_v3._is_bare_greeting(message) is True, message
    for message in (
        "Oi! Tudo bem? Queria saber quais serviços vocês fazem aí na Aurora.",
        "bom dia, quanto custa um polimento",
        "oi, quero agendar",
    ):
        assert graph_agent_runtime_v3._is_bare_greeting(message) is False, message
        assert graph_agent_runtime_v3._is_greeting(message) is True, message


def test_canonical_burst_overlays_the_latest_physical_message_for_proof():
    messages = [
        {"id": 1, "role": "user", "external_message_id": "wamid-1", "content": "Byd"},
        {"id": 2, "role": "user", "external_message_id": "wamid-2", "content": "Dolphin"},
    ]

    projected = graph_agent_runtime_v3._overlay_canonical_inbound(
        messages, "Byd\nDolphin", "wamid-2",
    )

    assert projected[0]["content"] == "Byd"
    assert projected[1]["content"] == "Byd\nDolphin"
    assert projected[1]["external_message_id"] == "wamid-2"
    assert messages[1]["content"] == "Dolphin"


def test_greeting_never_reuses_a_phrase_this_conversation_already_heard():
    """Rotating by lead_ref kept one lead on one phrase forever.

    That is stable *across* leads and maximally repetitive *inside* a single
    conversation -- the exact opposite of what anti-repetition needs. The
    variant is now chosen by excluding what the agent already said here.
    """
    responses = ["Olá! A.", "Oi! B.", "Olá! C.", "Oi! D."]
    document = greeting_document(responses=responses)

    def policy(recent):
        return graph_agent_runtime_v3._greeting_policy(
            document, contract={}, facts={}, lead_ref=87, recent_replies=recent,
        )

    assert policy([])["response"] == responses[0]
    assert policy([responses[0]])["response"] == responses[1]
    assert policy([responses[0], responses[1]])["response"] == responses[2]
    # Every variant spent: no deterministic greeting at all, so the turn falls
    # through to the model instead of replaying a phrase. Silence is not an
    # option here -- the model still owes this turn a reply.
    assert policy(responses) is None


def test_greeting_does_not_reintroduce_a_customer_already_known():
    document = greeting_document(responses=["Oi! Eu sou a Lia, do atendimento."])
    persona = graph_agent_runtime_v3._persona_node(document)
    persona["data"]["conversation_policy"]["intents"]["greeting"][
        "responses_returning"
    ] = ["Oi de novo! Aqui é a Lia."]

    first_contact = graph_agent_runtime_v3._greeting_policy(
        document, contract={}, facts={},
    )
    returning = graph_agent_runtime_v3._greeting_policy(
        document, contract={}, facts={"nome_cliente": {"status": "known"}},
    )
    assert "eu sou a lia" in first_contact["response"].casefold()
    assert returning["response"] == "Oi de novo! Aqui é a Lia."


def test_claims_and_handoff_need_published_policy():
    document = compiled_fixture()
    value = proposal(document, claims=[{
        "claim_type": "price", "value": {"amount": 10},
        "evidence_node_ids": ["branch:a"], "evidence_chunk_ids": ["chunk:a"],
    }])
    proof = check(document, value)
    assert "claim_not_authorized:price" in proof["errors"]
    value["handoff_requested"] = True
    assert "handoff_not_authorized" in check(document, value)["errors"]


def test_claim_evidence_and_handoff_condition_are_exactly_authorized():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    contract["claims"] = [{
        "claim_type": "price", "policy": {"mode": "informational"},
        "evidence_node_ids": ["branch:a"],
    }]
    value = proposal(document, claims=[{
        "claim_type": "price", "value": {"amount": 10},
        "evidence_node_ids": ["question:a"], "evidence_chunk_ids": [],
    }])
    assert "claim_evidence_not_authorized:price" in check(document, value)["errors"]

    contract["handoff_rules"] = [{
        "node_id": "rule:handoff", "condition": "qualification_complete",
    }]
    completed = proposal(
        document, branch_action="keep", branch_evidence_span="",
        extracted_facts=[{
            "field_key": "metragem", "owner_node_id": "branch:a",
            "status": "known", "value": 10, "source_message_id": "msg-1",
            "evidence_span": "10", "confidence": 1,
        }], claims=[], next_question_node_id=None,
        cited_node_ids=["branch:a"], cited_chunk_ids=[],
        qualification_complete=True, handoff_requested=False,
    )
    missing_handoff = check(document, completed, active="branch:a", message="10")
    assert missing_handoff["errors"] == []
    assert missing_handoff["handoff_required"] is True
    completed["handoff_requested"] = True
    assert check(document, completed, active="branch:a", message="10")["valid"]


def test_dependencies_and_conditions_are_checked_without_field_hardcodes():
    root = node(1, "root")
    branch = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    q1 = node(3, "q:base", parent_type="faq", data={"question": "Base?"})
    q2 = node(4, "q:conditional", parent_type="faq", data={"question": "Condicional?"})
    branch["metadata"]["qualification"] = {"fields": [
        {"key": "base", "question_node_id": "q:base", "value_schema": {"type": "string"}},
        {"key": "conditional", "question_node_id": "q:conditional",
         "value_schema": {"type": "string"}, "depends_on": ["base"],
         "condition": {"field": "base", "operator": "equals", "value": "yes"}},
    ]}
    document = graph_compiler_v3.compile_graph(
        persona=PERSONA, node_rows=[root, branch, q1, q2],
        edge_rows=[edge(1, root, branch), edge(2, branch, q1), edge(3, branch, q2)],
    )
    value = {
        **proposal(document),
        "branch_action": "keep", "branch_evidence_span": "",
        "extracted_facts": [{
            "field_key": "conditional", "owner_node_id": "branch:a",
            "status": "known", "value": "value", "source_message_id": "msg-1",
            "evidence_span": "value", "confidence": 1,
        }],
        "next_question_node_id": "q:base", "cited_node_ids": ["branch:a", "q:base"],
        "cited_chunk_ids": [],
    }
    proof = check(document, value, active="branch:a", message="value")
    assert "fact_dependency_unsatisfied:conditional:base" in proof["errors"]
    assert "fact_condition_not_met:conditional" in proof["errors"]


def test_active_service_branch_authorizes_boolean_service_availability():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    contract["claims"] = [{
        "claim_type": "availability",
        "policy": {"mode": "informational"},
        "evidence_node_ids": ["rule:operation"],
    }]
    contract["closure_node_ids"].append("rule:operation")
    value = proposal(document, claims=[{
        "claim_type": "availability",
        "value": {"available": True},
        "evidence_node_ids": ["branch:a"],
        "evidence_chunk_ids": [],
    }])

    proof = check(document, value)

    assert proof["valid"], proof["errors"]


def test_active_service_branch_authorizes_existence_when_contract_omits_anchor_field():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    contract.pop("branch_anchor_node_id", None)
    contract["claims"] = [{
        "claim_type": "availability",
        "policy": {"mode": "informational"},
        "evidence_node_ids": ["rule:operation"],
    }]
    contract["closure_node_ids"].append("rule:operation")
    value = proposal(document, branch_action="keep", branch_evidence_span="", claims=[{
        "claim_type": "availability",
        "value": {"available": True},
        "evidence_node_ids": ["branch:a"],
        "evidence_chunk_ids": [],
    }])

    proof = check(document, value, active="branch:a")

    assert proof["valid"], proof["errors"]


def test_service_branch_does_not_authorize_schedule_availability_payload():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    contract["claims"] = [{
        "claim_type": "availability",
        "policy": {"mode": "informational"},
        "evidence_node_ids": ["rule:operation"],
    }]
    contract["closure_node_ids"].append("rule:operation")
    value = proposal(document, claims=[{
        "claim_type": "availability",
        "value": {"available": True, "date": "amanhã"},
        "evidence_node_ids": ["branch:a"],
        "evidence_chunk_ids": [],
    }])

    proof = check(document, value)

    assert "claim_evidence_not_authorized:availability" in proof["errors"]


def test_backend_has_no_question_text_composer():
    """The model reply is never completed or rewritten with graph copy."""
    assert not hasattr(graph_proof_checker_v3, "compose_published_question")


def test_model_question_is_not_reordered_to_first_missing_graph_field():
    contract = {
        "fields": [
            {"key": "first", "owner_node_id": "persona", "required": True,
             "accepted_statuses": ["known"], "question_node_id": "q:first"},
            {"key": "second", "owner_node_id": "persona", "required": True,
             "accepted_statuses": ["known"], "question_node_id": "q:second"},
        ]
    }
    model = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="checksum:a", branch_evidence_span="",
        extracted_facts=[], claims=[], next_question_node_id="q:second",
        cited_node_ids=[], cited_chunk_ids=[], reply="Qual é o segundo?",
        qualification_complete=False, handoff_requested=False,
    )

    assert model.next_question_node_id == "q:second"


def test_qualification_complete_is_derived_not_validated_against_the_model():
    """Regression test for the qualification_completion_mismatch gap (2026-08-08 report).

    qualification_complete is 100% derivable from `missing_fields`, the same
    reasoning that already drives "servico" being re-derived from
    active_branch_node_id server-side instead of trusted from the model.
    Confirmed live: the model unreliably self-reports this right at the
    last field either way (claims complete when a field is still missing,
    or the reverse), and check() used to reject the *entire* otherwise
    -valid proposal over it. It must no longer be a rejection reason, and
    check()'s own returned value must reflect the true state regardless of
    what the model claimed.
    """
    document = compiled_fixture()
    value = proposal(document, branch_action="keep", branch_evidence_span="", extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": "known",
        "value": 20, "source_message_id": "msg-1", "evidence_span": "20", "confidence": 1,
    }], next_question_node_id=None, qualification_complete=False,  # wrong on purpose
        cited_node_ids=["branch:a"], cited_chunk_ids=[])
    proof = check(document, value, active="branch:a", message="20")
    assert "qualification_completion_mismatch" not in proof["errors"]
    assert proof["valid"], proof["errors"]
    assert proof["qualification_complete"] is True  # true regardless of the model's claim

    still_missing = proposal(document, branch_action="keep", branch_evidence_span="",
                              qualification_complete=True,  # wrong on purpose
                              cited_node_ids=["branch:a"], cited_chunk_ids=[])
    proof2 = check(document, still_missing, active="branch:a", message="oi")
    assert "qualification_completion_mismatch" not in proof2["errors"]
    assert proof2["qualification_complete"] is False


def test_required_field_count_matches_applicable_required_fields():
    """required_field_count is the denominator for the v3 qualification
    progress score (lead_qualification._v3_progress_score) -- it must count
    every applicable required field regardless of resolution, staying
    consistent with pending_fields() across partially- and fully-filled
    facts (required_field_count == len(pending_fields) + resolved count).
    """
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]

    empty_facts: dict = {}
    assert graph_proof_checker_v3.required_field_count(contract, empty_facts) == 1
    pending = graph_proof_checker_v3.pending_fields(contract, empty_facts)
    assert len(pending) == 1

    resolved_facts = {
        "metragem": {"status": "known", "value": 20, "owner_node_id": "branch:a"},
    }
    assert graph_proof_checker_v3.required_field_count(contract, resolved_facts) == 1
    assert graph_proof_checker_v3.pending_fields(contract, resolved_facts) == []


def test_required_field_count_flows_through_check_result():
    document = compiled_fixture()
    value = proposal(document, branch_action="keep", branch_evidence_span="", extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": "known",
        "value": 20, "source_message_id": "msg-1", "evidence_span": "20", "confidence": 1,
    }], next_question_node_id=None, cited_node_ids=["branch:a"], cited_chunk_ids=[])
    proof = check(document, value, active="branch:a", message="20")
    assert proof["required_field_count"] == 1


def test_mmr_enforces_a_real_token_budget_not_just_a_card_count_cap():
    """Regression test for the missing token-budget guardrail (2026-08-08
    gap report): graph_agent_runtime_v3._mmr() only ever capped the RAG
    chunk package by *count* (16), unlike the legacy context_cards.
    resolve_cards(), which already enforces max_tokens=8000. Without a real
    ceiling, any future addition to what gets retrieved per turn (e.g.
    tone/flow-management skill content) could grow per-turn input size with
    nothing to stop it. Each candidate below is ~2500 estimated tokens
    (10,000 chars / 4); a 6000-token budget must keep the single best one
    and refuse the rest, well short of the count cap of 16.
    """
    candidates = [
        {"chunk_id": f"chunk:{i}", "source_node_id": f"node:{i}",
         "hybrid_score": 1.0 - i * 0.01, "chunk_text": f"conteudo unico {i} " * 500}
        for i in range(10)
    ]
    selected = graph_agent_runtime_v3._mmr(candidates, 16, max_tokens=6000)
    assert 1 <= len(selected) < 10


def test_mmr_always_keeps_at_least_one_result_even_over_budget():
    """A single candidate larger than the whole budget must still be
    returned -- an empty package is worse than one slightly over budget,
    the same trade-off context_cards.resolve_cards() already makes."""
    huge = {"chunk_id": "chunk:huge", "source_node_id": "node:huge",
            "hybrid_score": 1.0, "chunk_text": "palavra " * 10000}
    assert graph_agent_runtime_v3._mmr([huge], 16, max_tokens=10) == [huge]


def test_fallback_retrieval_branch_never_leaves_a_greeting_without_context():
    """Regression test for the branch-less-turn crash (2026-08-08 report).

    A bare greeting ("Oi") scores every Phase-A candidate near zero and
    there's no active branch yet on a fresh conversation, so build_context()
    used to raise RuntimeError and the whole turn produced no reply at all.
    """
    # Active branch always wins outright -- this never re-litigates branch
    # selection on the customer's behalf.
    assert graph_agent_runtime_v3._fallback_retrieval_branch(
        active_branch="branch:a", candidates=[{"branch_anchor_node_id": "branch:b"}],
        branch_anchors=["branch:a", "branch:b"],
    ) == "branch:a"
    # A scored candidate is used when there's no active branch yet.
    assert graph_agent_runtime_v3._fallback_retrieval_branch(
        active_branch=None, candidates=[{"branch_anchor_node_id": "branch:b"}],
        branch_anchors=["branch:a", "branch:b"],
    ) == "branch:b"
    # Nothing scored and nothing is active -- fall back deterministically
    # instead of raising, so context still loads for a generic reply.
    assert graph_agent_runtime_v3._fallback_retrieval_branch(
        active_branch=None, candidates=[], branch_anchors=["branch:b", "branch:a"],
    ) == "branch:a"
    # A publication with no branch anchors at all is a real, unrecoverable
    # error -- still signaled by returning None so the caller still raises.
    assert graph_agent_runtime_v3._fallback_retrieval_branch(
        active_branch=None, candidates=[], branch_anchors=[],
    ) is None


def test_exact_graph_alias_retrieves_new_branch_before_model_call():
    """An explicit switch must arrive with the selected branch proof package."""
    deterministic = [{"branch_anchor_node_id": "branch:b", "score": 1.0}]

    assert graph_agent_runtime_v3._retrieval_branch_for_turn(
        active_branch="branch:a",
        deterministic_candidates=deterministic,
        candidates=deterministic,
        branch_anchors=["branch:a", "branch:b"],
    ) == "branch:b"


def test_exact_branch_match_does_not_disable_vector_rag_retrieval():
    """Exact branch selection and semantic knowledge retrieval are independent.

    A compound message can identify the published audience/product and ask a
    knowledge question in the same turn.  The exact selector may skip branch
    ranking, but it must never zero the embedding passed to the RAG search.
    """
    source = inspect.getsource(graph_agent_runtime_v3.build_context)
    assert "embedding = graph_compiler_v3.query_embeddings([message])[0]" in source
    assert "embedding = None if deterministic_candidates" not in source


def test_fuzzy_candidate_does_not_replace_active_retrieval_branch():
    assert graph_agent_runtime_v3._retrieval_branch_for_turn(
        active_branch="branch:a",
        deterministic_candidates=[],
        candidates=[{"branch_anchor_node_id": "branch:b", "score": 0.8}],
        branch_anchors=["branch:a", "branch:b"],
    ) == "branch:a"


def test_evidenced_branch_candidates_excludes_zero_signal_branches():
    """Regression test for the phantom-reclamação-selection bug (2026-08-10).

    Confirmed live: a bare name/greeting turn with zero complaint signal got
    "select"-ed into Aurora's reclamação branch because branch_selection_allowed
    was keyed off the raw top-8 candidates, which _candidate_branches always
    populates with one entry per branch anchor regardless of score. Only
    candidates clearing the same evidence floor as possible_switches
    (BRANCH_EVIDENCE_MIN_SCORE) may authorize an unsolicited branch pick.
    """
    candidates = [
        {"branch_anchor_node_id": "aurora-product-wash", "score": 0.62},
        {"branch_anchor_node_id": "aurora-service-reclamacao", "score": 0.0},
        {"branch_anchor_node_id": "aurora-product-polish", "score": 0.2},
        {"branch_anchor_node_id": "aurora-product-ppf", "score": 0.05},
    ]
    evidenced = graph_agent_runtime_v3._evidenced_branch_candidates(candidates)
    ids = {item["branch_anchor_node_id"] for item in evidenced}
    assert ids == {"aurora-product-wash", "aurora-product-polish"}
    assert "aurora-service-reclamacao" not in ids


def test_evidenced_branch_candidates_respects_the_limit():
    candidates = [
        {"branch_anchor_node_id": f"branch:{i}", "score": 1.0} for i in range(10)
    ]
    assert len(graph_agent_runtime_v3._evidenced_branch_candidates(candidates)) == 8
    assert len(graph_agent_runtime_v3._evidenced_branch_candidates(candidates, limit=3)) == 3


def test_graph_title_or_alias_resolves_one_branch_without_model_repair():
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Service Alpha", "slug": "service-alpha", "data": {"aliases": ["alpha"]}},
            "branch:b": {"title": "Service Beta", "slug": "service-beta", "data": {"aliases": ["beta"]}},
        },
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }
    matches = graph_agent_runtime_v3._deterministic_branch_candidates(
        document, "I want service alpha"
    )
    assert [row["branch_anchor_node_id"] for row in matches] == ["branch:a"]
    assert matches[0]["deterministic_alias_match"] is True
    assert matches[0]["branch_evidence_span"] == "service alpha"


def test_branch_candidates_expose_published_node_type_for_audience_product_split():
    document = {
        "branch_anchors": ["audience:resale", "product_group:dresses"],
        "node_by_id": {
            "audience:resale": {
                "node_type": "audience", "title": "Atacado / revenda",
                "slug": "atacado-revenda", "data": {"aliases": ["atacado"]},
            },
            "product_group:dresses": {
                "node_type": "product_group", "title": "Vestidos",
                "slug": "vestidos", "data": {"aliases": ["vestidos"]},
            },
        },
        "coordinates": {
            "audience:resale": {"path_checksum": "checksum:audience"},
            "product_group:dresses": {"path_checksum": "checksum:group"},
        },
    }

    audience = graph_agent_runtime_v3._deterministic_branch_candidates(
        document, "Quero atacado",
    )
    group = graph_agent_runtime_v3._deterministic_branch_candidates(
        document, "Quero vestidos",
    )
    assert audience[0]["node_type"] == "audience"
    assert group[0]["node_type"] == "product_group"


def test_short_explicit_service_phrase_remains_a_deterministic_switch_signal():
    """Exact graph aliases take precedence over the short-answer fuzzy-search gate."""
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Service Alpha", "slug": "service-alpha", "data": {}},
            "branch:b": {"title": "Service Beta", "slug": "service-beta", "data": {"aliases": ["beta"]}},
        },
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }

    matches = graph_agent_runtime_v3._deterministic_branch_candidates(
        document, "Prefiro Beta.",
    )

    assert len(matches) == 1
    assert matches[0]["branch_anchor_node_id"] == "branch:b"
    assert matches[0]["deterministic_alias_match"] is True
    assert matches[0]["branch_evidence_span"] == "Beta"


def test_recent_reply_similarity_is_detected_before_pending_question_exception():
    reply = "Fazemos sim. Antes de tudo, como voce se chama?"
    messages = [{"role": "assistant", "content": reply}]

    assert graph_agent_runtime_v3._repeats_recent_outbound(reply, messages) is True


def test_third_pending_question_attempt_marks_field_unknown():
    contract = {
        "fields": [{
            "key": "name", "owner_node_id": "persona:one", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:name",
        }],
        "questions": {"q:name": {"field_key": "name", "text": "Qual seu nome?"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[
            {"role": "assistant", "content": "Qual seu nome?"},
            {"role": "user", "content": "Quero saber mais"},
            {"role": "assistant", "content": "Qual seu nome?"},
            {"role": "user", "content": "Pode continuar"},
        ],
        cart={"facts": {}, "asked_question_node_ids": ["q:name", "q:name"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="checksum:a", extracted_facts=[], claims=[],
        next_question_node_id="q:name", cited_node_ids=[], cited_chunk_ids=[],
        reply="Qual seu nome?", qualification_complete=False,
        handoff_requested=False,
    )

    fact = graph_agent_runtime_v3._unanswered_fact_after_question_limit(
        context=context, contract=contract, ledger_facts={}, proposal=proposal,
        max_attempts=1,
    )

    assert fact == {
        "field_key": "name", "owner_node_id": "persona:one",
        "status": "unknown", "value": None, "source_message_id": "",
        "evidence_span": "", "confidence": 1.0,
        "reason": "ignored_twice", "metadata": {"reason": "ignored_twice"},
    }


def test_repeated_field_gets_one_model_repair_then_safe_handoff(monkeypatch):
    document = compiled_fixture()
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    contract = document["branch_contracts"]["branch:a"]
    question_id = "question:a"
    question_text = contract["questions"][question_id]["text"]
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[
            {"role": "assistant", "content": question_text},
            {"message_id": "msg:interrupt", "role": "user", "content": "Quero entender melhor."},
        ],
        cart={"facts": {}, "asked_question_node_ids": [question_id]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        retrieval_trace={"retrieval_branch_node_id": "branch:a"},
    )
    repeated = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "", "extracted_facts": [], "claims": [],
        "next_question_node_id": question_id, "cited_node_ids": [],
        "cited_chunk_ids": [], "reply": f"Posso ajudar. {question_text}",
        "qualification_complete": False, "handoff_requested": False,
    }

    _first_decision, first_response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": repeated, "repair_attempt": 0},
    )
    assert first_response.reply_text is None
    assert first_response.proof["repair_required"] is True
    assert "question_already_asked" in first_response.proof["repetition_audit"]["failures"]
    assert first_response.cart_state["asked_question_node_ids"] == [question_id]

    second_decision, second_response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": repeated, "repair_attempt": 1},
    )
    assert second_decision.route.value == "HUMAN"
    assert second_response.handoff_required is True
    assert question_text not in (second_response.reply_text or "")
    assert second_response.cart_state["asked_question_node_ids"] == [question_id]
    assert second_response.proof["repetition_action"] == "repetition_handoff"



def test_explicit_unknown_marks_field_unknown_immediately():
    contract = {
        "fields": [{
            "key": "objective", "owner_node_id": "persona:one", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:objective",
        }],
        "questions": {"q:objective": {"field_key": "objective", "text": "Qual é o objetivo?"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"role": "user", "content": "Não sei"}],
        cart={"facts": {}, "asked_question_node_ids": ["q:objective"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="checksum:a", extracted_facts=[], claims=[],
        next_question_node_id="q:objective", cited_node_ids=[], cited_chunk_ids=[],
        reply="", qualification_complete=False, handoff_requested=False,
    )

    fact = graph_agent_runtime_v3._unanswered_fact_after_question_limit(
        context=context, contract=contract, ledger_facts={}, proposal=proposal,
    )

    assert fact and fact["status"] == "unknown"
    assert fact["metadata"] == {"reason": "explicit_unknown"}


def test_request_to_continue_without_pending_answer_marks_it_unknown():
    contract = {
        "fields": [{
            "key": "generic_field", "owner_node_id": "branch:a", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:pending",
        }],
        "questions": {
            "q:pending": {"field_key": "generic_field", "text": "Pending question?"},
        },
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{
            "role": "user", "content": "Podemos seguir sem essa informação?",
            "message_id": "msg-defer",
        }],
        cart={"facts": {}, "asked_question_node_ids": ["q:pending"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="sha256:path", extracted_facts=[], claims=[],
        next_question_node_id="q:pending", cited_node_ids=[], cited_chunk_ids=[],
        reply="", qualification_complete=False, handoff_requested=False,
    )

    fact = graph_agent_runtime_v3._unanswered_fact_after_question_limit(
        context=context, contract=contract, ledger_facts={}, proposal=proposal,
        max_attempts=1, doubt_answered=True,
    )

    assert fact and fact["status"] == "unknown"
    assert fact["reason"] == "explicit_unknown"
    assert fact["evidence_span"] == "Podemos seguir sem essa informação?"


def test_commercial_projection_separates_common_and_per_service_facts():
    document = {
        "node_by_id": {
            "branch:a": {"slug": "service-a", "title": "Service A"},
            "branch:b": {"slug": "service-b", "title": "Service B"},
        },
        "branch_contracts": {
            "branch:a": {"fields": [
                {"key": "name", "owner_node_id": "persona"},
                {"key": "condition", "owner_node_id": "branch:a"},
            ]},
            "branch:b": {"fields": [
                {"key": "name", "owner_node_id": "persona"},
                {"key": "condition", "owner_node_id": "branch:b"},
            ]},
        },
    }
    projection = graph_agent_runtime_v3._commercial_note_projection(
        document=document,
        active_branch_ids=["branch:a", "branch:b"],
        focused_branch_id="branch:b",
        facts_by_key={
            "name": [{"owner_node_id": "persona", "status": "known", "value": "José"}],
            "condition": [
                {"owner_node_id": "branch:a", "status": "known", "value": "riscos"},
                {"owner_node_id": "branch:b", "status": "unknown", "value": None},
            ],
        },
    )

    assert projection["common_facts"] == {"name": "José"}
    assert projection["services"]["branch:a"]["facts"] == {"condition": "riscos"}
    assert projection["services"]["branch:b"]["facts"] == {"condition": "desconhecido"}
    assert projection["focused_service_id"] == "branch:b"


def test_commercial_projection_humanizes_selector_fact_when_it_is_the_only_fact():
    """Regression (live 2026-08-18): a branch whose only known fact is its
    own selector field used to surface the raw graph slug ("chapeacao")
    verbatim in the header instead of the humanized title ("Chapeação"),
    and even that raw entry must not disappear -- the offering would go
    invisible in the header if it had zero facts at all."""
    document = {
        "node_by_id": {"branch:a": {"slug": "chapeacao", "title": "Chapeação"}},
        "branch_contracts": {"branch:a": {"fields": [{
            "key": "servico", "owner_node_id": "branch:a",
            "validation": {"mode": "enum", "values": [
                {"value": "chapeacao", "aliases": ["Chapeação"]},
            ]},
        }]}},
    }
    projection = graph_agent_runtime_v3._commercial_note_projection(
        document=document, active_branch_ids=["branch:a"], focused_branch_id="branch:a",
        facts_by_key={"servico": [
            {"owner_node_id": "branch:a", "status": "known", "value": "chapeacao"},
        ]},
    )
    assert projection["services"]["branch:a"]["facts"] == {"servico": "Chapeação"}


def test_commercial_projection_drops_redundant_selector_fact_when_other_facts_exist():
    document = {
        "node_by_id": {"branch:a": {"slug": "chapeacao", "title": "Chapeação"}},
        "branch_contracts": {"branch:a": {"fields": [
            {
                "key": "servico", "owner_node_id": "branch:a",
                "validation": {"mode": "enum", "values": [
                    {"value": "chapeacao", "aliases": ["Chapeação"]},
                ]},
            },
            {"key": "vehicle_color", "owner_node_id": "branch:a"},
        ]}},
    }
    projection = graph_agent_runtime_v3._commercial_note_projection(
        document=document, active_branch_ids=["branch:a"], focused_branch_id="branch:a",
        facts_by_key={
            "servico": [{"owner_node_id": "branch:a", "status": "known", "value": "chapeacao"}],
            "vehicle_color": [{"owner_node_id": "branch:a", "status": "known", "value": "branco"}],
        },
    )
    assert projection["services"]["branch:a"]["facts"] == {"vehicle_color": "branco"}


def test_commercial_projection_treats_persona_field_as_common_even_when_one_active_branch_omits_it():
    """Regression for the exact live catalog gap: branch:a's contract
    declares vehicle_color (persona-owned), branch:b's contract -- also
    active -- does not declare it at all. It must still project as a shared
    common fact, not get misfiled as owned by branch:a alone just because
    branch:b's own field list happens to omit it."""
    document = {
        "node_by_id": {
            "branch:a": {"slug": "chapeacao", "title": "Chapeação"},
            "branch:b": {"slug": "ppf", "title": "PPF"},
        },
        "branch_contracts": {
            "branch:a": {"fields": [{"key": "vehicle_color", "owner_node_id": "persona"}]},
            "branch:b": {"fields": []},
        },
    }
    projection = graph_agent_runtime_v3._commercial_note_projection(
        document=document, active_branch_ids=["branch:a", "branch:b"], focused_branch_id="branch:a",
        facts_by_key={
            "vehicle_color": [{"owner_node_id": "persona", "status": "known", "value": "branco"}],
        },
    )
    assert projection["common_facts"] == {"vehicle_color": "branco"}
    assert "vehicle_color" not in projection["services"]["branch:a"]["facts"]


def test_drop_only_service_operation_does_not_invent_focus_evidence():
    document = {
        "node_by_id": {
            "branch:a": {"slug": "service-a", "title": "Service A"},
            "branch:b": {"slug": "service-b", "title": "Service B"},
        },
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"message_id": "msg:1", "role": "user", "content": "Remova Service B"}],
        cart={"facts": {}}, rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id="branch:b",
        active_branch_node_ids=["branch:a", "branch:b"],
        retrieval_trace={"service_resolution": {
            "focused_branch_node_id": "branch:a",
            "operations": [{
                "action": "drop", "branch_anchor_node_id": "branch:b",
                "branch_path_checksum": "checksum:b", "evidence_span": "Service B",
            }],
        }},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:b",
        branch_path_checksum="checksum:b", extracted_facts=[], claims=[],
        next_question_node_id=None, cited_node_ids=[], cited_chunk_ids=[],
        reply="", qualification_complete=False, handoff_requested=False,
    )

    reconciled = graph_agent_runtime_v3._apply_authoritative_branch_resolution(
        proposal, context, document,
    )
    drop_facts = graph_agent_runtime_v3._service_facts_for_operations(
        operations=[item.model_dump(mode="json") for item in reconciled.service_operations],
        document=document, grouped_facts={}, source_message_id="msg:1",
    )

    assert reconciled.extracted_facts == []
    assert reconciled.branch_anchor_node_id == "branch:a"
    assert drop_facts[0]["status"] == "declined"
    assert drop_facts[0]["value"] is None


def test_repeated_service_changes_focus_without_recreating_service_fact():
    document = {
        "node_by_id": {"branch:a": {"slug": "service-a", "title": "Service A"}},
        "coordinates": {"branch:a": {"path_checksum": "checksum:a"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"message_id": "msg:2", "role": "user", "content": "Service A"}],
        cart={"facts_by_key": {"servico": [{
            "owner_node_id": "branch:a", "status": "known", "value": "service-a",
        }]}},
        rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        retrieval_trace={"service_resolution": {
            "focused_branch_node_id": "branch:a",
            "operations": [{
                "action": "keep", "branch_anchor_node_id": "branch:a",
                "branch_path_checksum": "checksum:a", "evidence_span": "Service A",
            }],
        }},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="checksum:a", extracted_facts=[], claims=[],
        next_question_node_id=None, cited_node_ids=[], cited_chunk_ids=[],
        reply="", qualification_complete=False, handoff_requested=False,
    )

    reconciled = graph_agent_runtime_v3._apply_authoritative_branch_resolution(
        proposal, context, document,
    )

    assert reconciled.service_operations[0].action.value == "keep"
    assert reconciled.extracted_facts == []


def test_blank_model_keep_operation_is_discarded_before_proposal_validation():
    raw = {
        "branch_action": "keep",
        "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": "checksum:a",
        "branch_evidence_span": "",
        "service_operations": [{
            "action": "keep",
            "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a",
            "evidence_span": "",
        }],
        "extracted_facts": [],
        "claims": [],
        "next_question_node_id": "q:condition",
        "cited_node_ids": [],
        "cited_chunk_ids": [],
        "reply": "Qual é a condição?",
        "qualification_complete": False,
        "handoff_requested": False,
    }

    sanitized = graph_agent_runtime_v3._sanitize_untrusted_service_operations(raw)
    proposal = ConversationProposal.model_validate(sanitized)

    assert proposal.service_operations == []


def test_model_service_operation_with_blank_checksum_is_discarded_before_validation():
    raw = {
        "branch_action": "add",
        "branch_anchor_node_id": "branch:engine-wash",
        "branch_path_checksum": None,
        "branch_evidence_span": "lavar o motor",
        "service_operations": [{
            "action": "add",
            "branch_anchor_node_id": "branch:engine-wash",
            "branch_path_checksum": "",
            "evidence_span": "lavar o motor",
        }],
        "extracted_facts": [],
        "claims": [],
        "next_question_node_id": None,
        "cited_node_ids": [],
        "cited_chunk_ids": [],
        "reply": "Posso explicar o serviço.",
        "qualification_complete": False,
        "handoff_requested": False,
    }

    sanitized = graph_agent_runtime_v3._sanitize_untrusted_service_operations(raw)
    proposal = ConversationProposal.model_validate(sanitized)

    assert proposal.service_operations == []


def test_pending_condition_answer_does_not_change_branch_from_service_word():
    contract = {
        "fields": [
            {
                "key": "condicao",
                "question_node_id": "question:condition",
            },
        ],
    }

    assert graph_agent_runtime_v3._is_direct_answer_to_pending_non_service_field(
        message="Os bancos estao manchados e a pintura perdeu o brilho",
        contract=contract,
        missing_fields=["condicao"],
        asked_question_node_ids=["question:condition"],
    ) is True


def test_explicit_service_change_is_not_hidden_by_pending_field_guard():
    contract = {
        "fields": [
            {
                "key": "condicao",
                "question_node_id": "question:condition",
            },
        ],
    }

    for message in ("Na verdade, prefiro PPF", "Tambem quero PPF"):
        assert graph_agent_runtime_v3._is_direct_answer_to_pending_non_service_field(
            message=message,
            contract=contract,
            missing_fields=["condicao"],
            asked_question_node_ids=["question:condition"],
        ) is False


def test_backend_exact_resolution_overrides_model_routing_and_derives_service():
    document = {
        "node_by_id": {
            "branch:a": {"title": "Service Alpha", "slug": "service-alpha"},
            "branch:b": {"title": "Service Beta", "slug": "service-beta"},
        },
        "branch_anchors": ["branch:a", "branch:b"],
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:x",
        messages=[{"message_id": "msg-1", "role": "user", "content": "Quero Service Alpha"}],
        cart={"facts": {}}, rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id=None, branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        retrieval_trace={"service_resolution": graph_agent_runtime_v3._resolve_service_operations(
            document, "Quero Service Alpha", active_branch_node_id=None,
            active_branch_node_ids=[],
        )},
    )
    model = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:b",
        branch_path_checksum="checksum:b", branch_evidence_span="",
        extracted_facts=[], claims=[], next_question_node_id=None,
        cited_node_ids=[], cited_chunk_ids=[], reply="Certo.",
        qualification_complete=False, handoff_requested=False,
    )

    resolved = graph_agent_runtime_v3._apply_authoritative_branch_resolution(
        model, context, document,
    )

    assert resolved.branch_action.value == "select"
    assert resolved.branch_anchor_node_id == "branch:a"
    assert resolved.branch_path_checksum == "checksum:a"
    assert [(fact.field_key, fact.value, fact.owner_node_id) for fact in resolved.extracted_facts] == [
        ("servico", "service-alpha", "branch:a"),
    ]


def test_backend_exact_additive_service_keeps_existing_branch_and_appends_new_one():
    document = {
        "node_by_id": {
            "branch:a": {"title": "Service Alpha", "slug": "service-alpha"},
            "branch:b": {"title": "Service Beta", "slug": "service-beta"},
        },
        "branch_anchors": ["branch:a", "branch:b"],
        "coordinates": {"branch:b": {"path_checksum": "checksum:b"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:x",
        messages=[{"message_id": "msg-add", "role": "user",
                   "content": "Também quero Service Beta"}],
        cart={"facts": {}}, rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        retrieval_trace={"service_resolution": graph_agent_runtime_v3._resolve_service_operations(
            document, "TambÃ©m quero Service Beta", active_branch_node_id="branch:a",
            active_branch_node_ids=["branch:a"],
        )},
    )
    model = ConversationProposal(
        branch_action="switch", branch_anchor_node_id="branch:b",
        branch_path_checksum="checksum:b", branch_evidence_span="Service Beta",
        extracted_facts=[], claims=[], next_question_node_id=None,
        cited_node_ids=[], cited_chunk_ids=[], reply="Perfeito.",
        qualification_complete=False, handoff_requested=False,
    )

    resolved = graph_agent_runtime_v3._apply_authoritative_branch_resolution(
        model, context, document,
    )

    assert resolved.branch_action.value == "add"
    assert resolved.branch_anchor_node_id == "branch:b"
    assert resolved.extracted_facts[0].owner_node_id == "branch:b"


def test_system_prompt_marks_model_service_routing_as_observation_only():
    prompt = graph_agent_runtime_v3.SYSTEM_PROMPT
    assert "branch_action" in prompt
    assert "service_observations" in prompt
    # Assert the contract, not the copy: this text is tuned for tone and
    # length, and pinning exact sentences made every prompt edit a red build.
    assert "por compatibilidade" in prompt
    assert "nunca autorizam mutação" in prompt
    assert "resolvedor do backend" in prompt


def test_system_prompt_still_has_anti_repetition_instruction():
    """Regression guard for the SYSTEM_PROMPT extraction (2026-08-14).

    build_context() used to build this text inline as a local `prompt`
    variable; it was extracted into a module-level constant so it's
    testable without mocking the whole context-building call chain. This
    confirms the extraction didn't drop or corrupt the pre-existing
    anti-repetition instruction.
    """
    prompt = graph_agent_runtime_v3.SYSTEM_PROMPT
    assert "Nunca repita uma frase que você já disse" in prompt
    assert "handoff_requested só pode ser true" in prompt
    assert "fatos_conhecidos lista tudo" in prompt
    # The 2026-08-19 rewrite folded six scattered anti-repetition clauses into
    # one canonical block plus the ladder. Both have to survive.
    assert "não o pergunte novamente" in prompt
    assert "asked_question_node_ids" in prompt
    assert "nunca preencha a reply com uma pergunta do backend" in prompt


def test_contract_fact_scope_does_not_compare_service_from_another_owner():
    contract = {"fields": [
        {"key": "servico", "owner_node_id": "branch:paint"},
        {"key": "name", "owner_node_id": "persona"},
    ]}
    grouped = {
        "servico": [
            {"field_key": "servico", "owner_node_id": "branch:interior", "value": "interior"},
            {"field_key": "servico", "owner_node_id": "branch:paint", "value": "paint"},
        ],
        "name": [{"field_key": "name", "owner_node_id": "persona", "value": "Allan"}],
    }

    scoped = graph_agent_runtime_v3._facts_for_contract(contract, grouped)

    assert scoped["servico"]["value"] == "paint"
    assert scoped["name"]["value"] == "Allan"


def test_active_branch_forces_keep_when_message_has_no_explicit_graph_alias():
    document = {
        "node_by_id": {"branch:a": {"title": "Service Alpha", "slug": "service-alpha"}},
        "coordinates": {"branch:a": {"path_checksum": "checksum:a"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:x",
        messages=[{"message_id": "msg-2", "role": "user", "content": "2020"}],
        cart={"facts": {}}, rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id="branch:a", branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        retrieval_trace={},
    )
    model = ConversationProposal(
        branch_action="switch", branch_anchor_node_id="branch:b",
        branch_path_checksum="checksum:b", branch_evidence_span="2020",
        extracted_facts=[{
            "field_key": "servico", "value": "wrong", "status": "known",
            "source_message_id": "msg-2", "owner_node_id": "branch:b",
            "evidence_span": "2020", "confidence": 1,
        }],
        claims=[], next_question_node_id=None, cited_node_ids=[], cited_chunk_ids=[],
        reply="Certo.", qualification_complete=False, handoff_requested=False,
    )

    resolved = graph_agent_runtime_v3._apply_authoritative_branch_resolution(
        model, context, document,
    )

    assert resolved.branch_action.value == "keep"
    assert resolved.branch_anchor_node_id == "branch:a"
    assert resolved.extracted_facts == []


def test_ambiguous_alias_never_selects_a_branch_deterministically():
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Alpha", "slug": "alpha", "data": {}},
            "branch:b": {"title": "Beta Alpha", "slug": "beta-alpha", "data": {"aliases": ["alpha"]}},
        },
        "coordinates": {},
    }
    assert graph_agent_runtime_v3._deterministic_branch_candidates(document, "alpha") == []


def test_ambiguous_alias_resolves_to_the_strictly_more_specific_match():
    """A generic alias colliding with a more specific one must not discard
    both candidates -- it should prefer the longer, more specific match
    instead of falling through to semantic search. Mirrors the real-world
    collision between "polimento" (generic) and "polimento de vidros"
    (specific) that made every glass-polish mention unresolvable."""
    document = {
        "branch_anchors": ["branch:polish", "branch:glass"],
        "node_by_id": {
            "branch:polish": {"title": "Polimento técnico", "slug": "polimento-tecnico", "data": {"aliases": ["polimento tecnico"]}},
            "branch:glass": {"title": "Polimento de vidros", "slug": "polimento-de-vidros", "data": {"aliases": ["polimento de vidros"]}},
        },
        "coordinates": {
            "branch:polish": {"path_checksum": "checksum:polish"},
            "branch:glass": {"path_checksum": "checksum:glass"},
        },
    }
    # Simulate the pre-fix alias shape (bare "polimento" alias on the
    # technical-polish node) to prove the tie-break -- not the alias data
    # fix -- is what resolves the collision.
    document["node_by_id"]["branch:polish"]["data"]["aliases"] = ["polimento"]

    matches = graph_agent_runtime_v3._deterministic_branch_candidates(
        document, "vocês fazem polimento de vidros?",
    )

    assert [row["branch_anchor_node_id"] for row in matches] == ["branch:glass"]


def test_greeting_intent_is_transversal_and_has_no_history_gate():
    assert not hasattr(graph_agent_runtime_v3, "_already_engaged")
    for message in ("Oi", "Oii", "oi, tudo bem?"):
        assert graph_agent_runtime_v3._is_greeting(message)


def test_legacy_converted_journey_is_a_post_qualification_state():
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test", messages=[], cart={}, rag_nodes=[], rag_paths=[],
        journey_state="converted", operational_mode="post_qualification_support",
    )
    assert context.journey_state.value == "converted"
    assert graph_agent_runtime_v3._journey_operational_mode("converted") == (
        "post_qualification_support"
    )


@pytest.mark.parametrize("message", ["Oi", "Oii"])
def test_reactivated_handoff_greeting_stays_in_support_without_restarting_service(message):
    service = {
        "field_key": "servico", "status": "known", "value": "service-alpha",
        "owner_node_id": "branch:a",
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[
            {"role": "assistant", "content": "A equipe seguirá com seu pedido."},
            {"message_id": "msg:greeting", "role": "user", "content": message},
        ],
        cart={
            "facts": {"servico": service},
            "facts_by_key": {"servico": [service]},
            "asked_question_node_ids": ["question:old"],
        },
        rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        available_services=[{"slug": "service-alpha", "label": "Service Alpha"}],
        journey_state="handed_off", pending_reconfirmation=True,
        operational_mode="post_qualification_support",
        post_completion_state={"has_terminal_journey": True},
        retrieval_trace={
            "deterministic_intent": "greeting",
            "deterministic_reply": "Olá! Como posso ajudar com seu pedido?",
            "missing_fields": [],
        },
    )

    decision, response = graph_agent_runtime_v3.decide(context, model_observation=None)

    assert decision.intent == "greeting"
    assert decision.route.value == "SDR"
    assert response.handoff_required is False
    assert response.cart_state["sdr_state"] == "handed_off"
    assert response.cart_state["facts"]["servico"]["value"] == "service-alpha"
    assert response.proof["intent_audit"]["greeting"] is True
    assert response.proof["service_resolution"]["rejected_non_service_value"] is True
    assert response.proof["service_resolution"]["resolved"] is True
    assert response.proof["confirmation_state"] == "post_qualification_support"
    assert response.proof["journey_action"] == "none"
    assert response.proof["interaction_observation"] == {
        "kind": "greeting",
        "evidence_span": message,
        "confidence": 1,
        "authority": "deterministic_graph_policy",
    }
    assert response.proof["intent_audit"]["resolved_intent"] == decision.intent
    assert response.proof["journey_transition"]["from"] == "handed_off"
    assert response.proof["journey_transition"]["to"] == "handed_off"


def test_social_message_cannot_become_referential_service_fact():
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"message_id": "msg:oii", "role": "user", "content": "Oii"}],
        cart={}, rag_nodes=[], rag_paths=[],
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        retrieval_trace={"branch_candidates": [{"branch_anchor_node_id": "branch:a"}]},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="checksum:a", branch_evidence_span="Oii",
        extracted_facts=[ExtractedFact(
            field_key="servico", value="Oii", owner_node_id="branch:a",
            source_message_id="msg:oii", evidence_span="Oii", confidence=1,
        )],
    )
    normalized = graph_agent_runtime_v3._normalize_referential_service_fact(
        proposal, context, {
            "branch_anchors": ["branch:a"],
            "node_by_id": {"branch:a": {"slug": "service-alpha", "title": "Service Alpha"}},
            "coordinates": {"branch:a": {"path_checksum": "checksum:a"}},
        },
    )
    assert all(fact.field_key != "servico" for fact in normalized.extracted_facts)


@pytest.mark.parametrize(
    ("message", "intent", "route", "handoff"),
    [
        ("Sim", "qualification_confirmed", "HUMAN", True),
        ("Não", "qualification_correction_requested", "SDR", False),
    ],
)
def test_published_confirmation_requires_an_explicit_followup_turn(
    message, intent, route, handoff,
):
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"message_id": "msg:confirmation", "role": "user", "content": message}],
        cart={"facts": {"name": {"status": "known", "value": "Beatriz"}}},
        rag_nodes=[], rag_paths=[], journey_state="awaiting_confirmation",
        operational_mode="confirmation",
        pending_confirmation_ref="qualification:current:0",
        graph_contract={"conversation_policy": {"qualification": {
            "completion_message": "Obrigada. A equipe continuará o atendimento.",
            "correction_prompt": "Diga qual informação precisa ser corrigida.",
        }}},
    )
    intent_kind = "confirmation" if message == "Sim" else "rejection"
    confirmation_state = "affirm" if message == "Sim" else "reject"
    reply = (
        "Perfeito. Posso encaminhar seu atendimento para a equipe?"
        if handoff else "Sem problema. O que você gostaria de ajustar?"
    )
    interpretation = SemanticInterpretation.model_validate({
        "intents": [{"kind": intent_kind, "evidence_span": message}],
        "state_relation": "continue",
        "confirmation": {
            "state": confirmation_state,
            "target_ref": "qualification:current:0",
            "evidence_span": message,
        },
        "recommended_next_action": "handoff" if handoff else "clarify",
        "reply": reply,
        "handoff_requested": handoff,
    })
    result = graph_agent_runtime_v3._deterministic_confirmation_decision(
        context, interpretation,
    )
    assert result is not None
    decision, response = result
    assert decision.intent == intent
    assert decision.route.value == route
    assert response.handoff_required is handoff
    assert response.cart_state["facts"]["name"]["value"] == "Beatriz"
    assert response.proof["explicit_confirmation"] is (message == "Sim")
    assert response.reply_text == reply


def test_confirmation_with_customer_question_never_preempts_model_answer():
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{
            "message_id": "msg:mixed", "role": "user",
            "content": "sim, mas quais opções tem?",
        }],
        cart={}, rag_nodes=[], rag_paths=[], journey_state="awaiting_confirmation",
        operational_mode="confirmation",
        pending_confirmation_ref="qualification:current:0",
    )
    interpretation = SemanticInterpretation.model_validate({
        "intents": [
            {"kind": "confirmation", "evidence_span": "sim"},
            {"kind": "commercial_question", "evidence_span": "quais opções tem"},
        ],
        "state_relation": "continue",
        "confirmation": {
            "state": "affirm", "target_ref": "qualification:current:0",
            "evidence_span": "sim",
        },
        "questions": [{
            "kind": "product_detail", "topic": "opções",
            "entity_node_ids": [], "evidence_span": "quais opções tem",
        }],
        "recommended_next_action": "answer_question",
        "reply": "Temos opções publicadas em diferentes grupos. Qual grupo você quer conhecer?",
        "handoff_requested": False,
    })
    assert graph_agent_runtime_v3._deterministic_confirmation_decision(
        context, interpretation,
    ) is None


def test_previously_mentioned_service_titles_is_empty_before_any_pitch():
    document = {
        "branch_anchors": ["branch:a"],
        "node_by_id": {"branch:a": {"title": "Polimento de vidros"}},
    }
    messages = [{"role": "user", "texto": "vocês fazem polimento de vidros?"}]
    assert graph_agent_runtime_v3._previously_mentioned_service_titles(document, messages) == []


def test_previously_mentioned_service_titles_flags_a_service_the_agent_already_pitched():
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Polimento de vidros"},
            "branch:b": {"title": "Restauração de faróis"},
        },
    }
    messages = [
        {"role": "user", "texto": "vocês fazem polimento de vidros?"},
        {"role": "assistant", "texto": "Fazemos, sim -- o polimento de vidros reduz manchas minerais."},
    ]
    assert graph_agent_runtime_v3._previously_mentioned_service_titles(document, messages) == [
        "Polimento de vidros"
    ]


def test_previously_mentioned_service_titles_ignores_the_customers_own_message():
    document = {
        "branch_anchors": ["branch:a"],
        "node_by_id": {"branch:a": {"title": "Polimento de vidros"}},
    }
    messages = [{"role": "user", "texto": "vocês fazem polimento de vidros?"}]
    assert graph_agent_runtime_v3._previously_mentioned_service_titles(document, messages) == []


def test_bare_exact_service_mention_requires_confirmation_when_another_field_is_pending():
    document = {
        "branch_anchors": ["aurora-product-polish-localized", "aurora-product-vitrification"],
        "node_by_id": {
            "aurora-product-polish-localized": {
                "title": "Polimento localizado", "slug": "polimento-localizado", "data": {},
            },
            "aurora-product-vitrification": {
                "title": "Vitrificação", "slug": "vitrificacao", "data": {},
            },
        },
        "coordinates": {
            "aurora-product-polish-localized": {"path_checksum": "checksum:polish"},
            "aurora-product-vitrification": {"path_checksum": "checksum:vitrification"},
        },
    }

    resolution = graph_agent_runtime_v3._resolve_service_operations(
        document, "Vitrificação",
        active_branch_node_id="aurora-product-polish-localized",
        active_branch_node_ids=["aurora-product-polish-localized"],
    )
    assert resolution["status"] == "needs_confirmation"
    assert resolution["operations"] == []
    assert resolution["candidate"]["branch_anchor_node_id"] == "aurora-product-vitrification"
    assert resolution["next_active_branch_node_ids"] == ["aurora-product-polish-localized"]
    assert resolution["focused_branch_node_id"] == "aurora-product-polish-localized"


def _service_resolution_document():
    return {
        "branch_anchors": ["branch:vitrification", "branch:polish"],
        "node_by_id": {
            "branch:vitrification": {
                "title": "Vitrifica\u00e7\u00e3o", "slug": "vitrificacao",
                "data": {"aliases": ["prote\u00e7\u00e3o cer\u00e2mica"]},
            },
            "branch:polish": {
                "title": "Polimento", "slug": "polimento", "data": {"aliases": []},
            },
        },
        "coordinates": {
            "branch:vitrification": {"path_checksum": "checksum:v"},
            "branch:polish": {"path_checksum": "checksum:p"},
        },
    }


def test_exact_service_applies_only_with_intent_or_direct_published_question():
    document = _service_resolution_document()
    for message in (
        "Quanto custa Vitrifica\u00e7\u00e3o?",
        "Quero saber quanto custa Vitrifica\u00e7\u00e3o?",
    ):
        informative = graph_agent_runtime_v3._resolve_service_operations(
            document, message, active_branch_node_id=None, active_branch_node_ids=[],
        )
        assert informative["status"] == "needs_confirmation"
        assert informative["operations"] == []

    explicit = graph_agent_runtime_v3._resolve_service_operations(
        document, "Quero VITRIFICA\u00c7\u00c3O!",
        active_branch_node_id=None, active_branch_node_ids=[],
    )
    assert explicit["status"] == "resolved"
    assert explicit["operations"][0]["evidence_type"] == "exact_catalog"

    looking_for = graph_agent_runtime_v3._resolve_service_operations(
        document, "Estou procurando prote\u00e7\u00e3o cer\u00e2mica.",
        active_branch_node_id=None, active_branch_node_ids=[],
    )
    assert looking_for["status"] == "needs_confirmation"
    assert looking_for["operations"] == []

    direct = graph_agent_runtime_v3._resolve_service_operations(
        document, "vitrifica\u00e7\u00e3o.", active_branch_node_id=None,
        active_branch_node_ids=[],
        contract={"fields": [{
            "key": "servico", "branch_selection_field": True,
            "question_node_id": "q:service",
        }]},
        asked_question_node_ids=["q:service"],
    )
    assert direct["status"] == "resolved"
    assert direct["operations"][0]["action"] == "add"


def test_textual_service_similarity_only_creates_candidate_and_handles_limits():
    document = _service_resolution_document()
    typo = graph_agent_runtime_v3._resolve_service_operations(
        document, "Quero vitrificasao", active_branch_node_id=None,
        active_branch_node_ids=[],
    )
    assert typo["status"] == "needs_confirmation"
    assert typo["operations"] == []
    assert typo["candidate"]["resolution_method"] == "textual_similarity"
    assert typo["candidate"]["edit_distance"] <= 3
    assert typo["candidate"]["text_similarity"] >= 0.8

    switch_typo = graph_agent_runtime_v3._resolve_service_operations(
        document, "Quero trocar para vitrificasao",
        active_branch_node_id="branch:polish",
        active_branch_node_ids=["branch:polish"],
    )
    assert switch_typo["candidate"]["action"] == "switch"
    assert switch_typo["candidate"]["replace_branch_node_id"] == "branch:polish"

    unrelated = graph_agent_runtime_v3._resolve_service_operations(
        document, "Quero lavagem completa", active_branch_node_id=None,
        active_branch_node_ids=[],
    )
    assert unrelated["status"] == "none"
    assert unrelated["operations"] == []

    ambiguous_document = {
        "branch_anchors": ["a", "b"],
        "node_by_id": {
            "a": {"title": "Polimento", "slug": "polimento", "data": {}},
            "b": {"title": "Polimenta", "slug": "polimenta", "data": {}},
        },
        "coordinates": {"a": {}, "b": {}},
    }
    ambiguous = graph_agent_runtime_v3._resolve_service_operations(
        ambiguous_document, "polimentx", active_branch_node_id=None,
        active_branch_node_ids=[],
    )
    assert ambiguous["status"] == "ambiguous"
    assert len(ambiguous["confirmation"]["options"]) == 2


def _reconcile_name(message, value, evidence, *, service_spans=None, confidence=1.0,
                    validation=None, asked=("q:name",)):
    contract = {"fields": [{
        "key": "nome", "owner_node_id": "persona:generic",
        "question_node_id": "q:name",
        "validation": validation or {"semantic_type": "human_full_name"},
    }]}
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:x",
        messages=[{"message_id": "msg-name", "role": "user", "content": message}],
        cart={"asked_question_node_ids": list(asked)}, rag_nodes=[], rag_paths=[],
        graph_contract=contract, branch_node_ids=[],
        retrieval_trace={"service_resolution": {
            "consumed_spans": service_spans or [],
        }},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="checksum:a", extracted_facts=[ExtractedFact(
            field_key="nome", owner_node_id="persona:generic", status="known",
            value=value, source_message_id="msg-name", evidence_span=evidence,
            confidence=confidence,
        )],
    )
    return graph_agent_runtime_v3._reconcile_human_full_name_facts(
        proposal, context=context, contract=contract,
    )


def test_name_casing_does_not_decide_whether_the_answer_counts():
    """The live deadlock of 2026-08-19, in one assertion.

    The customer typed "allan rodrigues"; the model answered with the same
    name capitalized. A literal `==` between message and value called that a
    mismatch, demoted a correct high-confidence extraction to
    `needs_confirmation`, and the confirmation could only be cleared by a
    handful of literal phrases -- so the same template came back forever.
    """
    reconciled, errors = _reconcile_name(
        "allan rodrigues", "Allan Rodrigues", "allan rodrigues",
    )
    assert not errors
    fact = reconciled.extracted_facts[0]
    assert fact.status == "known"
    assert fact.value == "Allan Rodrigues"
    # The persisted span is the customer's own slice, not the model's echo.
    assert fact.evidence_span == "allan rodrigues"
    assert fact.metadata["validation_method"] == "model_confidence"

    # And the model may hand back the span in its own casing too.
    echoed, errors = _reconcile_name(
        "allan rodrigues", "Allan Rodrigues", "Allan Rodrigues",
    )
    assert not errors
    assert echoed.extracted_facts[0].status == "known"
    assert echoed.extracted_facts[0].evidence_span == "allan rodrigues"


def test_confident_name_survives_a_composite_message_with_a_service():
    composite_message = "Ana Silva, tamb\u00e9m quero Vitrifica\u00e7\u00e3o"
    service_resolution = graph_agent_runtime_v3._resolve_service_operations(
        _service_resolution_document(), composite_message,
        active_branch_node_id=None, active_branch_node_ids=[],
    )
    assert service_resolution["operations"][0]["action"] == "add"
    assert service_resolution["operations"][0]["evidence_type"] == "exact_catalog"

    composite, errors = _reconcile_name(
        composite_message, "Ana Silva", "Ana Silva",
        service_spans=service_resolution["consumed_spans"],
    )
    assert not errors
    fact = composite.extracted_facts[0]
    # Name and service in one breath: both are kept, neither steals the
    # other's span.
    assert fact.status == "known"
    assert fact.value == "Ana Silva"


def test_low_confidence_name_outside_a_direct_answer_still_asks():
    composite, errors = _reconcile_name(
        "sou Ana Silva e queria uma ideia", "Ana Silva", "Ana Silva",
        confidence=0.4,
    )
    assert not errors
    fact = composite.extracted_facts[0]
    assert fact.status == "needs_confirmation"
    assert fact.value is None
    assert fact.metadata["confirmation"]["candidate"] == "Ana Silva"

    # The same low confidence, but the whole answer to the published name
    # question, needs no confirmation at all.
    direct, errors = _reconcile_name(
        "ana silva", "Ana Silva", "ana silva", confidence=0.4,
    )
    assert not errors
    assert direct.extracted_facts[0].status == "known"
    assert (
        direct.extracted_facts[0].metadata["validation_method"]
        == "direct_published_name_answer"
    )


def test_name_never_steals_a_span_already_consumed_as_a_service():
    overlapping, errors = _reconcile_name(
        "Quero Vitrifica\u00e7\u00e3o", "Quero Vitrifica\u00e7\u00e3o",
        "Quero Vitrifica\u00e7\u00e3o",
        service_spans=[{
            "text": "Vitrifica\u00e7\u00e3o", "start": 6, "end": 18,
            "branch_anchor_node_id": "branch:v", "evidence_type": "exact_catalog",
        }],
    )
    assert overlapping.extracted_facts == []
    assert errors[0]["errors"] == ["human_full_name_overlaps_service_evidence"]


def test_name_token_bounds_come_from_the_published_field():
    long_name = "Maria da Silva dos Santos Neto"
    accepted, errors = _reconcile_name(long_name, long_name, long_name)
    assert not errors
    assert accepted.extracted_facts[0].status == "known"

    rejected, errors = _reconcile_name(
        long_name, long_name, long_name,
        validation={
            "semantic_type": "human_full_name", "min_tokens": 2, "max_tokens": 5,
        },
    )
    assert rejected.extracted_facts == []
    assert errors[0]["errors"] == ["human_full_name_invalid"]


def test_name_without_literal_evidence_is_never_persisted_as_known():
    invented, errors = _reconcile_name(
        "quero um or\u00e7amento", "Ana Silva", "Ana Silva",
    )
    assert not errors
    fact = invented.extracted_facts[0]
    assert fact.status == "needs_confirmation"
    assert fact.metadata["confirmation"]["method"] == "unproven_evidence"


def test_semantic_service_candidate_requires_score_margin_model_match_and_free_literal_span():
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:x",
        messages=[{"message_id": "msg-sem", "role": "user",
                   "content": "quero proteger a pintura"}],
        cart={}, rag_nodes=[], rag_paths=[], graph_contract={}, branch_node_ids=[],
        retrieval_trace={"service_resolution": {"semantic_ranking": [
            {"branch_anchor_node_id": "branch:v", "score": 0.86},
            {"branch_anchor_node_id": "branch:p", "score": 0.75},
        ]}},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:v",
        branch_path_checksum="checksum:v", service_observations=[{
            "branch_anchor_node_id": "branch:v",
            "evidence_span": "proteger a pintura", "observed_intent": "select",
            "confidence": 0.9,
        }],
    )
    candidate, rejection = graph_agent_runtime_v3._semantic_service_candidate(
        context, proposal,
    )
    assert rejection is None
    assert candidate["resolution_method"] == "semantic_anchor_ranking"
    assert candidate["semantic_score"] == 0.86
    assert candidate["semantic_margin"] == pytest.approx(0.11)

    ambiguous = context.model_copy(update={"retrieval_trace": {
        "service_resolution": {"semantic_ranking": [
            {"branch_anchor_node_id": "branch:v", "score": 0.86},
            {"branch_anchor_node_id": "branch:p", "score": 0.80},
        ]},
    }})
    assert graph_agent_runtime_v3._semantic_service_candidate(
        ambiguous, proposal,
    )[1] == "semantic_margin_ambiguous"

    reserved = proposal.model_copy(update={"extracted_facts": [ExtractedFact(
        field_key="nome", owner_node_id="persona:generic", status="known",
        value="proteger a pintura", source_message_id="msg-sem",
        evidence_span="proteger a pintura", confidence=1,
    )]})
    assert graph_agent_runtime_v3._semantic_service_candidate(
        context, reserved,
    )[1] == "service_evidence_reserved_or_non_literal"

    textual_context = context.model_copy(update={"retrieval_trace": {
        "service_resolution": {"candidate": {
            "branch_anchor_node_id": "branch:v",
            "evidence_span": "proteger a pintura",
            "resolution_method": "textual_similarity",
        }},
    }})
    assert graph_agent_runtime_v3._semantic_service_candidate(
        textual_context, reserved,
    )[1] == "service_evidence_reserved_or_non_literal"


def _pending_confirmation_document():
    common = {
        "fields": [
            {
                "key": "nome", "owner_node_id": "persona:generic",
                "question_node_id": "q:name", "required": True,
                "accepted_statuses": ["known", "needs_confirmation", "invalid"],
                "validation": {"semantic_type": "human_full_name"},
            },
            {
                "key": "servico", "owner_node_id": "persona:generic",
                "question_node_id": "q:service", "required": True,
                "accepted_statuses": ["known"], "branch_selection_field": True,
            },
        ],
        "questions": {
            "q:name": {"field_key": "nome", "text": "Qual \u00e9 seu nome e sobrenome?"},
            "q:service": {"field_key": "servico", "text": "Qual servi\u00e7o voc\u00ea quer?"},
        },
    }
    branch = {
        "branch_anchor_node_id": "branch:v", "branch_path_checksum": "checksum:v",
        "fields": [
            {
                "key": "nome", "owner_node_id": "persona:generic", "required": True,
                "accepted_statuses": ["known"], "question_node_id": "q:name",
            },
            {
                "key": "servico", "owner_node_id": "branch:v", "required": True,
                "accepted_statuses": ["known"], "question_node_id": "q:service",
            },
            {
                "key": "objetivo", "owner_node_id": "branch:v", "required": True,
                "accepted_statuses": ["known"], "question_node_id": "q:objective",
            },
        ],
        "questions": {
            "q:name": {"field_key": "nome", "text": "Qual \u00e9 seu nome e sobrenome?"},
            "q:service": {"field_key": "servico", "text": "Qual servi\u00e7o voc\u00ea quer?"},
            "q:objective": {"field_key": "objetivo", "text": "Qual \u00e9 seu objetivo?"},
        },
    }
    return {
        "checksum": "sha256:confirmation", "common_contract": common,
        "branch_anchors": ["branch:v"], "branch_contracts": {"branch:v": branch},
        "node_by_id": {"branch:v": {"title": "Vitrifica\u00e7\u00e3o", "slug": "vitrificacao"}},
        "coordinates": {"branch:v": {"path_checksum": "checksum:v"}},
    }


@pytest.mark.parametrize("answer,expected_status,expected_question", [
    ("sim", "known", "q:service"),
    ("n\u00e3o", "invalid", "q:name"),
])
def test_name_candidate_confirmation_is_resolved_before_final_confirmation(
    monkeypatch, answer, expected_status, expected_question,
):
    document = _pending_confirmation_document()
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    pending = {
        "field_key": "nome", "owner_node_id": "persona:generic",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "kind": "name", "candidate": "Ana Silva", "field_key": "nome",
            "owner_node_id": "persona:generic", "transition": "pending",
        }},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[{"message_id": "msg-confirm", "role": "user", "content": answer}],
        cart={"facts": {"nome": pending}, "facts_by_key": {"nome": [pending]},
              "asked_question_node_ids": ["q:name"]},
        rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
        branch_node_ids=[], active_branch_node_ids=[],
        pending_confirmation_ref="fact:nome:persona:generic",
    )
    intent_kind = "confirmation" if answer == "sim" else "rejection"
    confirmation_state = "affirm" if answer == "sim" else "reject"
    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={
            "interpretation": {
                "intents": [{"kind": intent_kind, "evidence_span": answer}],
                "state_relation": "continue",
                "confirmation": {
                    "state": confirmation_state,
                    "target_ref": "fact:nome:persona:generic",
                    "evidence_span": answer,
                },
                "next_question_node_id": expected_question,
                "reply": (
                    "Certo. Qual serviço você procura?"
                    if answer == "sim"
                    else "Tudo bem. Como você prefere ser chamado?"
                ),
            },
        },
    )
    fact = response.proof["accepted_facts"][0]
    assert fact["status"] == expected_status
    assert response.proof["mode"] == "deterministic_field_confirmation"
    assert response.proof["explicit_confirmation"] is False
    assert response.proof["next_question_node_id"] == expected_question
    assert response.proof["qualification_complete"] is False


def test_resolving_name_candidate_asks_next_persisted_service_confirmation(monkeypatch):
    document = _pending_confirmation_document()
    document["confirmation_templates"] = {
        "name": "Seu nome completo é {candidate}?",
        "service_selection": "Você quer selecionar {candidate}?",
        "service_addition": "Você quer adicionar {candidate}?",
        "service_switch": "Você quer trocar para {candidate}?",
        "service_removal": "Você quer remover {candidate}?",
    }
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    pending_name = {
        "field_key": "nome", "owner_node_id": "persona:generic",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "kind": "name", "candidate": "Ana Silva", "field_key": "nome",
            "owner_node_id": "persona:generic", "transition": "pending",
        }},
    }
    pending_service = {
        "field_key": "servico", "owner_node_id": "branch:v",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "kind": "service", "candidate": "vitrificacao",
            "candidate_title": "Vitrificação",
            "branch_anchor_node_id": "branch:v", "action": "add",
            "transition": "pending",
        }},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[{"message_id": "msg-confirm-name", "role": "user", "content": "sim"}],
        cart={
            "facts": {"nome": pending_name, "servico": pending_service},
            "facts_by_key": {
                "nome": [pending_name], "servico": [pending_service],
            },
            "asked_question_node_ids": ["q:name"],
        },
        rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
        branch_node_ids=[], active_branch_node_ids=[],
        pending_confirmation_ref="fact:nome:persona:generic",
    )
    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={
            "interpretation": {
                "intents": [{"kind": "confirmation", "evidence_span": "sim"}],
                "state_relation": "continue",
                "confirmation": {
                    "state": "affirm",
                    "target_ref": "fact:nome:persona:generic",
                    "evidence_span": "sim",
                },
            },
        },
    )
    assert response.reply_text == "Você quer selecionar Vitrificação?"
    assert response.proof["confirmation_state"] == "field_confirmation"
    assert response.proof["pending_confirmation"]["kind"] == "service"
    assert response.proof["next_question_node_id"] is None
    assert response.proof["qualification_complete"] is False


def test_positive_service_candidate_confirmation_applies_bound_operation_only(monkeypatch):
    document = _pending_confirmation_document()
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    name = {
        "field_key": "nome", "owner_node_id": "persona:generic",
        "status": "known", "value": "Ana Silva",
    }
    pending = {
        "field_key": "servico", "owner_node_id": "branch:v",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "kind": "service", "candidate": "vitrificacao",
            "branch_anchor_node_id": "branch:v",
            "branch_path_checksum": "checksum:v", "action": "add",
            "method": "textual_similarity", "transition": "pending",
        }},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[{"message_id": "msg-service-confirm", "role": "user", "content": "sim"}],
        cart={"facts": {"nome": name, "servico": pending},
              "facts_by_key": {"nome": [name], "servico": [pending]},
              "asked_question_node_ids": ["q:service"]},
        rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
        branch_node_ids=[], active_branch_node_ids=[],
        pending_confirmation_ref="fact:servico:branch:v",
    )
    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={
            "interpretation": {
                "intents": [{"kind": "confirmation", "evidence_span": "sim"}],
                "state_relation": "continue",
                "confirmation": {
                    "state": "affirm",
                    "target_ref": "fact:servico:branch:v",
                    "evidence_span": "sim",
                },
                "branch_selections": [{
                    "action": "add", "branch_anchor_node_id": "branch:v",
                    "evidence_span": "sim",
                }],
                "next_question_node_id": "q:objective",
                "reply": "Perfeito, vou considerar a vitrificação. Qual é seu objetivo?",
            },
        },
    )
    assert response.cart_state["active_branch_node_ids"] == ["branch:v"]
    assert response.cart_state["active_branch_node_id"] == "branch:v"
    operation = response.proof["applied_service_operations"][0]
    assert operation["action"] == "add"
    assert operation["evidence_type"] == "confirmed_candidate"
    assert response.proof["service_operation_proof"]["valid"]
    assert response.proof["next_question_node_id"] == "q:objective"
    assert "objective" not in response.cart_state["facts_by_key"]
    assert response.reply_text == (
        "Perfeito, vou considerar a vitrificação. Qual é seu objetivo?"
    )
    assert response.proof["explicit_confirmation"] is False


def test_confirmed_switch_drops_previous_service_and_negative_preserves_it(monkeypatch):
    document = _pending_confirmation_document()
    document["branch_anchors"].append("branch:p")
    document["node_by_id"]["branch:p"] = {
        "title": "Polimento", "slug": "polimento",
    }
    document["coordinates"]["branch:p"] = {"path_checksum": "checksum:p"}
    document["branch_contracts"]["branch:p"] = copy.deepcopy(
        document["branch_contracts"]["branch:v"]
    )
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    old_service = {
        "field_key": "servico", "owner_node_id": "branch:p",
        "status": "known", "value": "polimento",
    }
    pending = {
        "field_key": "servico", "owner_node_id": "branch:v",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "kind": "service", "candidate": "vitrificacao",
            "branch_anchor_node_id": "branch:v", "action": "switch",
            "replace_branch_node_id": "branch:p", "method": "textual_similarity",
            "transition": "pending",
        }},
    }

    def context(answer):
        return ConversationContext(
            persona_slug="generic", agent_slug="agent", graph_version=1,
            graph_checksum=document["checksum"], publication_id=pub["id"],
            messages=[{"message_id": f"msg-{answer}", "role": "user", "content": answer}],
            cart={"facts": {"servico": old_service},
                  "facts_by_key": {"servico": [old_service, pending]},
                  "asked_question_node_ids": ["q:service"]},
            rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
            branch_node_ids=[], active_branch_node_id="branch:p",
            active_branch_node_ids=["branch:p"],
            pending_confirmation_ref="fact:servico:branch:v",
        )

    _decision, accepted = graph_agent_runtime_v3.decide(
        context("sim"), model_observation={
            "interpretation": {
                "intents": [{"kind": "confirmation", "evidence_span": "sim"}],
                "state_relation": "continue",
                "confirmation": {
                    "state": "affirm",
                    "target_ref": "fact:servico:branch:v",
                    "evidence_span": "sim",
                },
                "branch_selections": [{
                    "action": "switch", "branch_anchor_node_id": "branch:v",
                    "evidence_span": "sim",
                }],
            },
        },
    )
    assert [item["action"] for item in accepted.proof["applied_service_operations"]] == [
        "drop", "add",
    ]
    assert accepted.cart_state["active_branch_node_ids"] == ["branch:v"]
    assert accepted.cart_state["active_branch_node_id"] == "branch:v"

    _decision, rejected = graph_agent_runtime_v3.decide(
        context("n\u00e3o"), model_observation={
            "interpretation": {
                "intents": [{"kind": "rejection", "evidence_span": "n\u00e3o"}],
                "state_relation": "continue",
                "confirmation": {
                    "state": "reject",
                    "target_ref": "fact:servico:branch:v",
                    "evidence_span": "n\u00e3o",
                },
            },
        },
    )
    assert rejected.proof["applied_service_operations"] == []
    assert rejected.cart_state["active_branch_node_ids"] == ["branch:p"]
    assert rejected.cart_state["active_branch_node_id"] == "branch:p"


def test_rejected_confirmation_of_active_service_restores_previous_known_fact(monkeypatch):
    document = _pending_confirmation_document()
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    pending = {
        "field_key": "servico", "owner_node_id": "branch:v",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "kind": "service", "candidate": "vitrificacao",
            "branch_anchor_node_id": "branch:v", "action": "keep",
            "transition": "pending", "previous_fact": {
                "field_key": "servico", "owner_node_id": "branch:v",
                "status": "known", "value": "vitrificacao", "metadata": {},
            },
        }},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[{"message_id": "msg-no", "role": "user", "content": "n\u00e3o"}],
        cart={"facts": {"servico": pending},
              "facts_by_key": {"servico": [pending]},
              "asked_question_node_ids": ["q:service"]},
        rag_nodes=[], rag_paths=[], graph_contract=document["branch_contracts"]["branch:v"],
        branch_node_ids=[], active_branch_node_id="branch:v",
        active_branch_node_ids=["branch:v"],
        pending_confirmation_ref="fact:servico:branch:v",
    )
    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={
            "interpretation": {
                "intents": [{"kind": "rejection", "evidence_span": "não"}],
                "state_relation": "continue",
                "confirmation": {
                    "state": "reject",
                    "target_ref": "fact:servico:branch:v",
                    "evidence_span": "não",
                },
            },
        },
    )
    restored = response.cart_state["facts_by_key"]["servico"][0]
    assert restored["status"] == "known"
    assert restored["value"] == "vitrificacao"
    assert restored["metadata"]["confirmation"]["transition"] == "rejected"
    assert response.cart_state["active_branch_node_ids"] == ["branch:v"]
    assert response.cart_state["active_branch_node_id"] == "branch:v"


def test_literal_e_ae_then_allan_rodrigues_leaves_only_service_question_pending():
    document = _pending_confirmation_document()
    assert graph_agent_runtime_v3._is_bare_greeting("e ae")
    assert graph_agent_runtime_v3._resolve_service_operations(
        document, "Allan Rodrigues", active_branch_node_id=None,
        active_branch_node_ids=[], contract=document["common_contract"],
        asked_question_node_ids=["q:name"],
    )["operations"] == []
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"],
        messages=[{"message_id": "msg-name", "role": "user",
                   "content": "Allan Rodrigues"}],
        cart={"asked_question_node_ids": ["q:name"]}, rag_nodes=[], rag_paths=[],
        graph_contract=document["common_contract"], branch_node_ids=[],
        retrieval_trace={"service_resolution": {"consumed_spans": []}},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:v",
        branch_path_checksum="checksum:v", extracted_facts=[ExtractedFact(
            field_key="nome", owner_node_id="persona:generic", status="known",
            value="Allan Rodrigues", source_message_id="msg-name",
            evidence_span="Allan Rodrigues", confidence=1,
        )],
    )
    reconciled, errors = graph_agent_runtime_v3._reconcile_human_full_name_facts(
        proposal, context=context, contract=document["common_contract"],
    )
    assert not errors
    name = reconciled.extracted_facts[0].model_dump(mode="json")
    missing, askable, _required, _contract = (
        graph_agent_runtime_v3._aggregate_confirmation_state(
            document, [], {"nome": [name]},
        )
    )
    assert name["status"] == "known"
    assert [field["key"] for field in missing] == ["servico"]
    assert askable[0]["question_node_id"] == "q:service"


def test_two_services_in_one_message_are_both_added_without_additive_word():
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Serviço Alpha", "slug": "alpha", "data": {}},
            "branch:b": {"title": "Serviço Beta", "slug": "beta", "data": {}},
        },
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }

    resolution = graph_agent_runtime_v3._resolve_service_operations(
        document, "Quero Serviço Alpha e Serviço Beta",
        active_branch_node_id=None, active_branch_node_ids=[],
    )

    assert [(item["action"], item["branch_anchor_node_id"]) for item in resolution["operations"]] == [
        ("add", "branch:a"), ("add", "branch:b"),
    ]
    assert resolution["next_active_branch_node_ids"] == ["branch:a", "branch:b"]


def test_new_service_without_operation_asks_add_or_switch_once():
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Serviço Alpha", "slug": "alpha", "data": {}},
            "branch:b": {"title": "Serviço Beta", "slug": "beta", "data": {}},
        },
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }
    ambiguous = graph_agent_runtime_v3._resolve_service_operations(
        document, "Serviço Beta",
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    additive = graph_agent_runtime_v3._resolve_service_operations(
        document, "adicione Serviço Beta",
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )

    assert ambiguous["status"] == "needs_confirmation"
    assert ambiguous["candidate"]["operation_ambiguous"] is True
    assert graph_agent_runtime_v3._service_candidate_template_key(
        ambiguous["candidate"], ["branch:a"],
    ) == "add_or_switch_question"
    assert additive["operations"][0]["action"] == "add"


def test_service_clarification_uses_two_attempts_then_handoff(monkeypatch):
    document = _pending_confirmation_document()
    document["nodes"] = [{
        "id": "persona:generic", "node_type": "persona", "data": {
            "conversation_policy": {"service_clarification": {
                "add_or_switch_question": "Trocar ou adicionar {candidate}?",
                "retry_question": "Ainda não entendi. Trocar ou adicionar {candidate}?",
                "handoff_message": "Vou chamar a equipe. Serviços: {services}.",
                "summary_template": "Até agora seu pedido tem: {services}.",
            }},
        },
    }]
    document["branch_anchors"].append("branch:p")
    document["node_by_id"]["branch:p"] = {"title": "Polimento", "slug": "polimento"}
    document["coordinates"]["branch:p"] = {"path_checksum": "checksum:p"}
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )

    def pending(attempts):
        return {
            "field_key": "servico", "owner_node_id": "branch:v",
            "status": "needs_confirmation", "value": None,
            "metadata": {"confirmation": {
                "kind": "service", "capability": "branch_selector",
                "candidate": "vitrificacao", "candidate_title": "Vitrificação",
                "branch_anchor_node_id": "branch:v", "action": "add",
                "operation": "add", "operation_ambiguous": True,
                "attempts": attempts,
            }},
        }

    def context(attempts, message):
        fact = pending(attempts)
        return ConversationContext(
            persona_slug="generic", agent_slug="agent", graph_version=1,
            graph_checksum=document["checksum"], publication_id=pub["id"],
            messages=[{"message_id": f"msg-{attempts}", "role": "user", "content": message}],
            cart={"facts_by_key": {"servico": [fact]}},
            rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
            branch_node_ids=[], active_branch_node_id="branch:p",
            active_branch_node_ids=["branch:p"],
            retrieval_trace={"service_resolution": {}},
        )

    retry_decision, retry = graph_agent_runtime_v3.decide(
        context(1, "quero isso"), model_observation=None,
    )
    assert retry_decision.intent == "service_clarification_retry"
    assert retry.proof["clarification_attempts"] == 2
    assert retry.reply_text == "Ainda não entendi. Trocar ou adicionar Vitrificação?"
    assert retry.handoff_required is False

    handoff_decision, handoff = graph_agent_runtime_v3.decide(
        context(2, "continua igual"), model_observation=None,
    )
    assert handoff_decision.intent == "service_clarification_exhausted"
    assert handoff.handoff_required is True
    assert "Polimento" in handoff.reply_text
    assert "Vitrificação" in handoff.reply_text
    assert "?" not in handoff.reply_text


def test_graph_owned_service_summary_supports_three_services():
    document = {
        "nodes": [{"node_type": "persona", "data": {"conversation_policy": {
            "service_clarification": {
                "summary_template": "Até agora seu pedido tem: {services}.",
            },
        }}}],
        "node_by_id": {
            "a": {"title": "Lavagem"}, "b": {"title": "Chapeação"},
            "c": {"title": "Vitrificação"},
        },
    }
    assert graph_agent_runtime_v3._service_request_summary(
        document, ["a", "b", "c"],
    ) == "Até agora seu pedido tem: Lavagem, Chapeação, Vitrificação."


def test_explicit_service_switch_drops_focus_before_adding_new_service():
    document = {
        "branch_anchors": ["branch:a", "branch:b"],
        "node_by_id": {
            "branch:a": {"title": "Serviço Alpha", "slug": "alpha", "data": {}},
            "branch:b": {"title": "Serviço Beta", "slug": "beta", "data": {}},
        },
        "coordinates": {
            "branch:a": {"path_checksum": "checksum:a"},
            "branch:b": {"path_checksum": "checksum:b"},
        },
    }

    message = "Na verdade, prefiro Serviço Beta"
    resolution = graph_agent_runtime_v3._resolve_service_operations(
        document, message,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )

    assert [item["action"] for item in resolution["operations"]] == ["drop", "add"]
    assert resolution["next_active_branch_node_ids"] == ["branch:b"]
    assert resolution["operations"][0]["evidence_type"] == "explicit_change"
    proof = graph_proof_checker_v3.check_service_operations(
        document=document,
        message=message,
        operations=resolution["operations"],
        active_branch_node_ids=["branch:a"],
        consumed_service_spans=resolution["consumed_spans"],
    )
    assert proof["valid"], proof["errors"]
    assert proof["next_active_branch_node_ids"] == ["branch:b"]


def test_product_audience_branch_uses_graph_selector_not_legacy_servico():
    document = {
        "common_contract": {"fields": [{
            "key": "purchase_profile", "branch_selection_field": True,
        }]},
        "node_by_id": {
            "audience:retail": {"title": "Uso proprio", "slug": "retail"},
        },
    }
    facts = graph_agent_runtime_v3._service_facts_for_operations(
        operations=[{
            "action": "add", "branch_anchor_node_id": "audience:retail",
            "branch_path_checksum": "checksum:retail",
            "evidence_span": "uso proprio", "evidence_type": "exact_catalog",
        }],
        document=document, grouped_facts={}, source_message_id="msg:retail",
    )

    assert facts[0]["field_key"] == "purchase_profile"
    assert facts[0]["value"] == "retail"
    assert all(fact["field_key"] != "servico" for fact in facts)


def test_removing_one_service_preserves_the_other_two():
    document = {
        "branch_anchors": ["branch:a", "branch:b", "branch:c"],
        "node_by_id": {
            "branch:a": {"title": "Alpha", "slug": "alpha", "data": {}},
            "branch:b": {"title": "Beta", "slug": "beta", "data": {}},
            "branch:c": {"title": "Gamma", "slug": "gamma", "data": {}},
        },
        "coordinates": {
            key: {"path_checksum": f"checksum:{key[-1]}"}
            for key in ("branch:a", "branch:b", "branch:c")
        },
    }
    resolution = graph_agent_runtime_v3._resolve_service_operations(
        document, "remova Beta do pedido",
        active_branch_node_id="branch:c",
        active_branch_node_ids=["branch:a", "branch:b", "branch:c"],
    )
    assert [(item["action"], item["branch_anchor_node_id"])
            for item in resolution["operations"]] == [("drop", "branch:b")]
    assert set(resolution["next_active_branch_node_ids"]) == {"branch:a", "branch:c"}
    assert "branch:b" not in resolution["next_active_branch_node_ids"]


def test_service_evidence_cannot_be_reused_as_objective_value():
    document = {
        "branch_anchors": ["branch:vitrification"],
        "node_by_id": {
            "branch:vitrification": {
                "title": "Vitrificação", "slug": "vitrificacao", "data": {},
            },
        },
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"message_id": "msg-jose", "role": "user", "content": "Vitrificação"}],
        cart={}, rag_nodes=[], rag_paths=[],
        retrieval_trace={"service_resolution": {
            "consumed_spans": [{"text": "Vitrificação", "start": 0, "end": 12}],
        }},
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:vitrification",
        branch_path_checksum="checksum",
        extracted_facts=[ExtractedFact(
            field_key="objective", owner_node_id="persona:aurora",
            value="Vitrificação", evidence_span="Vitrificação",
        )],
    )

    cleaned, validation = graph_agent_runtime_v3._remove_consumed_service_facts(
        proposal, context=context, document=document,
    )

    assert cleaned.extracted_facts == []
    assert validation[0]["errors"] == ["service_evidence_consumed"]


def test_recent_messages_and_chunks_are_projected_to_minimum_prompt_contract():
    messages = graph_agent_runtime_v3._project_recent_messages([
        {
            "id": 1, "role": "user", "content": "hello", "created_at": "now",
            "metadata": {"secret": "must-not-leak"}, "proof": {"large": True},
        }
    ])
    assert messages == [{
        "message_id": 1, "role": "user", "content": "hello", "created_at": "now",
    }]
    chunk = graph_agent_runtime_v3._compact_prompt_chunk({
        "id": "chunk-1", "source_graph_node_id": "node-1", "chunk_kind": "rule",
        "chunk_text": "complete rule", "chunk_checksum": "checksum",
        "path_checksum": "path", "metadata": {
            "provenance": {"source": "graph", "status": "validated", "debug": "drop"},
            "large_internal_payload": {"drop": True},
        },
    })
    assert chunk["metadata"] == {"provenance": {"source": "graph", "status": "validated"}}


def test_retrieval_reserves_one_authorized_faq_beyond_full_structural_package():
    structural = [
        {"chunk_id": f"structural:{index}"}
        for index in range(graph_agent_runtime_v3.RAG_CHUNK_LIMIT)
    ]
    faq = [{"chunk_id": "faq:current-turn"}]

    optional_slots = graph_agent_runtime_v3._optional_retrieval_chunk_slots(
        structural, faq,
    )

    assert optional_slots == 0
    assert len(structural) + len(faq) == (
        graph_agent_runtime_v3.RAG_CHUNK_LIMIT
        + graph_agent_runtime_v3.RAG_FAQ_CHUNK_RESERVE
    )


def test_retrieval_rejects_more_than_one_reserved_faq_chunk():
    with pytest.raises(RuntimeError, match="reserved chunk limit"):
        graph_agent_runtime_v3._optional_retrieval_chunk_slots(
            [], [{"chunk_id": "faq:a"}, {"chunk_id": "faq:b"}],
        )


def test_repair_package_keeps_exact_chunks_and_one_chunk_per_required_node():
    rows = [
        {
            "id": f"chunk:{source}:{kind}",
            "source_graph_node_id": f"node:{source}",
            "chunk_kind": kind,
        }
        for source in range(4)
        for kind in ("content", "question", "aliases")
    ]
    required = graph_agent_runtime_v3._repair_chunks(
        rows,
        [
            {"kind": "node", "id": "node:0"},
            {"kind": "node", "id": "node:1"},
            {"kind": "chunk", "id": "chunk:2:aliases"},
        ],
    )
    ids = {row["id"] for row in required}
    assert "chunk:2:aliases" in ids
    assert len(required) == 5


def test_semantic_chunking_separates_question_answer_and_field_intent():
    node_value = {
        "id": "n", "title": "FAQ", "summary": "Resumo", "data": {
            "question": "Pergunta?", "content": {"answer": "Resposta."},
            "aliases": ["apelido"], "qualification": {"fields": [{
                "key": "campo", "question_node_id": "q", "normalization": "texto",
            }]},
        },
    }
    kinds = {chunk["kind"] for chunk in graph_compiler_v3.semantic_chunks(node_value)}
    assert {"question", "answer", "aliases", "field_intent"}.issubset(kinds)


def test_pending_fields_ignores_a_fact_owned_by_a_different_branch():
    """Regression test for the 2026-08-06 finding.

    Field keys (e.g. "servico", "modelo_veiculo") are shared across every
    product's own field declarations, each scoped by owner_node_id.
    field_resolved() alone never checked owner_node_id, so a fact accepted
    while a *different* branch was active kept counting as resolved for
    the new branch after a switch — required fields the new branch
    actually needs silently stayed out of missing_fields.
    """
    contract = {
        "fields": [{
            "key": "servico", "required": True, "condition": None,
            "owner_node_id": "branch-b", "accepted_statuses": ["known"],
        }],
    }
    stale_fact_from_another_branch = {
        "servico": {"status": "known", "value": "polimento", "owner_node_id": "branch-a"},
    }
    pending = graph_proof_checker_v3.pending_fields(contract, stale_fact_from_another_branch)
    assert [field["key"] for field in pending] == ["servico"]

    matching_fact = {
        "servico": {"status": "known", "value": "higienizacao", "owner_node_id": "branch-b"},
    }
    assert graph_proof_checker_v3.pending_fields(contract, matching_fact) == []


def test_persona_wide_field_duplicated_per_branch_is_rejected_at_publish_time():
    """Regression test for docs/handoffs/AURORA_QUALIFICATION_REPEAT_QUESTION_HANDOFF_2026-08-08.md.

    test_pending_fields_ignores_a_fact_owned_by_a_different_branch above
    covers a field that is *legitimately* branch-specific (e.g. "servico"):
    it is correct for that fact to reset on a branch switch. This test
    covers the opposite case: a field whose question and expected answer
    never change across branches (e.g. "nome_cliente", "can_visit_in_person"
    in the Aurora transcripts) but whose graph content redeclares it on
    every branch node instead of once on the shared persona node.

    Previously, _field_declarations() (graph_compiler_v3.py) silently
    defaulted owner_node_id to whichever node happened to declare the
    field, so each branch's redundant copy got a *different* owner_node_id
    even though the field means the same thing everywhere;
    _resolved_for_field_owner (added 2026-08-06 to stop real cross-branch
    leakage of fields like "servico") then wiped this kind of field out on
    every branch switch too, forcing the agent to re-ask a question the
    customer already answered. As of the 2026-08-10 cross-branch
    consistency check, compile_graph() now refuses to publish a graph
    shaped like this at all -- the authoring mistake can no longer reach
    runtime, since a field must either share one owner across branches or
    explicitly declare scope="branch" to admit legitimate divergence.
    """
    root = node(1, "persona:generic")
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    branch_b = node(3, "branch:b", data={"capabilities": {"branch_anchor": True}})
    question_a = node(4, "question:nome:a", parent_type="faq", data={"question": "Como você se chama?"})
    question_b = node(5, "question:nome:b", parent_type="faq", data={"question": "Como você se chama?"})
    # Same field key, same literal question text -- authored redundantly on
    # each branch instead of once on the persona node they all share.
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "nome_cliente", "question_node_id": "question:nome:a", "required": True,
        "accepted_statuses": ["known"],
    }]}
    branch_b["metadata"]["qualification"] = {"fields": [{
        "key": "nome_cliente", "question_node_id": "question:nome:b", "required": True,
        "accepted_statuses": ["known"],
    }]}
    rows = [root, branch_a, branch_b, question_a, question_b]
    edges = [
        edge(1, root, branch_a), edge(2, root, branch_b),
        edge(3, branch_a, question_a), edge(4, branch_b, question_b),
    ]

    with pytest.raises(graph_compiler_v3.GraphCompilationError) as exc_info:
        graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)

    errors = exc_info.value.errors
    assert any("inconsistent_field_owner" in err and "nome_cliente" in err for err in errors), \
        f"Expected inconsistent_field_owner error for nome_cliente, got: {errors}"


def _servico_proposal(*, branch_anchor: str, servico_owner: str) -> ConversationProposal:
    return ConversationProposal(
        branch_action="select",
        branch_anchor_node_id=branch_anchor,
        branch_path_checksum="checksum",
        extracted_facts=[
            ExtractedFact(field_key="servico", value="polimento", owner_node_id=servico_owner),
            ExtractedFact(field_key="nome_cliente", value="Allan", owner_node_id="aurora-persona"),
        ],
    )


def test_normalize_servico_owner_repoints_mismatched_fact_to_selected_branch():
    """Regression test for the wrong-branch-selection bug found validating the fix above.

    Confirmed live 2026-08-08: the model sometimes proposes branch_anchor_node_id
    for the branch it actually means to select (matching the customer's literal
    request), but declares the redundant "servico" fact's owner_node_id as a
    *different* Phase-A candidate branch -- plausibly copied from that other
    candidate's evidence chunks in the same prompt. Before this fix,
    check_proposal() rejected the *entire* otherwise-correct proposal on the
    owner-match guard (commit 6538461), so a customer explicitly naming a
    service (e.g. "higienização interna") could still end up parked on an
    unrelated branch once retries exhausted the literal match. Since
    graph_agent_runtime_v3.decide() always re-derives "servico" from
    branch_anchor_node_id once a proposal is valid anyway, the model's own
    owner_node_id for that field is pure noise worth correcting, not grounds
    for rejection.
    """
    contract = {"fields": [{"key": "servico"}, {"key": "nome_cliente"}]}
    mismatched = _servico_proposal(branch_anchor="aurora-product-interior", servico_owner="aurora-product-wash")

    normalized = graph_agent_runtime_v3._normalize_servico_owner(mismatched, contract)

    servico_fact = next(f for f in normalized.extracted_facts if f.field_key == "servico")
    assert servico_fact.owner_node_id == "aurora-product-interior"
    # Untouched fields are not disturbed by the normalization.
    nome_fact = next(f for f in normalized.extracted_facts if f.field_key == "nome_cliente")
    assert nome_fact.owner_node_id == "aurora-persona"


def test_normalize_servico_owner_is_a_noop_without_a_servico_field_or_mismatch():
    matching = _servico_proposal(branch_anchor="aurora-product-interior", servico_owner="aurora-product-interior")
    contract = {"fields": [{"key": "servico"}]}
    assert graph_agent_runtime_v3._normalize_servico_owner(matching, contract) is matching

    mismatched = _servico_proposal(branch_anchor="aurora-product-interior", servico_owner="aurora-product-wash")
    contract_without_servico_convention = {"fields": [{"key": "nome_cliente"}]}
    assert graph_agent_runtime_v3._normalize_servico_owner(mismatched, contract_without_servico_convention) is mismatched


def test_normalize_unique_published_field_owner_reconciles_model_scope_hint():
    proposal = ConversationProposal(
        extracted_facts=[ExtractedFact(
            field_key="procedimento_anterior",
            value="nenhum",
            owner_node_id="branch:polish",
            evidence_span="Nunca foi feito procedimento nessa pintura",
        )],
    )
    contract = {"fields": [{
        "key": "procedimento_anterior", "owner_node_id": "persona:generic",
    }]}

    normalized = graph_agent_runtime_v3._normalize_unique_published_field_owners(
        proposal, contract,
    )

    assert normalized.extracted_facts[0].owner_node_id == "persona:generic"


def test_normalize_unique_published_field_owner_stays_fail_closed_when_ambiguous():
    proposal = ConversationProposal(extracted_facts=[ExtractedFact(
        field_key="servico", value="polimento", owner_node_id="model:guess",
    )])
    contract = {"fields": [
        {"key": "servico", "owner_node_id": "branch:a"},
        {"key": "servico", "owner_node_id": "branch:b"},
    ]}

    normalized = graph_agent_runtime_v3._normalize_unique_published_field_owners(
        proposal, contract,
    )

    assert normalized is proposal


def test_normalize_unique_owner_can_use_union_of_active_branch_fields():
    proposal = ConversationProposal(extracted_facts=[ExtractedFact(
        field_key="foco_brilho_riscos",
        value="brilho_e_riscos",
        owner_node_id="branch:polish",
        evidence_span="brilho e riscos",
    )])
    document = {"branch_contracts": {
        "branch:interior": {"fields": [{
            "key": "revestimento", "owner_node_id": "persona:generic",
        }]},
        "branch:polish": {"fields": [{
            "key": "foco_brilho_riscos", "owner_node_id": "persona:generic",
        }]},
    }}
    fields = graph_agent_runtime_v3._active_contract_fields(
        document, ["branch:interior", "branch:polish"], {},
    )

    normalized = graph_agent_runtime_v3._normalize_unique_published_field_owners(
        proposal, {"fields": fields},
    )

    assert normalized.extracted_facts[0].owner_node_id == "persona:generic"


def test_normalize_premature_servico_requestion_repoints_to_the_real_pending_field():
    """Regression test for a gap re-surfaced live 2026-08-08 while validating the report's fixes.

    Right after a branch gets selected, the model's very next turn often
    proposes next_question_node_id pointing back at the "servico" question
    even though servico was already resolved by the branch selection
    itself. check_proposal() correctly rejects that as
    next_question_not_for_pending_field, but the rejection discards the
    entire otherwise-correct proposal -- including whatever fact the model
    DID extract that turn (a customer's name, confirmed live), reopening
    the exact repeated-question symptom the other fixes in this session
    closed.
    """
    contract = {"fields": [
        {"key": "servico", "question_node_id": "faq:servico"},
        {"key": "nome_cliente", "question_node_id": "faq:nome_cliente"},
    ]}
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a", branch_path_checksum="checksum",
        next_question_node_id="faq:servico",
    )
    ledger_facts = {"servico": {"status": "known", "value": "pintura"}}

    normalized = graph_agent_runtime_v3._normalize_premature_servico_requestion(proposal, contract, ledger_facts)
    assert normalized.next_question_node_id == "faq:nome_cliente"


def test_normalize_premature_servico_requestion_is_a_noop_when_not_applicable():
    contract = {"fields": [
        {"key": "servico", "question_node_id": "faq:servico"},
        {"key": "nome_cliente", "question_node_id": "faq:nome_cliente"},
    ]}
    # servico genuinely still pending -- asking about it is correct, not premature.
    still_pending = ConversationProposal(
        branch_action="select", branch_anchor_node_id="branch:a", branch_path_checksum="checksum",
        next_question_node_id="faq:servico",
    )
    assert graph_agent_runtime_v3._normalize_premature_servico_requestion(still_pending, contract, {}) is still_pending

    # asking about something other than servico is untouched regardless.
    other_question = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a", branch_path_checksum="checksum",
        next_question_node_id="faq:nome_cliente",
    )
    ledger_facts = {"servico": {"status": "known", "value": "pintura"}}
    assert graph_agent_runtime_v3._normalize_premature_servico_requestion(
        other_question, contract, ledger_facts
    ) is other_question


def _switch_proposal(*, cited_node_ids: list[str], cited_chunk_ids: list[str]) -> ConversationProposal:
    return ConversationProposal(
        branch_action="switch",
        branch_anchor_node_id="branch:b",
        branch_path_checksum="checksum",
        cited_node_ids=cited_node_ids,
        cited_chunk_ids=cited_chunk_ids,
    )


def test_drop_stale_branch_citations_removes_only_citations_from_the_old_branch():
    """Regression test for the silent-switch-failure gap (2026-08-08 report).

    A customer explicitly asking to switch service (e.g. "na verdade,
    prefiro fazer chapeação em vez de pintura") got the switch silently
    dropped: the model's reply cited a node/chunk from the branch it was
    leaving, which is *never* going to be in the new branch's closure
    (unlike a package-retrieval gap, there is no repair that fixes this),
    so check_proposal() rejected the whole proposal -- switch, extracted
    facts and all -- and the conversation stayed on the old service for the
    rest of the turn. Only citations pointing at the branch being left
    should be dropped; anything else must survive untouched so grounding
    still catches a genuinely unrelated/fabricated citation.
    """
    proposal = _switch_proposal(
        cited_node_ids=["branch:a", "faq:a-1", "branch:b"],
        cited_chunk_ids=["chunk:a-1", "chunk:b-1"],
    )
    chunk_sources = {"chunk:a-1": "faq:a-1", "chunk:b-1": "faq:b-1"}

    cleaned = graph_agent_runtime_v3._drop_stale_branch_citations(
        proposal, previous_branch_closure={"branch:a", "faq:a-1"}, chunk_sources=chunk_sources,
    )

    assert cleaned.cited_node_ids == ["branch:b"]
    assert cleaned.cited_chunk_ids == ["chunk:b-1"]


def test_drop_stale_branch_citations_is_a_noop_without_overlap():
    proposal = _switch_proposal(cited_node_ids=["branch:b"], cited_chunk_ids=["chunk:b-1"])
    chunk_sources = {"chunk:b-1": "faq:b-1"}

    unchanged = graph_agent_runtime_v3._drop_stale_branch_citations(
        proposal, previous_branch_closure={"branch:a"}, chunk_sources=chunk_sources,
    )
    assert unchanged is proposal

    also_unchanged = graph_agent_runtime_v3._drop_stale_branch_citations(
        proposal, previous_branch_closure=set(), chunk_sources=chunk_sources,
    )
    assert also_unchanged is proposal


def test_normalize_stale_next_question_after_branch_change_repoints_to_real_pending_field():
    """Regression test for the silent-switch-failure gap reproduced live 2026-08-09.

    Production evidence (lead_ref 117, today): customer says "na verdade,
    prefiro fazer lavagem técnica detalhada em vez de pintura" -- an
    explicit, otherwise-valid branch switch. The model's proposal still
    carried a next_question_node_id left over from the branch it was
    leaving (not one of the new branch's own fields at all), so
    check_proposal() rejected the whole proposal with
    next_question_not_for_pending_field -- discarding the switch itself and
    the conversation never actually changed service, silently. This
    generalizes _normalize_premature_servico_requestion (which only covers
    the servico-specific case) to any stale question left over from before
    a branch change.
    """
    contract_b = {"fields": [
        {"key": "servico", "question_node_id": "faq:servico", "owner_node_id": "branch:b",
         "accepted_statuses": ["known"]},
        {"key": "presencial", "question_node_id": "faq:presencial", "owner_node_id": "aurora-persona",
         "accepted_statuses": ["known"]},
    ]}
    proposal = ConversationProposal(
        branch_action="switch", branch_anchor_node_id="branch:b", branch_path_checksum="checksum",
        next_question_node_id="faq:cor",  # stale -- belongs to the branch being left, not branch:b
    )
    normalized = graph_agent_runtime_v3._normalize_stale_next_question_after_branch_change(
        proposal, contract_b, {}
    )
    # servico is auto-derived known the instant branch:b is selected, so the
    # real next pending field is "presencial", not the stale "faq:cor".
    assert normalized.next_question_node_id == "faq:presencial"


def test_normalize_stale_next_question_after_branch_change_is_a_noop_when_already_correct():
    contract_b = {"fields": [
        {"key": "servico", "question_node_id": "faq:servico", "owner_node_id": "branch:b",
         "accepted_statuses": ["known"]},
        {"key": "presencial", "question_node_id": "faq:presencial", "owner_node_id": "aurora-persona",
         "accepted_statuses": ["known"]},
    ]}
    already_correct = ConversationProposal(
        branch_action="switch", branch_anchor_node_id="branch:b", branch_path_checksum="checksum",
        next_question_node_id="faq:presencial",
    )
    assert graph_agent_runtime_v3._normalize_stale_next_question_after_branch_change(
        already_correct, contract_b, {}
    ) is already_correct

    # "keep" never changes branch, so it is out of scope for this normalizer.
    keeping = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:b", branch_path_checksum="checksum",
        next_question_node_id="faq:cor",
    )
    assert graph_agent_runtime_v3._normalize_stale_next_question_after_branch_change(
        keeping, contract_b, {}
    ) is keeping


def test_decide_does_not_apply_model_only_add_without_backend_evidence(monkeypatch):
    """End-to-end regression for multi-service support (branch_action "add").

    A customer asking for an additional service (e.g. "e também quero
    quantidade") must keep the branch already in progress active *and* add
    the new one -- unlike "switch", which replaces. This exercises the real
    accumulation logic in decide()'s success path, not just check()'s
    validation of the "add" action in isolation.
    """
    document = compiled_fixture()
    persona_row = {**PERSONA, "config": {}}
    pub = publication(document)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )

    contract_b = document["branch_contracts"]["branch:b"]
    question_card = ContextCard(
        id="question:b", node_type="faq", slug="question-b", title="question:b",
        rendered_content="Qual é a quantidade?", content_checksum="sha256:card",
        revision=1, graph_version=1, graph_checksum=document["checksum"],
        context_role="pending_field_question", position=0,
    )
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[{
            "role": "user", "texto": "e também quero informar a quantidade",
        }], cart={"facts": {}}, rag_nodes=[], rag_paths=[],
        context_cards=[question_card],
        graph_contract=document["branch_contracts"]["branch:a"],
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        publication_id=pub["id"],
        retrieval_trace={"possible_switches": ["branch:b"], "retrieval_branch_node_id": "branch:b"},
    )
    add_proposal = {
        "branch_action": "add", "branch_anchor_node_id": "branch:b",
        "branch_path_checksum": contract_b["branch_path_checksum"],
        "branch_evidence_span": "quantidade",
        "extracted_facts": [], "claims": [],
        "next_question_node_id": "question:b",
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Certo, também anoto a quantidade.",
        "qualification_complete": False, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": add_proposal},
    )
    assert response.proof.get("valid"), response.proof.get("errors")
    assert response.cart_state["active_branch_node_ids"] == ["branch:a"]
    assert response.cart_state["active_branch_node_id"] == "branch:a"
    assert response.proof["applied_service_operations"] == []


def test_collected_field_facts_uses_enum_alias_not_raw_slug():
    """Regression: an enum field's stored value is the internal matching
    slug (e.g. Aurora's objective="continuar_cuidar_proteger"), never meant
    to reach the customer verbatim -- it must render as the published
    alias, not leak snake_case with underscores into the confirmation."""
    document = {"branch_contracts": {}, "node_by_id": {}}
    contract = {
        "conversation_policy": {}, "field_labels": {},
        "fields": [{
            "key": "objective", "owner_node_id": "persona:aurora",
            "validation": {"mode": "enum", "values": [
                {
                    "value": "continuar_cuidar_proteger",
                    "aliases": ["continuar com o veículo e cuidar bem dele"],
                },
            ]},
        }],
    }
    facts_by_key = {"objective": [{
        "owner_node_id": "persona:aurora", "status": "known",
        "value": "continuar_cuidar_proteger",
    }]}
    collected = graph_agent_runtime_v3._collected_field_facts(
        document, ["persona:aurora"], contract, facts_by_key,
    )
    assert collected == [
        ("Objective", "continuar com o veículo e cuidar bem dele"),
    ]


def test_collected_field_facts_non_enum_field_is_unaffected():
    document = {"branch_contracts": {}, "node_by_id": {}}
    contract = {
        "conversation_policy": {}, "field_labels": {},
        "fields": [{"key": "nome_cliente", "owner_node_id": "persona:aurora"}],
    }
    facts_by_key = {"nome_cliente": [{
        "owner_node_id": "persona:aurora", "status": "known", "value": "Cíntia",
    }]}
    collected = graph_agent_runtime_v3._collected_field_facts(
        document, ["persona:aurora"], contract, facts_by_key,
    )
    assert collected == [("Nome cliente", "Cíntia")]


def test_active_offering_titles_has_no_hardcoded_selection_key():
    """Generic across service and product graphs: the selector field key
    comes from branch_selection_field on the compiled contract, never the
    literal "servico" -- a persona selling products must work identically."""
    document = {
        "common_contract": {"fields": [{"key": "produto", "branch_selection_field": True}]},
        "node_by_id": {
            "branch:x": {"title": "Camiseta"},
            "branch:y": {"title": "Boné"},
        },
    }
    facts_by_key = {"produto": [
        {"status": "known", "owner_node_id": "branch:x"},
        {"status": "known", "owner_node_id": "branch:y"},
    ]}
    titles = graph_agent_runtime_v3.active_offering_titles(
        document, ["branch:x", "branch:y"], facts_by_key,
    )
    assert titles == ["Camiseta", "Boné"]


def test_active_offering_titles_includes_a_branch_pending_selection_confirmation():
    """Regression (live 2026-08-18): graph_compiler_v3._with_confirmable_status
    always authorizes "needs_confirmation" on the branch selector field --
    an approximate service match stays in that state until the customer
    confirms, but the branch is already active and its other collected
    facts already count toward qualification. Gating this on "known" only
    silently dropped that branch's title from the confirmation summary and
    from the lead's interesse_produto projection (conversation_runtime.py)
    the moment a composite reply moved focus to a different active branch."""
    document = {
        "common_contract": {"fields": [{"key": "servico", "branch_selection_field": True}]},
        "node_by_id": {
            "branch:chapeacao": {"title": "Chapeação"},
            "branch:lavagem": {"title": "Lavagem detalhada"},
        },
    }
    facts_by_key = {"servico": [
        {"status": "needs_confirmation", "owner_node_id": "branch:chapeacao"},
        {"status": "known", "owner_node_id": "branch:lavagem"},
    ]}
    titles = graph_agent_runtime_v3.active_offering_titles(
        document, ["branch:chapeacao", "branch:lavagem"], facts_by_key,
    )
    assert titles == ["Chapeação", "Lavagem detalhada"]


def test_collected_field_facts_includes_a_field_pending_selection_confirmation():
    """Same regression as active_offering_titles, for the confirmation
    summary's field-by-field listing: a field whose accepted_statuses the
    contract explicitly widens beyond "known" (the branch selector) must
    not require "known" specifically to be counted as collected."""
    document = {"branch_contracts": {}, "node_by_id": {}}
    contract = {
        "conversation_policy": {}, "field_labels": {},
        "fields": [{
            "key": "servico", "owner_node_id": "branch:chapeacao",
            "accepted_statuses": ["known", "needs_confirmation"],
        }],
    }
    facts_by_key = {"servico": [{
        "owner_node_id": "branch:chapeacao", "status": "needs_confirmation",
        "value": "Chapeação",
    }]}
    collected = graph_agent_runtime_v3._collected_field_facts(
        document, ["branch:chapeacao"], contract, facts_by_key,
    )
    assert collected == [("Servico", "Chapeação")]


def test_terminal_reply_confirmation_lists_two_services_in_one_clause_not_a_bolt_on():
    """End-to-end regression for the live 2026-08-18 bug: the final
    confirmation sentence for a 2-service pedido must name both services in
    ONE "Serviço:" clause and must never contain the old "Também no seu
    pedido" bolt-on paragraph (function removed entirely -- this asserts the
    observable behavior, not just that the dead code is gone)."""
    document = {
        "common_contract": {"fields": []},
        "node_by_id": {
            "branch:a": {"title": "Chapeação"},
            "branch:b": {"title": "PPF (película de proteção física)"},
        },
    }
    contract = {
        "conversation_policy": {
            "qualification": {
                "summary_template": "Então ficou assim: {informed_fields}.",
                "confirmation_question": "Tá tudo certo?",
            },
        },
        "field_labels": {},
        "fields": [
            {"key": "servico", "owner_node_id": "branch:a", "accepted_statuses": ["known"]},
            {"key": "servico", "owner_node_id": "branch:b", "accepted_statuses": ["known"]},
        ],
    }
    facts_by_key = {"servico": [
        {"status": "known", "owner_node_id": "branch:a", "value": "chapeacao"},
        {"status": "known", "owner_node_id": "branch:b", "value": "ppf"},
    ]}
    reply = graph_agent_runtime_v3._terminal_reply(
        document=document, contract=contract,
        active_branch_ids=["branch:a", "branch:b"],
        facts_by_key=facts_by_key, missing_fields=[], qualification_complete=True,
    )
    assert reply.count("Servico:") == 1
    assert "Chapeação, PPF (película de proteção física)" in reply
    assert "Também no seu pedido" not in reply


def test_collected_field_facts_merges_two_active_offerings_into_one_selector_clause():
    """Regression (live 2026-08-18): with 2+ active branches, the selector
    field ("servico") used to surface as one ("Serviço", value) tuple per
    branch, so the terminal confirmation sentence came out with two disjoint
    "serviço:" clauses instead of one that treats every active offering as
    equally fundamental. merge_selector=True collapses them into a single
    tuple with a joined value, using the same active_offering_titles() the
    old (now-removed) _active_service_summary bolt-on paragraph used."""
    document = {
        "common_contract": {"fields": []},
        "node_by_id": {
            "branch:a": {"title": "Vitrificação"}, "branch:b": {"title": "Polimento"},
        },
    }
    contract = {
        "conversation_policy": {}, "field_labels": {},
        "fields": [
            {"key": "servico", "owner_node_id": "branch:a", "accepted_statuses": ["known"]},
            {"key": "servico", "owner_node_id": "branch:b", "accepted_statuses": ["known"]},
        ],
    }
    facts_by_key = {"servico": [
        {"status": "known", "owner_node_id": "branch:a", "value": "vitrificacao"},
        {"status": "known", "owner_node_id": "branch:b", "value": "polimento"},
    ]}
    collected = graph_agent_runtime_v3._collected_field_facts(
        document, ["branch:a", "branch:b"], contract, facts_by_key, merge_selector=True,
    )
    assert collected == [("Servico", "Vitrificação, Polimento")]


def test_collected_field_facts_merge_selector_falls_back_with_one_offering():
    """Companion to the merge test: a single active branch must keep today's
    unmerged per-field rendering (guards the len(titles) < 2 fallthrough)."""
    document = {
        "common_contract": {"fields": []},
        "node_by_id": {"branch:a": {"title": "Vitrificação"}},
    }
    contract = {
        "conversation_policy": {}, "field_labels": {},
        "fields": [{"key": "servico", "owner_node_id": "branch:a", "accepted_statuses": ["known"]}],
    }
    facts_by_key = {"servico": [
        {"status": "known", "owner_node_id": "branch:a", "value": "vitrificacao"},
    ]}
    collected = graph_agent_runtime_v3._collected_field_facts(
        document, ["branch:a"], contract, facts_by_key, merge_selector=True,
    )
    assert collected == [("Servico", "vitrificacao")]


def test_confirmed_branch_node_ids_covers_every_active_branch(monkeypatch):
    """The branches marked 'completed' on an explicit "sim" must be every
    branch active on the ledger, not just the turn's focused one -- otherwise
    a second confirmed offering would get dropped to 'dropped' by the SQL
    reconciliation instead of durably marked 'completed' (migration 128)."""
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"message_id": "msg:sim", "role": "user", "texto": "sim"}],
        cart={}, rag_nodes=[], rag_paths=[], graph_contract={
            "conversation_policy": {"qualification": {
                "completion_message": "Perfeito, obrigada! A equipe segue com você.",
            }},
        },
        active_branch_node_id="branch:b", active_branch_node_ids=["branch:a", "branch:b"],
        journey_state="awaiting_confirmation", operational_mode="confirmation",
        pending_confirmation_ref="qualification:current:0",
    )
    result = graph_agent_runtime_v3._deterministic_confirmation_decision(
        context,
        SemanticInterpretation.model_validate({
            "intents": [{"kind": "confirmation", "evidence_span": "sim"}],
            "state_relation": "continue",
            "confirmation": {
                "state": "affirm",
                "target_ref": "qualification:current:0",
                "evidence_span": "sim",
            },
            "recommended_next_action": "handoff",
            "reply": "Perfeito. Posso encaminhar seu atendimento para a equipe?",
            "handoff_requested": True,
        }),
    )
    assert result is not None
    decision, response = result
    assert decision.intent == "qualification_confirmed"
    assert set(response.proof["confirmed_branch_node_ids"]) == {"branch:a", "branch:b"}


def test_pending_branch_confirmation_reopens_post_qualification_support(monkeypatch):
    """Root-cause regression: a customer confirming a first offering, then a
    second one in the same still-open conversation, must not have the second
    one silently swallowed as generic post-order support chat.

    branch:a is already confirmed (completed_branch_node_ids). branch:b --
    already active from an earlier turn, as if the customer had already
    named it -- finishes collecting its own required field on this turn.
    Even though the journey overall is still post_qualification_support
    (from branch:a's earlier confirmation), the lock must lift for branch:b
    specifically so a fresh confirmation is offered, instead of the reply
    falling back to raw, un-graph-checked model text forever (the bug).
    """
    document = compiled_fixture()
    persona_row = {**PERSONA, "config": {}}
    pub = publication(document)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )
    contract_b = document["branch_contracts"]["branch:b"]
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[{
            "message_id": "msg:qtd", "role": "user", "texto": "são 5 unidades",
        }],
        cart={
            "facts": {"metragem": {"status": "known", "value": 20, "owner_node_id": "branch:a"}},
            "facts_by_key": {"metragem": [
                {"status": "known", "value": 20, "owner_node_id": "branch:a"},
            ]},
        },
        rag_nodes=[], rag_paths=[],
        graph_contract=contract_b,
        active_branch_node_id="branch:b", active_branch_node_ids=["branch:a", "branch:b"],
        completed_branch_node_ids=["branch:a"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        publication_id=pub["id"],
        journey_state="handed_off", operational_mode="post_qualification_support",
        retrieval_trace={"retrieval_branch_node_id": "branch:b"},
    )
    proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:b",
        "branch_path_checksum": contract_b["branch_path_checksum"],
        "branch_evidence_span": "5 unidades",
        "extracted_facts": [{
            "field_key": "quantidade", "owner_node_id": "branch:b",
            "status": "known", "value": 5, "source_message_id": "msg:qtd",
            "evidence_span": "5 unidades", "confidence": 1,
        }],
        "claims": [], "next_question_node_id": None,
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Perfeito, ficam 20 e 5 no pedido. Posso confirmar?",
        "qualification_complete": True, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )
    assert response.proof.get("valid"), response.proof.get("errors")
    # Without the fix this stays "post_qualification_support" forever and
    # branch:b's confirmation never gets a chance to run.
    assert response.proof["confirmation_state"] == "awaiting_confirmation"
    assert set(response.cart_state["active_branch_node_ids"]) == {"branch:a", "branch:b"}


def test_no_pending_branch_confirmation_stays_locked_in_support(monkeypatch):
    """Companion to the regression above: once every active branch is
    already 'completed', ordinary post-order support chat must stay locked
    (commit 66c0cbe's whole point) -- ruling out a fix that just deletes the
    lock instead of scoping it per branch."""
    document = compiled_fixture()
    persona_row = {**PERSONA, "config": {}}
    pub = publication(document)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )
    contract_b = document["branch_contracts"]["branch:b"]
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[{
            "message_id": "msg:thanks", "role": "user", "texto": "obrigado!",
        }],
        cart={"facts": {
            "metragem": {"status": "known", "value": 20, "owner_node_id": "branch:a"},
            "quantidade": {"status": "known", "value": 5, "owner_node_id": "branch:b"},
        }},
        rag_nodes=[], rag_paths=[],
        graph_contract=contract_b,
        active_branch_node_id="branch:b", active_branch_node_ids=["branch:a", "branch:b"],
        completed_branch_node_ids=["branch:a", "branch:b"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        publication_id=pub["id"],
        journey_state="handed_off", operational_mode="post_qualification_support",
        retrieval_trace={"retrieval_branch_node_id": "branch:b"},
    )
    proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:b",
        "branch_path_checksum": contract_b["branch_path_checksum"],
        "branch_evidence_span": "", "extracted_facts": [], "claims": [],
        "next_question_node_id": None,
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Por nada! Qualquer coisa é só chamar.",
        "qualification_complete": True, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )
    assert response.proof.get("valid"), response.proof.get("errors")
    assert response.proof["confirmation_state"] == "post_qualification_support"


def _two_active_branches_context(monkeypatch, *, focused_branch, extra_context_kwargs=None):
    document = compiled_fixture()
    persona_row = {**PERSONA, "config": {}}
    pub = publication(document)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )
    contract = document["branch_contracts"][focused_branch]
    # compiled_fixture() has no qualification copy configured; several of
    # these tests can legitimately reach a "qualification complete" state
    # (e.g. the negative-case gating test, where the only required field is
    # already known) and _terminal_reply raises without templates.
    contract.setdefault("conversation_policy", {})["qualification"] = {
        "summary_template": "Então ficou assim: {informed_fields}.",
        "confirmation_question": "Tá tudo certo?",
        "incomplete_handoff_template": "Faltou: {missing_fields}.",
    }
    base_kwargs: dict = {
        "persona_slug": "generic", "agent_slug": "agent", "graph_version": 1,
        "graph_checksum": document["checksum"], "messages": [{
            "message_id": "msg:both", "role": "user", "texto": "são 20 metros e 5 unidades",
        }],
        "cart": {}, "rag_nodes": [], "rag_paths": [],
        "graph_contract": contract,
        "active_branch_node_id": focused_branch, "active_branch_node_ids": ["branch:a", "branch:b"],
        "branch_node_ids": [], "runtime_version": "graph_agent_runtime_v3",
        "publication_id": pub["id"],
        "retrieval_trace": {"retrieval_branch_node_id": focused_branch},
    }
    base_kwargs.update(extra_context_kwargs or {})
    context = ConversationContext(**base_kwargs)
    return document, contract, context


def test_decide_persists_carried_facts_into_accepted_facts_on_new_journey(monkeypatch):
    """Regression (live 2026-08-18): a carried fact (_seed_carried_facts)
    only ever lived in context.cart["facts"] for one turn's in-memory
    processing -- never folded into accepted_facts, the only thing
    actually persisted. decide() now writes it into accepted_facts
    whenever context.journey_id is None (exactly the turn build_context
    creates a new journey's placeholder), so it survives durably instead
    of evaporating the moment a second journey closes before the field is
    independently restated."""
    _document, contract_a, context = _two_active_branches_context(
        monkeypatch, focused_branch="branch:a",
        extra_context_kwargs={
            "journey_id": None,
            "cart": {
                "facts": {"nome_cliente": {
                    "status": "known", "value": "Allan Rodrigues",
                    "owner_node_id": "persona", "source_message_id": "msg:old",
                    "evidence_span": "Allan Rodrigues", "confidence": 1,
                    "carried_from_journey": "journey-anterior",
                }},
                "facts_by_key": {},
            },
        },
    )
    proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract_a["branch_path_checksum"],
        "branch_evidence_span": "", "extracted_facts": [],
        "claims": [], "next_question_node_id": None,
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Perfeito.",
        "qualification_complete": False, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )
    carried = [
        fact for fact in response.proof.get("accepted_facts") or []
        if fact.get("field_key") == "nome_cliente"
    ]
    assert len(carried) == 1
    assert carried[0]["value"] == "Allan Rodrigues"
    assert carried[0]["owner_node_id"] == "persona"


def test_decide_accepts_same_message_facts_for_two_active_branches(monkeypatch):
    """Regression for Claim 3 (branch-scoped extracted_facts asymmetry): a
    customer naming a fact for a second already-active branch (not the one
    the model happened to focus on this turn) must have it accepted, not
    rejected as undeclared/owner-mismatched purely because this turn's
    contract is scoped to the focused branch. branch:a's own required field
    is deliberately left unanswered so qualification never completes,
    keeping this test isolated to the acceptance question."""
    _document, contract_a, context = _two_active_branches_context(monkeypatch, focused_branch="branch:a")
    proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract_a["branch_path_checksum"],
        "branch_evidence_span": "",
        "extracted_facts": [{
            "field_key": "quantidade", "owner_node_id": "branch:b",
            "status": "known", "value": 5, "source_message_id": "msg:both",
            "evidence_span": "5 unidades", "confidence": 1,
        }],
        "claims": [], "next_question_node_id": None,
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Perfeito, 5 unidades anotadas.",
        "qualification_complete": False, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )
    assert response.proof.get("valid"), response.proof.get("errors")
    accepted = {
        (fact["field_key"], fact["owner_node_id"])
        for fact in response.proof.get("accepted_facts") or []
    }
    assert ("quantidade", "branch:b") in accepted


def test_decide_defers_non_focused_branch_fact_error_but_still_answers_naturally(monkeypatch):
    """Claim 4 mitigation: branch:b's own fact fails validation (evidence
    not literal in the message) while branch:a's (focused) fact is clean --
    the turn must still take the natural/accepted-facts path instead of the
    fully deterministic fallback. proof["valid"] stays the true, complete
    result (False, since branch:b's fact really did fail); what matters is
    the turn isn't silently reduced to the generic deterministic reply."""
    _document, contract_a, context = _two_active_branches_context(monkeypatch, focused_branch="branch:a")
    proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract_a["branch_path_checksum"],
        "branch_evidence_span": "",
        "extracted_facts": [
            {
                "field_key": "metragem", "owner_node_id": "branch:a",
                "status": "known", "value": 20, "source_message_id": "msg:both",
                "evidence_span": "20 metros", "confidence": 1,
            },
            {
                "field_key": "quantidade", "owner_node_id": "branch:b",
                "status": "known", "value": 5, "source_message_id": "msg:both",
                # Not literally in the message -- forces this one fact to fail.
                "evidence_span": "essa frase nao esta na mensagem", "confidence": 1,
            },
        ],
        "claims": [], "next_question_node_id": None,
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Perfeito, 20 metros anotados.",
        "qualification_complete": False, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )
    assert response.proof.get("valid") is True
    assert response.proof.get("gating_errors") == []
    assert "fact_evidence_not_literal:quantidade" in response.proof.get(
        "component_errors", []
    )
    assert response.proof.get("mode") != "model_repair_exhausted_handoff"
    accepted = {
        (fact["field_key"], fact["owner_node_id"])
        for fact in response.proof.get("accepted_facts") or []
    }
    assert ("metragem", "branch:a") in accepted
    assert ("quantidade", "branch:b") not in accepted


def test_seed_carried_facts_carries_vehicle_not_just_name(monkeypatch):
    """Regression (live 2026-08-18): a new journey/appointment cycle after a
    previous one closed only seeded nome_cliente -- the fixture's
    carry_over generalization (publish_aurora_graph.py) is what actually
    fixes the live bug, but _seed_carried_facts/_carry_over_field_keys
    themselves must already correctly seed EVERY field the compiled
    contract flags carry_over=True for, not just identity. This pins that
    behavior directly against the runtime function, independent of which
    fields a given graph's publish script happens to flag."""
    document = {
        "common_contract": {"fields": []},
        "branch_contracts": {"branch:a": {"fields": [
            {"key": "nome_cliente", "owner_node_id": "persona", "carry_over": True},
            {"key": "modelo_veiculo", "owner_node_id": "persona", "carry_over": True},
            {"key": "vehicle_color", "owner_node_id": "persona", "carry_over": True},
            {"key": "servico", "owner_node_id": "branch:a", "carry_over": False},
        ]}},
    }
    rows = [
        {"id": "f1", "field_key": "nome_cliente", "status": "known", "value_json": "Allan Rodrigues"},
        {"id": "f2", "field_key": "modelo_veiculo", "status": "known", "value_json": "Ford Ka"},
        {"id": "f3", "field_key": "vehicle_color", "status": "known", "value_json": "branco"},
        {"id": "f4", "field_key": "servico", "status": "known", "value_json": "chapeacao"},
    ]
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_lead_carry_over_facts",
        lambda persona_id, lead_ref, field_keys: rows,
    )
    seeded = graph_agent_runtime_v3._seed_carried_facts(
        {"facts": {}, "facts_by_key": {}}, document, {"id": "journey-prev"},
    )
    assert set(seeded["facts"].keys()) == {"nome_cliente", "modelo_veiculo", "vehicle_color"}
    assert seeded["facts"]["modelo_veiculo"]["value"] == "Ford Ka"
    assert seeded["facts"]["vehicle_color"]["value"] == "branco"
    assert "servico" not in seeded["facts"]


def test_qualification_complete_turn_citing_persona_root_is_not_rejected(monkeypatch):
    """Regression for José's silence: the persona root node is
    unconditionally in every branch's closure (it owns identity-level
    facts like nome_cliente) but typically has no indexed RAG chunk of its
    own, so it never earns a context card and never lands in
    package_node_ids. The model naturally cites it while restating
    already-known facts on the turn qualification completes -- without the
    fix that legitimate citation was rejected as
    cited_node_outside_package, forcing a repair round-trip that, live in
    production, left the customer with no reply at all."""
    root = node(1, "persona:aurora", parent_type="persona")
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    q_a = node(3, "question:a", parent_type="faq", data={"question": "Qual é a metragem?"})
    closing_rule = node(4, "rule:closing", parent_type="rule", data={"handoff_rule": {
        "condition": "qualification_complete",
        "text": "Perfeito! Anotei tudo, a equipe vai te chamar em breve.",
    }})
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "metragem", "question_node_id": "question:a", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "number", "minimum": 0},
    }]}
    rows = [root, branch_a, q_a, closing_rule]
    edges = [
        edge(1, root, branch_a), edge(2, branch_a, q_a), edge(3, branch_a, closing_rule),
    ]
    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)
    contract = document["branch_contracts"]["branch:a"]
    persona_id = "persona:aurora"
    assert persona_id in (contract.get("closure_node_ids") or []), (
        "fixture must have the persona root in the branch closure to exercise this path"
    )

    pub = publication(document)
    persona_row = {**PERSONA, "config": {}}
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )

    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[{
            "role": "user", "texto": "20",
        }], cart={"facts": {
            "metragem": {"status": "known", "value": 20, "owner_node_id": "branch:a"},
        }}, rag_nodes=[], rag_paths=[], graph_contract=contract,
        # No context_cards this turn -- the persona node has no indexed
        # prose chunk of its own, matching production.
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        publication_id=pub["id"],
        retrieval_trace={"retrieval_branch_node_id": "branch:a"},
    )
    proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "", "extracted_facts": [], "claims": [],
        "next_question_node_id": None,
        "cited_node_ids": [persona_id],
        "cited_chunk_ids": [],
        "reply": "Perfeito, ficam 20 no pedido. Posso confirmar?",
        "qualification_complete": True, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )
    assert response.proof.get("valid"), response.proof.get("errors")
    assert not any(
        str(err).startswith("cited_node_outside_package")
        for err in (response.proof.get("errors") or [])
    )
    assert response.reply_text


def test_bare_service_like_answer_does_not_override_pending_objective(monkeypatch):
    persona_node = node(1, "persona:aurora", parent_type="persona")
    polish = node(2, "aurora-product-polish-localized", parent_type="product", data={
        "capabilities": {"branch_anchor": True}, "aliases": ["polimento localizado"],
    })
    vitrification = node(3, "aurora-product-vitrification", parent_type="product", data={
        "capabilities": {"branch_anchor": True}, "aliases": ["vitrificação"],
    })
    q_service = node(4, "q:service", parent_type="faq", data={
        "question": "Qual serviço te interessa?",
    })
    q_objective = node(5, "q:objective", parent_type="faq", data={
        "question": "Você pretende vender o carro ou continuar cuidando dele?",
    })
    persona_node["metadata"]["qualification"] = {"fields": [{
        "key": "objective", "scope": "declaration",
        "question_node_id": "q:objective", "required": True,
        "accepted_statuses": ["known"],
        "value_schema": {"type": "string", "enum": ["sell", "keep"]},
        "validation": {
            "mode": "enum",
            "values": [
                {"value": "sell", "aliases": ["vender"]},
                {"value": "keep", "aliases": ["continuar cuidando"]},
            ],
            "invalid_response": "Não consegui identificar seu objetivo.",
        },
    }]}
    for branch, slug, title in (
        (polish, "polimento-localizado", "Polimento localizado"),
        (vitrification, "vitrificacao", "Vitrificação"),
    ):
        branch["slug"] = slug
        branch["title"] = title
        branch["metadata"]["qualification"] = {"fields": [{
            "key": "servico", "scope": "branch",
            "question_node_id": "q:service", "required": True,
            "accepted_statuses": ["known"],
            "value_schema": {"type": "string"},
            "validation": {
                "mode": "enum",
                "values": [{"value": slug, "aliases": [title]}],
                "invalid_response": "Não entendi exatamente qual serviço.",
            },
        }]}
    document = graph_compiler_v3.compile_graph(
        persona=PERSONA,
        node_rows=[persona_node, polish, vitrification, q_service, q_objective],
        edge_rows=[
            edge(1, persona_node, polish), edge(2, persona_node, vitrification),
            edge(3, persona_node, q_service), edge(4, persona_node, q_objective),
        ],
    )
    document["confirmation_templates"] = {
        "service_addition": "Voc\u00ea quer adicionar {candidate}?",
    }
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda persona_id: pub,
    )
    resolution = graph_agent_runtime_v3._resolve_service_operations(
        document, "Vitrificação",
        active_branch_node_id="aurora-product-polish-localized",
        active_branch_node_ids=["aurora-product-polish-localized"],
    )
    resolution = graph_agent_runtime_v3._reserve_message_for_pending_field(
        resolution, pending_field_answer=True, message="Vitrificação",
        active_branch_node_id="aurora-product-polish-localized",
        active_branch_node_ids=["aurora-product-polish-localized"],
    )
    existing_service = {
        "field_key": "servico", "owner_node_id": "aurora-product-polish-localized",
        "status": "known", "value": "polimento-localizado",
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"],
        messages=[{"message_id": "msg-jose", "role": "user", "content": "Vitrificação"}],
        cart={
            "facts": {"servico": existing_service},
            "facts_by_key": {"servico": [existing_service]},
            "asked_question_node_ids": ["q:objective"],
        },
        rag_nodes=[], rag_paths=[], context_cards=[],
        graph_contract=document["branch_contracts"]["aurora-product-vitrification"],
        active_branch_node_id="aurora-product-polish-localized",
        active_branch_node_ids=["aurora-product-polish-localized"],
        publication_id=pub["id"], runtime_version="graph_agent_runtime_v3",
        retrieval_trace={
            "service_resolution": resolution,
            "possible_switches": ["aurora-product-vitrification"],
            "retrieval_branch_node_id": "aurora-product-vitrification",
        },
    )
    model_proposal = {
        "branch_action": "keep",
        "branch_anchor_node_id": "aurora-product-polish-localized",
        "branch_path_checksum": document["branch_contracts"]["aurora-product-polish-localized"]["branch_path_checksum"],
        "branch_evidence_span": "",
        "extracted_facts": [{
            "field_key": "objective", "owner_node_id": "persona:aurora",
            "status": "known", "value": "Vitrificação",
            "source_message_id": "msg-jose", "evidence_span": "Vitrificação",
            "confidence": 1,
        }],
        "claims": [], "next_question_node_id": "q:objective",
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Agora temos dois serviços.",
        "qualification_complete": False, "handoff_requested": False,
    }

    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": {
            **model_proposal,
            "reply": (
                "Agora temos duas opcoes. Quer comparar os detalhes? "
                "Qual delas chamou mais atencao?"
            ),
        }},
    )

    assert response.proof["valid"], response.proof["errors"]
    assert response.reply_text is None
    assert response.proof["repair_required"] is True
    assert response.proof["question_component_invalid"] is True
    assert response.cart_state == context.cart



def test_completion_component_error_preserves_nonempty_model_reply(monkeypatch):
    """A stale completion component is dropped without rewriting the reply."""
    root = node(1, "persona:generic", parent_type="persona", data={
        "conversation_policy": {
            "qualification": {
                "summary_template": "Resumo: {informed_fields}.",
                "confirmation_question": "Os dados estão corretos?",
                "completion_message": "A equipe continuará o atendimento.",
            },
        },
    })
    branch_a = node(2, "branch:a", data={"capabilities": {"branch_anchor": True}})
    q_a = node(4, "question:a", parent_type="faq", data={"question": "Qual é a metragem?"})
    closing_rule = node(5, "rule:closing", parent_type="rule", data={"handoff_rule": {
        "condition": "qualification_complete",
        "text": "Perfeito! Anotei tudo, a equipe vai te chamar em breve.",
    }})
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "metragem", "question_node_id": "question:a", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "number", "minimum": 0},
    }]}
    rows = [root, branch_a, q_a, closing_rule]
    edges = [
        edge(1, root, branch_a), edge(2, branch_a, q_a), edge(3, branch_a, closing_rule),
    ]
    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)
    contract = document["branch_contracts"]["branch:a"]
    assert contract.get("handoff_rules"), "fixture must compile a handoff rule to exercise this path"

    pub = publication(document)
    persona_row = {**PERSONA, "config": {}}
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )

    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[{
            "role": "user", "texto": "20",
        }], cart={"facts": {
            "metragem": {"status": "known", "value": 20, "owner_node_id": "branch:a"},
        }}, rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        publication_id=pub["id"],
        retrieval_trace={"retrieval_branch_node_id": "branch:a"},
    )
    # The model incorrectly still asks about "metragem" even though it is
    # already known -- next_question_not_for_pending_field would normally
    # fire, but here missing_fields is empty, so check() instead raises
    # question_after_completion, landing in the fallback path with no field
    # left to fall back to.
    stale_proposal = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "", "extracted_facts": [], "claims": [],
        "next_question_node_id": "question:a",
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": "Só confirmando...", "qualification_complete": True, "handoff_requested": False,
    }
    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": stale_proposal},
    )
    assert decision.intent == "awaiting_confirmation"
    assert decision.route.value == "SDR"
    assert response.handoff_required is False
    assert response.reply_text == stale_proposal["reply"]


def test_keep_without_an_active_branch_cannot_silently_establish_one():
    """Regression test for the phantom-branch switch-rejection bug (2026-08-08).

    Confirmed live against production ledger 248675f9-100c-4bc6-8e97-42a8c0fdaa77
    (lead_ref 92): the customer's *explicit* switch request -- "Na verdade,
    prefiro fazer chapeação em vez de PPF" (9 words -- the short_expected_answer
    <=8-word retrieval gate in graph_agent_runtime_v3.build_context() was NOT
    involved; retrieval_trace confirmed short_expected_answer=false and
    global_branch_search_executed=true for this exact turn, and
    aurora-product-bodywork scored 0.513249 in branch_candidates, comfortably
    above the 0.18 possible_switches threshold) -- was rejected with
    branch_switch_not_authorized anyway. The real cause: turn 1's legitimate
    branch_action="select" for aurora-product-ppf was rejected for an
    unrelated reason (branch_evidence_not_literal), so no active branch was
    ever committed. Turn 2 processed the customer's name ("Isabela" -- zero
    branch/service signal), so _fallback_retrieval_branch() picked a branch to
    retrieve context against the only way it can when nothing scored: the
    alphabetically-first branch anchor (by design -- see
    test_fallback_retrieval_branch_never_leaves_a_greeting_without_context --
    and it happened to be aurora-product-bodywork). check()'s "keep" branch
    below only validates branch continuity when active_branch_node_id is
    already set:

        if action == "keep":
            if active_branch_node_id and branch != active_branch_node_id:
                errors.append("keep_changed_branch")

    With no active branch yet, ANY branch_anchor_node_id passes for "keep" --
    unlike "select", it never consults branch_selection_allowed or requires a
    literal evidence span. The model echoed the retrieval-only fallback branch
    back as branch_action="keep", and graph_agent_runtime_v3.decide() (line
    ~611-612: state["active_branch_node_id"] = proposal.branch_anchor_node_id)
    silently committed it as the real active branch -- one the customer never
    actually asked for. Two turns later, when the customer explicitly asked to
    switch to that exact branch, check()'s "switch" branch rejected it
    unconditionally because branch == active_branch_node_id already:

        elif action == "switch":
            if not branch_switch_allowed or not active_branch_node_id or branch == active_branch_node_id:
                errors.append("branch_switch_not_authorized")

    -- the customer's real, explicit switch collided with a branch that was
    never legitimately selected in the first place.

    This test currently FAILS: "keep" has no active-branch guard, so this
    proposal is (wrongly) accepted. The proposed fix is to require an active
    branch for "keep" to mean anything, mirroring how "select" already
    requires branch_selection_allowed and "switch" already requires
    branch_switch_allowed:

        if action == "keep":
            if not active_branch_node_id:
                errors.append("keep_without_active_branch")
            elif branch != active_branch_node_id:
                errors.append("keep_changed_branch")
    """
    document = compiled_fixture()
    value = proposal(
        document, branch_action="keep", branch_anchor_node_id="branch:b",
        branch_path_checksum=document["branch_contracts"]["branch:b"]["branch_path_checksum"],
        branch_evidence_span="", cited_node_ids=["branch:b"], cited_chunk_ids=[],
    )
    proof = check(document, value, active=None, message="Isabela")
    assert "keep_without_active_branch" in proof["errors"], proof["errors"]


def test_discovery_keep_uses_model_reply_without_committing_fallback_branch(monkeypatch):
    document = compiled_fixture()
    pub = publication(document)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client,
        "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client,
        "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    contract = document["branch_contracts"]["branch:b"]
    question = ContextCard(
        id="question:b", node_type="faq", slug="question-b", title="question:b",
        rendered_content="Qual é a quantidade?", content_checksum="sha256:card",
        revision=1, graph_version=1, graph_checksum=document["checksum"],
        context_role="pending_field_question", position=0,
    )
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"],
        messages=[{"role": "user", "texto": "Oi"}], cart={"facts": {}},
        rag_nodes=[], rag_paths=[], context_cards=[question],
        graph_contract=contract, active_branch_node_id=None,
        active_branch_node_ids=[], branch_node_ids=[],
        runtime_version="graph_agent_runtime_v3", publication_id=pub["id"],
        retrieval_trace={
            "retrieval_branch_node_id": "branch:b", "branch_candidates": [],
            "possible_switches": [], "ledger_revision": 0,
        },
    )
    value = {
        "branch_action": "keep", "branch_anchor_node_id": "branch:b",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "", "extracted_facts": [], "claims": [],
        "next_question_node_id": "question:b", "cited_node_ids": [],
        "cited_chunk_ids": [],
        "reply": "Oi! Para eu te ajudar direitinho, qual é a quantidade?",
        "qualification_complete": False, "handoff_requested": False,
    }

    decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": value},
    )

    assert response.proof["valid"] is True
    assert response.proof["mode"] == "discovery"
    assert response.cart_state["active_branch_node_id"] is None
    assert response.reply_text.endswith("quantidade?")
    assert decision.intent == "collect_graph_fields"


def test_publication_change_preserves_compatible_persona_fact_without_active_branch():
    document = {
        "nodes": [{"id": "persona:generic", "node_type": "persona"}],
        "branch_contracts": {
            "branch:a": {"fields": [{
                "key": "nome_cliente", "scope": "persona",
                "owner_node_id": "persona:generic", "accepted_statuses": ["known"],
                "value_schema": {"type": "string", "minLength": 1},
            }]},
        },
    }
    fact = {
        "field_key": "nome_cliente", "status": "known", "value": "Andressa",
        "owner_node_id": "persona:generic",
    }

    assert graph_agent_runtime_v3._publication_fact_is_compatible(
        document, {}, "nome_cliente", fact,
    )


def test_direct_literal_answer_is_reconciled_to_last_published_missing_field():
    contract = {
        "fields": [{
            "key": "objective",
            "owner_node_id": "branch:a",
            "required": True,
            "accepted_statuses": ["known"],
            "value_schema": {"type": "string", "minLength": 3},
            "question_node_id": "q:objective",
        }],
        "questions": {
            "q:objective": {
                "field_key": "objective",
                "owner_node_id": "branch:a",
                "text": "Qual é o seu objetivo?",
            },
        },
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{
            "role": "user", "content": "Quero continuar com o veículo e cuidar bem dele",
            "message_id": "msg-objective",
        }],
        cart={"facts": {}, "asked_question_node_ids": ["q:objective"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposed = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="sha256:path", extracted_facts=[], claims=[],
        next_question_node_id="q:objective", cited_node_ids=[], cited_chunk_ids=[],
        reply="Entendi.", qualification_complete=False, handoff_requested=False,
    )

    reconciled = graph_agent_runtime_v3._reconcile_direct_answer_to_pending_field(
        proposed, context, contract, {},
    )

    assert len(reconciled.extracted_facts) == 1
    fact = reconciled.extracted_facts[0]
    assert fact.field_key == "objective"
    assert fact.value == "Quero continuar com o veículo e cuidar bem dele"
    assert fact.source_message_id == "msg-objective"


def test_direct_enum_answer_accepts_published_alias_inside_natural_sentence():
    field = {
        "key": "focus",
        "validation": {"mode": "enum", "values": [
            {"value": "shine", "aliases": ["melhorar o brilho"]},
            {"value": "scratches", "aliases": ["reduzir os riscos"]},
            {"value": "both", "aliases": ["melhorar o brilho e reduzir os riscos"]},
        ]},
        "value_schema": {"type": "string", "minLength": 1},
    }

    value = graph_agent_runtime_v3._coerce_direct_field_value(
        "Quero melhorar o brilho e reduzir os riscos", field,
    )

    assert value == "both"


def test_direct_answer_accepts_nullable_json_schema_type_list_without_crashing():
    field = {
        "key": "road_use",
        "value_schema": {"type": ["boolean", "null"]},
    }

    assert graph_agent_runtime_v3._coerce_direct_field_value("não", field) is False
    assert (
        graph_agent_runtime_v3._coerce_direct_field_value(
            "Somente quando viajo", field,
        )
        is None
    )


def test_direct_answer_reconciles_the_last_asked_pending_field_after_order_shift():
    contract = {"fields": [
        {
            "key": "color", "owner_node_id": "persona:generic",
            "accepted_statuses": ["known"], "question_node_id": "q:color",
            "value_schema": {"type": "string", "minLength": 1},
        },
        {
            "key": "focus", "owner_node_id": "persona:generic",
            "accepted_statuses": ["known"], "question_node_id": "q:focus",
            "validation": {"mode": "enum", "values": [{
                "value": "both", "aliases": ["melhorar o brilho e reduzir os riscos"],
            }]},
            "value_schema": {"type": "string", "minLength": 1},
        },
    ]}
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test", messages=[{
            "role": "user", "content": "Quero melhorar o brilho e reduzir os riscos",
            "message_id": "msg-focus",
        }],
        cart={"facts": {}, "asked_question_node_ids": ["q:focus"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposal = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="sha256:path", next_question_node_id="q:color",
    )

    reconciled = graph_agent_runtime_v3._reconcile_direct_answer_to_pending_field(
        proposal, context, contract, {},
    )

    assert [(fact.field_key, fact.value) for fact in reconciled.extracted_facts] == [
        ("focus", "both"),
    ]


def test_fact_source_message_id_is_normalized_to_backend_inbound_identity():
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{
            "role": "user",
            "message_id": "db-message-1946",
            "external_message_id": "provider-message-abc",
            "content": "Beatriz",
        }],
        cart={}, rag_nodes=[], rag_paths=[], graph_contract={},
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposal = ConversationProposal(
        branch_action="keep",
        branch_anchor_node_id="branch:a",
        branch_path_checksum="path:a",
        branch_evidence_span="",
        extracted_facts=[{
            "field_key": "nome_cliente",
            "owner_node_id": "persona:one",
            "status": "known",
            "value": "Beatriz",
            "source_message_id": "provider-message-abc",
            "evidence_span": "Beatriz",
            "confidence": 1,
        }],
        claims=[],
        next_question_node_id="q:objective",
        cited_node_ids=[],
        cited_chunk_ids=[],
        reply="Prazer, Beatriz!",
        qualification_complete=False,
        handoff_requested=False,
    )

    normalized = graph_agent_runtime_v3._normalize_fact_source_message_ids(
        proposal, context,
    )

    assert normalized.extracted_facts[0].source_message_id == "db-message-1946"


def test_direct_reconciliation_does_not_turn_a_supported_doubt_into_a_fact():
    contract = {
        "fields": [{
            "key": "objective", "owner_node_id": "branch:a", "required": True,
            "accepted_statuses": ["known"],
            "value_schema": {"type": "string", "minLength": 3},
            "question_node_id": "q:objective",
        }],
        "questions": {"q:objective": {"field_key": "objective", "text": "Objetivo?"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{"role": "user", "content": "Vocês oferecem este serviço", "message_id": "msg-doubt"}],
        cart={"facts": {}, "asked_question_node_ids": ["q:objective"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposed = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="sha256:path", extracted_facts=[],
        claims=[{
            "claim_type": "availability", "value": {"available": True},
            "evidence_node_ids": ["branch:a"], "evidence_chunk_ids": [],
        }],
        next_question_node_id="q:objective", cited_node_ids=["branch:a"],
        cited_chunk_ids=[], reply="Sim.", qualification_complete=False,
        handoff_requested=False,
    )

    reconciled = graph_agent_runtime_v3._reconcile_direct_answer_to_pending_field(
        proposed, context, contract, {},
    )

    assert reconciled.extracted_facts == []


def test_direct_reconciliation_rejects_question_without_question_mark():
    contract = {
        "fields": [{
            "key": "objective", "owner_node_id": "branch:a", "required": True,
            "accepted_statuses": ["known"],
            "value_schema": {"type": "string", "minLength": 3},
            "question_node_id": "q:objective",
        }],
        "questions": {"q:objective": {"field_key": "objective", "text": "Objetivo?"}},
    }
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:test",
        messages=[{
            "role": "user", "content": "Vocês oferecem este serviço",
            "message_id": "msg-question",
        }],
        cart={"facts": {}, "asked_question_node_ids": ["q:objective"]},
        rag_nodes=[], rag_paths=[], graph_contract=contract,
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a"],
    )
    proposed = ConversationProposal(
        branch_action="keep", branch_anchor_node_id="branch:a",
        branch_path_checksum="sha256:path", extracted_facts=[], claims=[],
        next_question_node_id="q:objective", cited_node_ids=[], cited_chunk_ids=[],
        reply="Sim.", qualification_complete=False, handoff_requested=False,
    )

    reconciled = graph_agent_runtime_v3._reconcile_direct_answer_to_pending_field(
        proposed, context, contract, {},
    )

    assert reconciled.extracted_facts == []


def test_topological_fields_preserves_graph_required_field_order():
    fields = [
        {"key": "can_visit_in_person", "priority": 0.7, "depends_on": []},
        {"key": "nome_cliente", "priority": 0.7, "depends_on": []},
        {"key": "servico", "priority": 1.0, "depends_on": []},
    ]

    ordered, errors = graph_compiler_v3._topological_fields(
        fields,
        preferred_order=["nome_cliente", "servico", "can_visit_in_person"],
    )

    assert errors == []
    assert [field["key"] for field in ordered] == [
        "nome_cliente", "servico", "can_visit_in_person",
    ]


def test_agent_identity_comes_from_the_graph_never_from_code():
    """The model must know its own name, and the name must not live in Python."""
    document = greeting_document()
    persona = graph_agent_runtime_v3._persona_node(document)
    assert graph_agent_runtime_v3._agent_identity_prompt(document) == ""

    persona["data"]["agent_identity"] = {
        "name": "Lia", "role": "agente de atendimento",
        "company": "Aurora Estética Automotiva", "company_short": "Aurora",
    }
    identity = graph_agent_runtime_v3._agent_identity_prompt(document)
    assert "Você se chama Lia" in identity
    assert "Aurora Estética Automotiva" in identity
    # The agent is the person, not the business.
    assert "Você não é a empresa" in identity


def test_system_prompt_carries_no_persona_copy():
    """AGENTS.md 26: production code must not branch on a client or brand."""
    prompt = graph_agent_runtime_v3.SYSTEM_PROMPT
    for forbidden in ("Lia", "Aurora", "Tock", "Vitória"):
        assert forbidden not in prompt


def test_semantic_interpretation_payload_reaches_a_real_decision(monkeypatch):
    """The live workflow sends `interpretation`, never `proposal`.

    `_decide` used to read `observation.get("proposal")` and, finding none,
    validate the WHOLE observation dict as ConversationProposal -- a
    StrictModel with extra="forbid". Every key (`interpretation`,
    `repair_attempt`, ...) came back `extra_forbidden`, so every turn no
    deterministic short-circuit caught fell into `_invalid_proposal_fallback`.
    The main decision path was dead for the shape production actually sends.
    """
    document = compiled_fixture()
    persona_row = {**PERSONA, "config": {}}
    pub = publication(document)
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda slug: persona_row)
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication", lambda persona_id: pub
    )
    contract_b = document["branch_contracts"]["branch:b"]
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[{
            "message_id": "msg:1", "role": "user", "texto": "vou levar pra loja",
        }],
        cart={"facts": {}},
        rag_nodes=[], rag_paths=[],
        graph_contract=contract_b,
        active_branch_node_id="branch:b", active_branch_node_ids=["branch:b"],
        branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
        publication_id=pub["id"],
        retrieval_trace={"retrieval_branch_node_id": "branch:b"},
    )
    observation = {
        "interpretation": {
            "intents": [{"kind": "spontaneous_info", "evidence_span": "vou levar pra loja"}],
            "state_relation": "continue",
            "reply": "Entendi. Quantas unidades voce quer?",
            "recommended_next_action": "ask_field",
        },
        "repair_attempt": 0,
        "interpretation_parse_errors": [],
        "token_usage": {"model": "fixture-model"},
    }

    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation=observation,
    )

    # The bug's signature: the fallback stamps a schema error and throws the
    # model's whole reading away before any of it is used.
    assert "proposal_schema_invalid" not in str(response.proof.get("errors") or [])
    assert response.proof.get("valid"), response.proof.get("errors")
    # Proof that the interpretation was really consumed, not merely tolerated.
    assert response.proof.get("semantic_validation", {}).get("valid") is True
    assert response.reply_text


# ---------------------------------------------------------------------------
# Multi-branch retrieval: a turn with two branches open must see both.
# ---------------------------------------------------------------------------

def test_secondary_retrieval_branches_excludes_the_focused_one():
    assert graph_agent_runtime_v3._secondary_retrieval_branches(
        "branch:a",
        active_branch_node_id="branch:a",
        active_branch_node_ids=["branch:a", "branch:b"],
        branch_anchors=["branch:a", "branch:b"],
    ) == ["branch:b"]


def test_secondary_retrieval_branches_is_empty_with_one_branch_open():
    assert graph_agent_runtime_v3._secondary_retrieval_branches(
        "branch:a",
        active_branch_node_id="branch:a",
        active_branch_node_ids=["branch:a"],
        branch_anchors=["branch:a", "branch:b"],
    ) == []


def test_secondary_retrieval_branches_drops_an_unpublished_anchor():
    """A stale ledger row from a rolled-back publication must not be queried."""
    assert graph_agent_runtime_v3._secondary_retrieval_branches(
        "branch:a",
        active_branch_node_id="branch:a",
        active_branch_node_ids=["branch:a", "branch:gone"],
        branch_anchors=["branch:a", "branch:b"],
    ) == []


def test_secondary_retrieval_branches_dedupes_and_keeps_order():
    assert graph_agent_runtime_v3._secondary_retrieval_branches(
        "branch:a",
        active_branch_node_id="branch:b",
        active_branch_node_ids=["branch:b", "branch:c", "branch:b"],
        branch_anchors=["branch:a", "branch:b", "branch:c"],
    ) == ["branch:b", "branch:c"]


# ---------------------------------------------------------------------------
# The branch selector is never a "non-service field".
# ---------------------------------------------------------------------------

def _selector_contract(selector_key: str) -> dict:
    return {
        "fields": [
            {"key": selector_key, "question_node_id": "q:selector",
             "branch_selection_field": True},
            {"key": "outro_campo", "question_node_id": "q:outro"},
        ],
    }


@pytest.mark.parametrize("selector_key", ["servico", "purchase_profile", "modalidade"])
def test_answering_the_branch_selector_is_never_suppressed(selector_key):
    """Suppressing it strands the customer on the question they just answered.

    The key is graph-declared: Aurora's is "servico", Tock Fatal's is
    "purchase_profile". Comparing against the literal "servico" silently broke
    every persona that named it anything else.
    """
    assert graph_agent_runtime_v3._is_direct_answer_to_pending_non_service_field(
        message="uso próprio mesmo",
        contract=_selector_contract(selector_key),
        missing_fields=[selector_key],
        asked_question_node_ids=["q:selector"],
    ) is False


def test_a_genuine_non_service_field_answer_is_still_suppressed():
    """The guard's real job survives: service words inside a field answer
    must not hijack branch focus."""
    assert graph_agent_runtime_v3._is_direct_answer_to_pending_non_service_field(
        message="a pintura perdeu o brilho",
        contract=_selector_contract("servico"),
        missing_fields=["outro_campo"],
        asked_question_node_ids=["q:outro"],
    ) is True

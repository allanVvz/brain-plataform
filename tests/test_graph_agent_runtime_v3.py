from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.conversation import ConversationContext, ConversationProposal, ContextCard, ExtractedFact
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

@pytest.mark.parametrize("status", ["unknown", "declined", "needs_confirmation"])
def test_semantic_fact_statuses_are_contract_owned(status):
    document = compiled_fixture(accepted=["known", status])
    value = proposal(document, branch_action="keep", branch_evidence_span="", extracted_facts=[{
        "field_key": "metragem", "owner_node_id": "branch:a", "status": status,
        "value": None, "source_message_id": "msg-1", "evidence_span": "não sei",
        "confidence": 0.9,
    }], next_question_node_id=None, qualification_complete=True,
                     cited_node_ids=["branch:a"], cited_chunk_ids=[])
    proof = check(document, value, active="branch:a", message="não sei")
    assert proof["valid"], proof["errors"]
    assert proof["missing_fields"] == []


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
    assert "handoff_required_by_rule" in missing_handoff["errors"]
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


def test_strict_model_parse_failure_emits_only_published_fallback():
    document = compiled_fixture()
    context = ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], messages=[], cart={"facts": {}},
        rag_nodes=[], rag_paths=[], graph_contract=document["branch_contracts"]["branch:a"],
        active_branch_node_id="branch:a", branch_node_ids=[], runtime_version="graph_agent_runtime_v3",
    )
    decision, response = graph_agent_runtime_v3.decide(
        context,
        model_observation={"proposal": proposal(document), "proposal_parse_errors": ["missing:claims"]},
    )
    assert decision.intent == "published_fallback"
    assert response.reply_text == "Qual é a metragem?"
    assert response.handoff_required is False


def test_published_question_is_composed_not_required_in_model_reply():
    document = compiled_fixture()
    value = proposal(document, reply="Certo.")
    proof = check(document, value)
    assert proof["valid"], proof["errors"]
    emitted = graph_proof_checker_v3.compose_published_question(
        reply=value["reply"], next_question_node_id="question:a",
        contract=document["branch_contracts"]["branch:a"],
    )
    assert emitted == "Certo.\n\nQual é a metragem?"


def test_published_question_is_not_duplicated_when_model_personalizes_it():
    """Regression test for the duplicate-question-in-one-message gap (2026-08-08 report).

    Evidence across several Aurora transcripts: the model asks a field
    question in its own words, personalized with a value already known
    (e.g. "Você consegue trazer o Onix aqui..." instead of the published
    "...o carro..."), and the literal-substring check in
    compose_published_question() failed to recognize that as the same
    question, so it appended the canonical text again in the same message.
    Content-word overlap should recognize the personalized rewording as
    already asking it.
    """
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    emitted = graph_proof_checker_v3.compose_published_question(
        reply="Perfeito! E qual é a metragem do seu apartamento, você sabe me dizer?",
        next_question_node_id="question:a", contract=contract,
    )
    assert emitted == "Perfeito! E qual é a metragem do seu apartamento, você sabe me dizer?"


def test_published_question_is_still_appended_for_a_genuinely_different_reply():
    document = compiled_fixture()
    contract = document["branch_contracts"]["branch:a"]
    emitted = graph_proof_checker_v3.compose_published_question(
        reply="Perfeito, anotado!", next_question_node_id="question:a", contract=contract,
    )
    assert emitted == "Perfeito, anotado!\n\nQual é a metragem?"


def test_published_question_is_not_duplicated_when_its_only_content_word_is_swapped():
    """Regression test for a gap in the fix above, found live 2026-08-08.

    Word-overlap alone still missed a short question whose only real
    content word is exactly the one the model personalizes away: "Qual é a
    cor do veículo?" -> the model says "...Qual é a cor do seu Onix?" --
    "veículo" is gone, replaced by the car model, so content-word overlap
    was 0. The shared sentence structure around the swapped word (character
    -run coverage) must catch this even when word overlap alone can't.
    """
    contract = {"questions": {"q:color": {"text": "Qual é a cor do veículo?", "field_key": "vehicle_color"}}}
    emitted = graph_proof_checker_v3.compose_published_question(
        reply="Entendi, Beatriz! Bancos manchados são comuns. Qual é a cor do seu Onix?",
        next_question_node_id="q:color", contract=contract,
    )
    assert "Qual é a cor do veículo?" not in emitted


def test_published_question_still_appends_for_a_similarly_worded_different_question():
    """The character-run signal must not blur two genuinely different questions."""
    contract = {"questions": {"q:color": {"text": "Qual é a cor do veículo?", "field_key": "vehicle_color"}}}
    emitted = graph_proof_checker_v3.compose_published_question(
        reply="Perfeito! Anotado.", next_question_node_id="q:color", contract=contract,
    )
    assert emitted == "Perfeito! Anotado.\n\nQual é a cor do veículo?"


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


def test_persona_wide_field_duplicated_per_branch_is_wrongly_reasked_on_switch():
    """Regression test for docs/handoffs/AURORA_QUALIFICATION_REPEAT_QUESTION_HANDOFF_2026-08-08.md.

    test_pending_fields_ignores_a_fact_owned_by_a_different_branch above
    covers a field that is *legitimately* branch-specific (e.g. "servico"):
    it is correct for that fact to reset on a branch switch. This test
    covers the opposite, currently-unhandled case: a field whose question
    and expected answer never change across branches (e.g. "nome_cliente",
    "can_visit_in_person" in the Aurora transcripts) but whose graph
    content redeclares it on every branch node instead of once on the
    shared persona node. _field_declarations() (graph_compiler_v3.py)
    defaults owner_node_id to whichever node happens to declare the field,
    so each branch's redundant copy gets a *different* owner_node_id even
    though the field means the same thing everywhere. _resolved_for_field_owner
    (added 2026-08-06 to stop real cross-branch leakage of fields like
    "servico") then wipes this kind of field out on every branch switch too,
    forcing the agent to re-ask a question the customer already answered --
    this is the mechanism behind the repeated-question bug.
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
    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)

    contract_a = document["branch_contracts"]["branch:a"]
    contract_b = document["branch_contracts"]["branch:b"]
    owner_a = next(f["owner_node_id"] for f in contract_a["fields"] if f["key"] == "nome_cliente")
    owner_b = next(f["owner_node_id"] for f in contract_b["fields"] if f["key"] == "nome_cliente")
    assert owner_a != owner_b  # the authoring mistake: same field, two owners

    facts_known_while_branch_a_was_active = {
        "nome_cliente": {"status": "known", "value": "Allan", "owner_node_id": owner_a},
    }
    pending = graph_proof_checker_v3.pending_fields(contract_b, facts_known_while_branch_a_was_active)
    assert [field["key"] for field in pending] == ["nome_cliente"]


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


def test_decide_add_action_grows_active_branch_node_ids_without_dropping_the_current_one(monkeypatch):
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
    assert response.cart_state["active_branch_node_ids"] == ["branch:a", "branch:b"]
    # Dialogue focus moves to the branch just added, but the list keeps both.
    assert response.cart_state["active_branch_node_id"] == "branch:b"


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

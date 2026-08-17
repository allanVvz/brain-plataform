from __future__ import annotations

import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_proof_checker_v3


def test_aggregate_missing_fields_unions_two_active_branches():
    """Two simultaneously-selected services must each keep their own
    required fields pending until resolved, while a shared persona-owned
    field (nome_cliente) counts as resolved once, for both.
    """
    branch_contracts = {
        "branch:interior": {"fields": [
            {"key": "nome_cliente", "owner_node_id": "aurora-persona", "required": True,
             "accepted_statuses": ["known"]},
            {"key": "servico", "owner_node_id": "branch:interior", "required": True,
             "accepted_statuses": ["known"]},
        ]},
        "branch:bodywork": {"fields": [
            {"key": "nome_cliente", "owner_node_id": "aurora-persona", "required": True,
             "accepted_statuses": ["known"]},
            {"key": "servico", "owner_node_id": "branch:bodywork", "required": True,
             "accepted_statuses": ["known"]},
        ]},
    }
    facts_by_key = {
        "nome_cliente": [
            {"status": "known", "value": "Allan", "owner_node_id": "aurora-persona"},
        ],
        "servico": [
            {"status": "known", "value": "Higienização interna", "owner_node_id": "branch:interior"},
        ],
    }

    missing = graph_proof_checker_v3.aggregate_missing_fields(
        branch_contracts, ["branch:interior", "branch:bodywork"], facts_by_key,
    )

    # nome_cliente is resolved (shared persona owner, known once) -- must not
    # appear twice or at all. servico is only resolved for branch:interior;
    # branch:bodywork's own servico fact was never given, so it must still
    # be pending, scoped to its own owner.
    assert [(field["key"], field["owner_node_id"]) for field in missing] == [
        ("servico", "branch:bodywork"),
    ]


def test_aggregate_missing_fields_is_empty_when_every_active_branch_is_resolved():
    branch_contracts = {
        "branch:a": {"fields": [
            {"key": "servico", "owner_node_id": "branch:a", "required": True,
             "accepted_statuses": ["known"]},
        ]},
        "branch:b": {"fields": [
            {"key": "servico", "owner_node_id": "branch:b", "required": True,
             "accepted_statuses": ["known"]},
        ]},
    }
    facts_by_key = {
        "servico": [
            {"status": "known", "value": "Polimento", "owner_node_id": "branch:a"},
            {"status": "known", "value": "Vitrificação", "owner_node_id": "branch:b"},
        ],
    }

    assert graph_proof_checker_v3.aggregate_missing_fields(
        branch_contracts, ["branch:a", "branch:b"], facts_by_key,
    ) == []


def test_aggregate_required_count_deduplicates_shared_owner():
    branch_contracts = {
        "branch:a": {"fields": [
            {"key": "name", "owner_node_id": "persona", "required": True},
            {"key": "service", "owner_node_id": "branch:a", "required": True},
        ]},
        "branch:b": {"fields": [
            {"key": "name", "owner_node_id": "persona", "required": True},
            {"key": "service", "owner_node_id": "branch:b", "required": True},
        ]},
    }

    assert graph_proof_checker_v3.aggregate_required_field_count(
        branch_contracts, ["branch:a", "branch:b"], {},
    ) == 3


def test_aggregate_missing_fields_with_a_single_active_branch_matches_pending_fields():
    """With exactly one active branch, aggregation must reduce to the same
    result as the existing single-branch pending_fields() -- multi-service
    support must not change anything for personas that never use "add"."""
    contract = {"fields": [
        {"key": "servico", "owner_node_id": "branch:a", "required": True,
         "accepted_statuses": ["known"]},
    ]}
    facts_by_key: dict = {}

    aggregated = graph_proof_checker_v3.aggregate_missing_fields(
        {"branch:a": contract}, ["branch:a"], facts_by_key,
    )
    single = graph_proof_checker_v3.pending_fields(contract, {})
    assert [field["key"] for field in aggregated] == [field["key"] for field in single]


def test_unknown_field_stays_missing_but_is_not_asked_again():
    contract = {"fields": [
        {"key": "name", "owner_node_id": "persona", "required": True,
         "accepted_statuses": ["known"], "question_node_id": "q:name"},
        {"key": "objective", "owner_node_id": "persona", "required": True,
         "accepted_statuses": ["known"], "question_node_id": "q:objective"},
    ]}
    facts = {
        "name": {"status": "unknown", "value": None, "owner_node_id": "persona"},
    }

    assert [field["key"] for field in graph_proof_checker_v3.pending_fields(
        contract, facts,
    )] == ["name", "objective"]
    assert [field["key"] for field in graph_proof_checker_v3.askable_pending_fields(
        contract, facts,
    )] == ["objective"]


def test_unknown_never_qualifies_even_when_legacy_contract_accepts_it():
    field = {
        "key": "color", "owner_node_id": "persona", "required": True,
        "accepted_statuses": ["known", "unknown"], "question_node_id": "q:color",
    }
    facts = {
        "color": {"status": "unknown", "value": None, "owner_node_id": "persona"},
    }

    assert graph_proof_checker_v3.pending_fields({"fields": [field]}, facts) == [field]
    assert graph_proof_checker_v3.askable_pending_fields({"fields": [field]}, facts) == []


def test_loose_later_answer_can_replace_unknown_without_correction_marker():
    contract = {
        "branch_path_checksum": "checksum:a",
        "closure_node_ids": ["branch:a", "q:name"],
        "fields": [{
            "key": "name", "owner_node_id": "persona", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:name",
            "value_schema": {"type": "string", "minLength": 1},
            "overwrite_policy": "explicit_correction",
        }],
        "questions": {"q:name": {"field_key": "name", "text": "Qual seu nome?"}},
    }
    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active", "checksum": "sha256:x",
            "document_json": {"branch_anchors": ["branch:a"]},
        },
        contract=contract,
        ledger={
            "graph_checksum": "sha256:x",
            "facts": {"name": {
                "status": "unknown", "value": None, "owner_node_id": "persona",
            }},
        },
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "",
            "extracted_facts": [{
                "field_key": "name", "owner_node_id": "persona", "status": "known",
                "value": "Beatriz", "source_message_id": "msg-1",
                "evidence_span": "Beatriz", "confidence": 1,
            }],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Prazer!",
            "qualification_complete": True, "handoff_requested": False,
        },
        message="Meu nome é Beatriz", source_message_id="msg-1",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", branch_selection_allowed=False,
        branch_switch_allowed=False,
    )

    assert proof["valid"] is True, proof["errors"]
    assert proof["accepted_facts"][0]["value"] == "Beatriz"


def _single_fact_proof(*, message: str, value: str, evidence_span: str) -> dict:
    contract = {
        "branch_path_checksum": "checksum:a",
        "closure_node_ids": ["branch:a"],
        "fields": [{
            "key": "vehicle", "owner_node_id": "branch:a", "required": True,
            "accepted_statuses": ["known"], "value_schema": {"type": "string"},
        }],
        "questions": {},
    }
    return graph_proof_checker_v3.check(
        publication={
            "status": "active", "checksum": "sha256:x",
            "document_json": {"branch_anchors": ["branch:a"]},
        },
        contract=contract,
        ledger={"graph_checksum": "sha256:x", "facts": {}},
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "",
            "extracted_facts": [{
                "field_key": "vehicle", "owner_node_id": "branch:a",
                "status": "known", "value": value,
                "source_message_id": "msg-2", "evidence_span": evidence_span,
                "confidence": 1,
            }],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Anotado.",
            "qualification_complete": True, "handoff_requested": False,
        },
        message=message, source_message_id="msg-2",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", branch_selection_allowed=False,
        branch_switch_allowed=False,
    )


def test_fact_evidence_can_span_adjacent_messages_in_a_canonical_burst():
    proof = _single_fact_proof(
        message="Byd\nDolphin", value="Byd Dolphin", evidence_span="Byd Dolphin",
    )

    assert proof["valid"] is True, proof["errors"]
    assert proof["accepted_facts"][0]["value"] == "Byd Dolphin"


def test_media_placeholder_cannot_be_persisted_as_a_known_fact():
    proof = _single_fact_proof(
        message="[o cliente enviou uma imagem]",
        value="[o cliente enviou uma imagem]",
        evidence_span="[o cliente enviou uma imagem]",
    )

    assert "fact_evidence_placeholder:vehicle" in proof["errors"]
    assert proof["accepted_facts"] == []


def _base_check_kwargs(**overrides):
    document = {"branch_anchors": ["branch:a", "branch:b"]}
    publication = {"status": "active", "checksum": "sha256:x", "document_json": document}
    contract = {
        "branch_path_checksum": "checksum:b", "closure_node_ids": ["branch:b"],
        "fields": [],
    }
    ledger = {"graph_checksum": "sha256:x", "facts": {}}
    proposal = {
        "branch_action": "add", "branch_anchor_node_id": "branch:b",
        "branch_path_checksum": "checksum:b", "branch_evidence_span": "polimento",
        "extracted_facts": [], "claims": [], "cited_node_ids": [], "cited_chunk_ids": [],
    }
    kwargs = dict(
        publication=publication, contract=contract, ledger=ledger, proposal=proposal,
        message="quero também polimento", source_message_id="msg-1",
        package_node_ids={"branch:b"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", branch_selection_allowed=False,
        branch_switch_allowed=True, active_branch_node_ids=["branch:a"],
    )
    kwargs.update(overrides)
    return kwargs


def test_add_action_accepts_a_new_branch_alongside_the_active_one():
    proof = graph_proof_checker_v3.check(**_base_check_kwargs())
    assert proof["valid"], proof["errors"]


def test_add_action_rejects_re_adding_an_already_active_branch():
    kwargs = _base_check_kwargs(active_branch_node_ids=["branch:a", "branch:b"])
    proof = graph_proof_checker_v3.check(**kwargs)
    assert "add_duplicate_branch" in proof["errors"]


def test_add_action_rejects_without_any_active_branch():
    kwargs = _base_check_kwargs(active_branch_node_id=None, active_branch_node_ids=[])
    proof = graph_proof_checker_v3.check(**kwargs)
    assert "add_without_active_branch" in proof["errors"]


def test_next_question_must_target_the_first_missing_graph_field():
    contract = {
        "branch_path_checksum": "checksum:a",
        "closure_node_ids": ["branch:a", "q:first", "q:second"],
        "fields": [
            {"key": "first", "owner_node_id": "persona", "required": True,
             "accepted_statuses": ["known"], "question_node_id": "q:first"},
            {"key": "second", "owner_node_id": "persona", "required": True,
             "accepted_statuses": ["known"], "question_node_id": "q:second"},
        ],
        "questions": {
            "q:first": {"field_key": "first", "text": "First?", "depends_on": []},
            "q:second": {"field_key": "second", "text": "Second?", "depends_on": []},
        },
    }
    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active", "checksum": "sha256:x",
            "document_json": {"branch_anchors": ["branch:a"]},
        },
        contract=contract,
        ledger={"graph_checksum": "sha256:x", "facts": {}},
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "",
            "extracted_facts": [], "claims": [],
            "next_question_node_id": "q:second", "cited_node_ids": [],
            "cited_chunk_ids": [], "reply": "Second?",
            "qualification_complete": False, "handoff_requested": False,
        },
        message="hello", source_message_id="msg-1",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", branch_selection_allowed=False,
        branch_switch_allowed=False,
    )
    assert "next_question_not_first_missing_field" in proof["errors"]


def test_add_action_requires_literal_evidence():
    kwargs = _base_check_kwargs(branch_switch_allowed=True)
    kwargs["proposal"] = {**kwargs["proposal"], "branch_evidence_span": "algo que não foi dito"}
    proof = graph_proof_checker_v3.check(**kwargs)
    assert "branch_evidence_not_literal" in proof["errors"]


def test_add_action_falls_back_to_singular_active_branch_when_list_not_given():
    """Callers that don't pass active_branch_node_ids (not yet using
    multi-service) still get correct "add" validation from the singular
    active_branch_node_id alone -- this keeps every existing call site
    working unchanged."""
    kwargs = _base_check_kwargs(active_branch_node_ids=None)
    proof = graph_proof_checker_v3.check(**kwargs)
    assert proof["valid"], proof["errors"]


@pytest.mark.parametrize("value", [
    "Ana Silva",
    "Jo\u00e3o da Silva",
    "Anne-Marie O'Neill",
    "Anne-Marie O\u2019Neill",
])
def test_human_full_name_accepts_unicode_particles_hyphen_and_apostrophe(value):
    assert graph_proof_checker_v3.is_human_full_name(value)


@pytest.mark.parametrize("value", [
    "Ana", "bom dia", "e ae", "Ana 123", "https://example.com Ana",
    "Ana_Silva", "Ana Silva Pereira Souza Costa Oliveira Santos",
])
def test_human_full_name_rejects_incomplete_or_non_name_values(value):
    assert not graph_proof_checker_v3.is_human_full_name(value)


def test_pending_name_confirmation_never_resolves_a_required_field():
    field = {
        "accepted_statuses": ["known", "needs_confirmation", "invalid"],
    }
    assert not graph_proof_checker_v3.field_resolved(
        field, {"status": "needs_confirmation", "value": None},
    )
    assert not graph_proof_checker_v3.field_resolved(
        field, {"status": "invalid", "value": None},
    )


def test_service_operation_requires_authorized_consumed_evidence():
    document = {
        "branch_anchors": ["branch:a"],
        "coordinates": {"branch:a": {"path_checksum": "checksum:a"}},
    }
    operation = {
        "action": "add", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": "checksum:a", "evidence_span": "Vitrifica\u00e7\u00e3o",
        "evidence_type": "exact_catalog", "resolution_method": "exact_catalog",
    }
    rejected = graph_proof_checker_v3.check_service_operations(
        document=document, message="Quero Vitrifica\u00e7\u00e3o", operations=[operation],
        active_branch_node_ids=[], consumed_service_spans=[],
    )
    assert "service_evidence_not_consumed:branch:a" in rejected["errors"]

    accepted = graph_proof_checker_v3.check_service_operations(
        document=document, message="Quero Vitrifica\u00e7\u00e3o", operations=[operation],
        active_branch_node_ids=[], consumed_service_spans=[{
            "text": "Vitrifica\u00e7\u00e3o", "start": 6, "end": 18,
            "branch_anchor_node_id": "branch:a", "evidence_type": "exact_catalog",
        }],
    )
    assert accepted["valid"], accepted["errors"]
    assert accepted["next_active_branch_node_ids"] == ["branch:a"]


# ── validate_natural_summary: grounding guard for the model-written summary ──

def test_natural_summary_accepted_when_every_value_is_mentioned():
    assert graph_proof_checker_v3.validate_natural_summary(
        "Boa, Cintia! Então fechamos assim: vitrificação no seu Civic 2021. "
        "Confere pra mim se está certo?",
        informed_values=["Cintia", "Vitrificação", "Civic", "2021"],
    ) is True


def test_natural_summary_rejected_when_a_collected_value_is_missing():
    assert graph_proof_checker_v3.validate_natural_summary(
        "Boa! Então fechamos assim: vitrificação no seu carro. Confere?",
        informed_values=["Cintia", "Vitrificação", "Civic", "2021"],
    ) is False


def test_natural_summary_rejected_without_exactly_one_question():
    grounded = "Fechamos vitrificação no seu Civic 2021."
    assert graph_proof_checker_v3.validate_natural_summary(
        grounded, informed_values=["Vitrificação", "Civic", "2021"],
    ) is False
    assert graph_proof_checker_v3.validate_natural_summary(
        grounded + " Confere? Posso seguir?",
        informed_values=["Vitrificação", "Civic", "2021"],
    ) is False


def test_natural_summary_rejected_when_it_claims_the_order_is_already_closed():
    assert graph_proof_checker_v3.validate_natural_summary(
        "Prontinho, vitrificação confirmada pro seu Civic 2021. Combinado?",
        informed_values=["Vitrificação", "Civic", "2021"],
    ) is False


def test_natural_summary_match_is_accent_and_case_insensitive():
    assert graph_proof_checker_v3.validate_natural_summary(
        "entao ficou assim: VITRIFICACAO no seu carro. ta certo?",
        informed_values=["Vitrificação"],
    ) is True

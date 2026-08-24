from __future__ import annotations

import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_proof_checker_v3
from schemas.conversation import ServiceOperation


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


def test_add_action_can_resolve_a_pending_selection_confirmation_without_correction_marker():
    """Regression (live 2026-08-18): the branch selector field is the only
    one whose accepted_statuses graph_compiler_v3._with_confirmable_status
    widens to include "needs_confirmation" -- an approximate service match
    stays pending until the customer confirms. Settling that candidate into
    "known" once the customer answers ("pedi chapeacao tambem", no "na
    verdade"/"corrigindo" language) is confirmation, not correction, and
    must not require the explicit-correction marker the overwrite policy
    otherwise demands. Before this fix it failed as
    fact_correction_not_explicit:servico, discarding the whole proposal and
    leaving the customer's clarification unanswered."""
    contract = {
        "branch_path_checksum": "checksum:chapeacao",
        "closure_node_ids": ["branch:chapeacao"],
        "fields": [{
            "key": "servico", "owner_node_id": "branch:chapeacao", "required": True,
            "accepted_statuses": ["known", "needs_confirmation"],
            "value_schema": {"type": "string", "minLength": 1},
            "overwrite_policy": "explicit_correction",
        }],
        "questions": {},
    }
    proof = graph_proof_checker_v3.check(
        publication={
            "status": "active", "checksum": "sha256:x",
            "document_json": {"branch_anchors": ["branch:chapeacao", "branch:lavagem"]},
        },
        contract=contract,
        ledger={
            "graph_checksum": "sha256:x",
            "facts": {"servico": {
                "status": "needs_confirmation", "value": "Chapeação",
                "owner_node_id": "branch:chapeacao",
            }},
        },
        proposal={
            "branch_action": "add", "branch_anchor_node_id": "branch:chapeacao",
            "branch_path_checksum": "checksum:chapeacao",
            "branch_evidence_span": "chapeacao",
            "extracted_facts": [{
                "field_key": "servico", "owner_node_id": "branch:chapeacao",
                "status": "known", "value": "Chapeação", "source_message_id": "msg-3",
                "evidence_span": "chapeacao", "confidence": 1,
            }],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Anotado, chapeação também.",
            "qualification_complete": True, "handoff_requested": False,
        },
        message="pedi chapeacao tambem", source_message_id="msg-3",
        package_node_ids={"branch:chapeacao"}, package_chunk_ids=set(),
        active_branch_node_id="branch:lavagem",
        active_branch_node_ids=["branch:lavagem"],
        branch_selection_allowed=False, branch_switch_allowed=True,
    )

    assert proof["valid"] is True, proof["errors"]
    assert proof["accepted_facts"][0]["value"] == "Chapeação"


def _two_branch_fixture():
    """branch:a is this turn's focused contract; branch:b is a second
    already-active branch whose own field only becomes visible via
    additional_fields (the union of every active branch's own fields)."""
    contract_a = {
        "branch_path_checksum": "checksum:a",
        "closure_node_ids": ["branch:a"],
        # required=False: these tests are about whether a fact validates,
        # not about full qualification/pending-question mechanics.
        "fields": [{
            "key": "servico", "owner_node_id": "branch:a", "required": False,
            "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
        }],
        "questions": {},
    }
    branch_b_field = {
        "key": "servico", "owner_node_id": "branch:b", "required": False,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
    }
    publication = {
        "status": "active", "checksum": "sha256:x",
        "document_json": {"branch_anchors": ["branch:a", "branch:b"]},
    }
    ledger = {"graph_checksum": "sha256:x", "facts": {}}
    return contract_a, branch_b_field, publication, ledger


def test_check_accepts_a_fact_for_a_second_active_branch_via_additional_fields():
    """Regression for Claim 3 (branch-scoped extracted_facts asymmetry): a
    customer naming two services in the same message, with the model's
    branch_anchor_node_id focused on branch:a this turn, must not have
    branch:b's own fact rejected as undeclared purely because this turn's
    contract only covers branch:a. additional_fields carries branch:b's own
    declared fields so its fact validates too."""
    contract_a, branch_b_field, publication, ledger = _two_branch_fixture()
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract_a, ledger=ledger,
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "servico a",
            "extracted_facts": [{
                "field_key": "servico", "owner_node_id": "branch:b",
                "status": "known", "value": "PPF", "source_message_id": "msg-1",
                "evidence_span": "ppf", "confidence": 1,
            }],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Anotado.",
            "qualification_complete": False, "handoff_requested": False,
        },
        message="quero servico a e ppf", source_message_id="msg-1",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a", "branch:b"],
        branch_selection_allowed=False, branch_switch_allowed=True,
        additional_fields=[branch_b_field],
    )
    assert proof["valid"] is True, proof["errors"]
    assert proof["accepted_facts"][0]["value"] == "PPF"
    assert proof["accepted_facts"][0]["owner_node_id"] == "branch:b"


def test_check_without_additional_fields_still_rejects_a_foreign_branch_fact():
    """Backward-compat guard: omitting additional_fields keeps today's
    behavior -- a fact for a branch outside the focused contract is
    rejected, not silently accepted."""
    contract_a, _branch_b_field, publication, ledger = _two_branch_fixture()
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract_a, ledger=ledger,
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "servico a",
            "extracted_facts": [{
                "field_key": "servico", "owner_node_id": "branch:b",
                "status": "known", "value": "PPF", "source_message_id": "msg-1",
                "evidence_span": "ppf", "confidence": 1,
            }],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Anotado.",
            "qualification_complete": False, "handoff_requested": False,
        },
        message="quero servico a e ppf", source_message_id="msg-1",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a", "branch:b"],
        branch_selection_allowed=False, branch_switch_allowed=True,
    )
    assert proof["valid"] is True
    # Matches pre-existing behavior: contract_a already declares "servico"
    # (for branch:a), so the key isn't unknown -- it's an owner mismatch,
    # not undeclared. additional_fields only adds NEW (key, owner) pairs;
    # it doesn't change this outcome for a key the focused contract already
    # declares under a different owner.
    assert "field_owner_mismatch:servico" in proof["errors"]
    assert "field_owner_mismatch:servico" in proof["component_errors"]
    assert proof["accepted_facts"] == []


def test_check_field_owner_mismatch_still_distinguished_from_undeclared_field():
    """A fact whose key is declared (for a DIFFERENT owner) in
    additional_fields, but whose own declared owner doesn't match any known
    (key, owner) pair, must still be field_owner_mismatch, not
    undeclared_field -- the two error codes mean different things
    downstream."""
    contract_a, branch_b_field, publication, ledger = _two_branch_fixture()
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract_a, ledger=ledger,
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "servico a",
            "extracted_facts": [{
                "field_key": "servico", "owner_node_id": "branch:c",
                "status": "known", "value": "Pintura", "source_message_id": "msg-1",
                "evidence_span": "pintura", "confidence": 1,
            }],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Anotado.",
            "qualification_complete": False, "handoff_requested": False,
        },
        message="quero servico a e pintura", source_message_id="msg-1",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a", "branch:b"],
        branch_selection_allowed=False, branch_switch_allowed=True,
        additional_fields=[branch_b_field],
    )
    assert proof["valid"] is True
    assert "field_owner_mismatch:servico" in proof["errors"]
    assert "field_owner_mismatch:servico" in proof["component_errors"]
    assert "undeclared_field:servico" not in proof["errors"]
    assert proof["accepted_facts"] == []


def test_field_validation_entries_are_attributed_to_the_owning_branch():
    """Foundation for the Claim-4 error-partitioning fix: each
    field_validation row must carry the owner_node_id of the fact that
    produced it, so a caller can tell a non-focused branch's own error apart
    from the focused branch's. Uses a fact that IS declared (via
    additional_fields) but fails a later per-fact check (evidence not
    literal in the message) -- unlike undeclared_field/field_owner_mismatch,
    which bail out before ever reaching field_validation."""
    contract_a, _branch_b_field, publication, ledger = _two_branch_fixture()
    branch_b_extra_field = {
        "key": "outro_campo", "owner_node_id": "branch:b", "required": False,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
    }
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract_a, ledger=ledger,
        proposal={
            "branch_action": "keep", "branch_anchor_node_id": "branch:a",
            "branch_path_checksum": "checksum:a", "branch_evidence_span": "servico a",
            "extracted_facts": [
                {
                    "field_key": "servico", "owner_node_id": "branch:a",
                    "status": "known", "value": "Servico A", "source_message_id": "msg-1",
                    "evidence_span": "servico a", "confidence": 1,
                },
                {
                    "field_key": "outro_campo", "owner_node_id": "branch:b",
                    "status": "known", "value": "PPF", "source_message_id": "msg-1",
                    "evidence_span": "essa frase nao esta na mensagem", "confidence": 1,
                },
            ],
            "claims": [], "next_question_node_id": None,
            "cited_node_ids": [], "cited_chunk_ids": [], "reply": "Anotado.",
            "qualification_complete": False, "handoff_requested": False,
        },
        message="quero servico a e ppf", source_message_id="msg-1",
        package_node_ids={"branch:a"}, package_chunk_ids=set(),
        active_branch_node_id="branch:a", active_branch_node_ids=["branch:a", "branch:b"],
        branch_selection_allowed=False, branch_switch_allowed=True,
        additional_fields=[branch_b_extra_field],
    )
    invalid_rows = [row for row in proof["field_validation"] if not row["valid"]]
    assert len(invalid_rows) == 1
    assert invalid_rows[0]["owner_node_id"] == "branch:b"
    assert "fact_evidence_not_literal:outro_campo" in invalid_rows[0]["errors"]


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


def test_unproved_question_text_is_not_authorized_when_selection_is_invalid():
    kwargs = _base_check_kwargs()
    kwargs["contract"] = {
        "branch_path_checksum": "checksum:b",
        "closure_node_ids": ["branch:b", "q:objective", "q:budget"],
        "fields": [{
            "key": "objective", "owner_node_id": "branch:b", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:objective",
        }],
        "questions": {
            "q:objective": {"field_key": "objective", "text": "Qual seu objetivo?"},
            "q:budget": {"field_key": "budget", "text": "Qual seu orçamento?"},
        },
    }
    kwargs["proposal"] = {
        **kwargs["proposal"],
        "next_question_node_id": "q:budget",
        "reply": "Posso te orientar. Qual seu orçamento?",
    }

    proof = graph_proof_checker_v3.check(**kwargs)

    assert proof["valid"] is True
    assert "next_question_not_askable" in proof["errors"]
    assert "next_question_not_askable" in proof["component_errors"]
    assert proof["next_question_node_id"] is None


def test_add_action_rejects_re_adding_an_already_active_branch():
    kwargs = _base_check_kwargs(active_branch_node_ids=["branch:a", "branch:b"])
    proof = graph_proof_checker_v3.check(**kwargs)
    assert "add_duplicate_branch" in proof["errors"]


def test_add_action_rejects_without_any_active_branch():
    kwargs = _base_check_kwargs(active_branch_node_id=None, active_branch_node_ids=[])
    proof = graph_proof_checker_v3.check(**kwargs)
    assert "add_without_active_branch" in proof["errors"]


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


@pytest.mark.parametrize("value", ["Allan", "Allan Rodrigues", "José da Silva"])
def test_human_name_accepts_preferred_or_complete_name(value):
    canonical, error = graph_proof_checker_v3._canonical_field_value(
        {
            "validation": {"mode": "semantic", "semantic_type": "human_name"},
            "value_schema": {"type": "string", "minLength": 1},
        },
        value,
        value,
    )
    assert canonical == value
    assert error is None


@pytest.mark.parametrize("value", ["oi", "bom dia", "123", "https://example.com", "quero polimento"])
def test_human_name_rejects_greetings_numbers_urls_and_non_names(value):
    _, error = graph_proof_checker_v3._canonical_field_value(
        {
            "validation": {"mode": "semantic", "semantic_type": "human_name"},
            "value_schema": {"type": "string", "minLength": 1},
        },
        value,
        value,
    )
    assert error == "value is not a plausible human name"


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


def test_branch_operation_does_not_depend_on_service_resolver_consumption():
    document = {
        "branch_anchors": ["branch:a"],
        "coordinates": {"branch:a": {"path_checksum": "checksum:a"}},
    }
    operation = {
        "action": "add", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": "checksum:a", "evidence_span": "Vitrifica\u00e7\u00e3o",
        "evidence_type": "exact_catalog", "resolution_method": "exact_catalog",
    }
    accepted_without_resolver = graph_proof_checker_v3.check_service_operations(
        document=document, message="Quero Vitrifica\u00e7\u00e3o", operations=[operation],
        active_branch_node_ids=[], consumed_service_spans=[],
    )
    assert accepted_without_resolver["valid"]
    assert accepted_without_resolver["errors"] == []
    assert (
        "branch_evidence_not_consumed:branch:a"
        in accepted_without_resolver["observations"]
    )

    accepted = graph_proof_checker_v3.check_service_operations(
        document=document, message="Quero Vitrifica\u00e7\u00e3o", operations=[operation],
        active_branch_node_ids=[], consumed_service_spans=[{
            "text": "Vitrifica\u00e7\u00e3o", "start": 6, "end": 18,
            "branch_anchor_node_id": "branch:a", "evidence_type": "exact_catalog",
        }],
    )
    assert accepted["valid"], accepted["errors"]
    assert accepted["next_active_branch_node_ids"] == ["branch:a"]


def test_multiple_questions_are_quality_observation_not_a_global_rejection():
    kwargs = _base_check_kwargs()
    kwargs["proposal"] = {
        **kwargs["proposal"],
        "next_question_node_id": None,
        "reply": "Posso explicar. Você quer comparar opções? É para uso próprio?",
    }

    proof = graph_proof_checker_v3.check(**kwargs)

    assert proof["valid"] is True
    assert proof["gating_errors"] == []
    assert proof["question_count"] == 2
    assert proof["observations"] == ["multiple_questions_in_reply"]


def test_explicit_change_evidence_can_only_drop_an_active_branch():
    document = {
        "branch_anchors": ["branch:a"],
        "coordinates": {"branch:a": {"path_checksum": "checksum:a"}},
    }
    operation = {
        "action": "drop", "branch_anchor_node_id": "branch:a",
        "branch_path_checksum": "checksum:a", "evidence_span": "Na verdade",
        "evidence_type": "explicit_change", "resolution_method": "exact_catalog",
    }
    assert ServiceOperation.model_validate(operation).evidence_type == "explicit_change"
    consumed = [{
        "text": "Na verdade", "start": 0, "end": 10,
        "branch_anchor_node_id": "branch:a", "evidence_type": "explicit_change",
    }]
    accepted = graph_proof_checker_v3.check_service_operations(
        document=document, message="Na verdade, quero outro caminho",
        operations=[operation], active_branch_node_ids=["branch:a"],
        consumed_service_spans=consumed,
    )
    assert accepted["valid"], accepted["errors"]

    operation["action"] = "add"
    rejected = graph_proof_checker_v3.check_service_operations(
        document=document, message="Na verdade, quero outro caminho",
        operations=[operation], active_branch_node_ids=[],
        consumed_service_spans=consumed,
    )
    assert "service_explicit_change_only_authorizes_drop:branch:a" in rejected["errors"]


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

from __future__ import annotations

import sys
from pathlib import Path


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

"""Remember valid answers independently from published question ordering."""
from copy import deepcopy

import pytest

from services.graph_proof_checker_v3 import askable_pending_fields, check


OWNER = "persona:test"
CONTRACT = {
    "branch_path_checksum": "path:test", "closure_node_ids": ["branch:test"],
    "fields": [
        {"key": key, "owner_node_id": OWNER, "required": True,
         "accepted_statuses": ["known"],
         "value_schema": {"type": "string", "minLength": 1},
         "depends_on": dependencies}
        for key, dependencies in [("service", []), ("vehicle", ["service"]),
                                  ("name", ["service"])]
    ],
    "questions": {},
}


def turn(message, extracted, ledger=None):
    return check(
        publication={"status": "active", "checksum": "sha256:test",
                     "document_json": {"branch_anchors": ["branch:test"]}},
        contract=CONTRACT,
        ledger=ledger or {"graph_checksum": "sha256:test", "facts": {}},
        proposal={"branch_action": "keep", "branch_anchor_node_id": "branch:test",
                  "branch_path_checksum": "path:test", "extracted_facts": extracted,
                  "claims": [], "next_question_node_id": None,
                  "cited_node_ids": [], "cited_chunk_ids": [],
                  "reply": "Anotado. Como posso ajudar?",
                  "qualification_complete": False, "handoff_requested": False},
        message=message, source_message_id="msg:test",
        package_node_ids={"branch:test"}, package_chunk_ids=set(),
        active_branch_node_id="branch:test", branch_selection_allowed=False,
        branch_switch_allowed=False,
    )


def fact(key, value):
    return {"field_key": key, "owner_node_id": OWNER, "status": "known",
            "value": value, "source_message_id": "msg:test",
            "evidence_span": value, "confidence": 1}


@pytest.mark.parametrize("key,value", [("vehicle", "Fordka"), ("name", "Allan")])
def test_essential_volunteered_answer_is_remembered_before_service(key, value):
    # Extraction belongs to the model: no runtime parser for any spelling.
    proof = turn(value, [fact(key, value)])
    assert proof["accepted_facts"][0]["value"] == value
    assert key not in proof["missing_fields"]
    assert "service" in proof["missing_fields"]
    assert not any("fact_dependency_unsatisfied" in e for e in proof["errors"])


def test_next_turn_retains_vehicle_and_does_not_offer_it_again():
    early = turn("Fordka", [fact("vehicle", "Fordka")])
    ledger = {"graph_checksum": "sha256:test", "facts": {
        "vehicle": early["accepted_facts"][0]}}
    following = turn("polimento", [fact("service", "polimento")], ledger)
    facts = deepcopy(ledger["facts"])
    facts.update({f["field_key"]: f for f in following["accepted_facts"]})
    assert "vehicle" not in following["missing_fields"]
    assert [f["key"] for f in askable_pending_fields(CONTRACT, facts)] == ["name"]
    assert ledger["facts"]["vehicle"]["value"] == "Fordka"


def test_question_dependencies_still_guide_proactive_collection():
    assert [f["key"] for f in askable_pending_fields(CONTRACT, {})] == ["service"]


@pytest.mark.parametrize("change", [
    {"owner_node_id": "persona:other"},
    {"source_message_id": "msg:other"},
    {"evidence_span": "not in inbound"},
    {"value": ""},
])
def test_early_fact_keeps_identity_source_evidence_and_schema_checks(change):
    candidate = {**fact("vehicle", "Fordka"), **change}
    proof = turn("Fordka", [candidate])
    assert proof["accepted_facts"] == []
    assert "vehicle" in proof["missing_fields"]
    assert proof["errors"]

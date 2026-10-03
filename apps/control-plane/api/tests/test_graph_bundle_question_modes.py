from __future__ import annotations

import json
import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle


def _bundle() -> dict:
    return json.loads(
        (REPO_ROOT / "data/graph_bundles/examples/basic-commercial-sdr.json")
        .read_text(encoding="utf-8")
    )


def test_question_modes_project_to_published_fields_without_removing_them():
    bundle = _bundle()
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    persona["data"]["conversation_policy"]["qualification"]["question_modes"] = {
        "need": "required",
        "resale_stage": "optional",
        "volume_interest": "disabled",
    }

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["validation_errors"] == []
    contracts = plan["candidate_document"]["branch_contracts"]
    reseller = next(
        contract for contract in contracts.values()
        if any(field["key"] == "resale_stage" for field in contract["fields"])
    )
    fields = {field["key"]: field for field in reseller["fields"]}
    assert fields["resale_stage"]["question_mode"] == "optional"
    assert fields["resale_stage"]["required"] is False
    assert fields["volume_interest"]["question_mode"] == "disabled"
    assert fields["volume_interest"]["required"] is False
    question = reseller["questions"][fields["volume_interest"]["question_node_id"]]
    assert question["question_mode"] == "disabled"
    assert "volume_interest" not in reseller["required_fields"]


def test_appointment_policy_can_disable_an_authored_question():
    bundle = _bundle()
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    persona["data"]["appointment_policy"] = {
        "question_modes": {"need": "disabled"},
    }

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["validation_errors"] == []
    retail = next(
        contract for contract in plan["candidate_document"]["branch_contracts"].values()
        if any(field["key"] == "need" for field in contract["fields"])
    )
    field = next(field for field in retail["fields"] if field["key"] == "need")
    assert field["question_mode"] == "disabled"
    assert field["question_node_id"] in retail["questions"]
    assert "need" not in retail["required_fields"]


def test_invalid_question_mode_blocks_graphbundle_dry_run():
    bundle = _bundle()
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    persona["data"]["conversation_policy"]["qualification"]["question_modes"] = {
        "need": "sometimes",
    }

    plan = graph_bundle.build_publication_plan(bundle)

    assert plan["disposition"] == "blocked"
    assert "bundle_question_mode_invalid:qualification:need:sometimes" in plan[
        "validation_errors"
    ]

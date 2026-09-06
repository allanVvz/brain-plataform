from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "data"
    / "graph_bundles"
    / "tock-fatal"
    / "sdr-qualification-v17-sales-conversation-repair.json"
)
BUILDER = ROOT / "api" / "scripts" / "build_tock_fatal_v18.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_tock_fatal_v18", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate() -> dict:
    return _module().build(json.loads(SOURCE.read_text(encoding="utf-8")))


def _nodes(bundle: dict) -> dict[str, dict]:
    return {node["id"]: node for node in bundle["nodes"]}


def test_name_remains_first_and_is_still_asked_once():
    nodes = _nodes(_candidate())
    policy = nodes["persona:tock-fatal"]["data"]["conversation_policy"]
    fields = nodes["persona:tock-fatal"]["data"]["qualification"]["fields"]
    by_key = {field["key"]: field for field in fields}

    assert policy["qualification"]["name_question_max_attempts"] == 1
    assert policy["question_policy"]["preferred_field_order_after_purchase_profile"][0] == "nome_cliente"
    assert policy["question_policy"]["never_repeat_nome_cliente_after_branch_switch"] is True
    assert by_key["nome_cliente"]["depends_on"] == ["purchase_profile"]


def test_unanswered_name_no_longer_blocks_other_qualification_fields():
    nodes = _nodes(_candidate())
    persona_fields = nodes["persona:tock-fatal"]["data"]["qualification"]["fields"]
    for field in persona_fields:
        if field["key"] != "nome_cliente":
            assert "nome_cliente" not in field.get("depends_on", [])

    for anchor in ("audience:tock-retail", "audience:tock-reseller"):
        fields = nodes[anchor]["data"]["qualification"]["fields"]
        for field in fields:
            if field["key"] != "purchase_profile":
                assert "nome_cliente" not in field.get("depends_on", [])


def test_branch_local_ordering_and_all_graph_objects_are_preserved():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidate = _module().build(source)
    before = _nodes(source)
    after = _nodes(candidate)

    assert len(candidate["nodes"]) == len(source["nodes"])
    assert len(candidate["edges"]) == len(source["edges"])
    assert candidate["edges"] == source["edges"]
    assert after["audience:tock-retail"]["data"]["qualification"]["fields"][2]["depends_on"] == ["retail_need"]
    assert after["audience:tock-reseller"]["data"]["qualification"]["fields"][2]["depends_on"] == ["resale_stage"]

    changed = {
        node_id for node_id in before
        if before[node_id] != after[node_id]
    }
    assert changed == {"persona:tock-fatal", "audience:tock-retail", "audience:tock-reseller"}


def test_candidate_is_publishable_and_records_the_validator_regression():
    candidate = _candidate()
    metadata = candidate["metadata"]

    assert metadata["purpose"] == "tock_fatal_v18_nonblocking_name_once"
    assert metadata["publication_allowed"] is True
    assert "branch_switch_advances_without_repeating_name" in metadata["conversation_regressions"]

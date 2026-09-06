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
    / "sdr-qualification-v18-nonblocking-name-once.json"
)
BUILDER = ROOT / "api" / "scripts" / "build_tock_fatal_v19.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_tock_fatal_v19", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate() -> dict:
    return _module().build(json.loads(SOURCE.read_text(encoding="utf-8")))


def _nodes(bundle: dict) -> dict[str, dict]:
    return {node["id"]: node for node in bundle["nodes"]}


def test_name_is_still_authored_preferred_and_asked_once_but_optional():
    nodes = _nodes(_candidate())
    persona = nodes["persona:tock-fatal"]["data"]
    policy = persona["conversation_policy"]
    fields = {field["key"]: field for field in persona["qualification"]["fields"]}

    assert policy["qualification"]["name_question_max_attempts"] == 1
    assert policy["question_policy"]["preferred_field_order_after_purchase_profile"][0] == "nome_cliente"
    assert policy["question_policy"]["never_repeat_nome_cliente_after_branch_switch"] is True
    assert policy["question_policy"]["name_is_preferred_optional_once"] is True
    assert fields["nome_cliente"]["required"] is False
    assert fields["nome_cliente"]["question_node_id"] == "faq:tock-customer-name"
    assert fields["nome_cliente"]["depends_on"] == ["purchase_profile"]


def test_only_persona_changes_and_graph_shape_is_preserved():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidate = _module().build(source)
    before = _nodes(source)
    after = _nodes(candidate)

    assert len(candidate["nodes"]) == len(source["nodes"])
    assert len(candidate["edges"]) == len(source["edges"])
    assert candidate["edges"] == source["edges"]
    assert {
        node_id for node_id in before if before[node_id] != after[node_id]
    } == {"persona:tock-fatal"}


def test_candidate_records_nonblocking_completion_regression():
    metadata = _candidate()["metadata"]

    assert metadata["purpose"] == "tock_fatal_v19_optional_name_once"
    assert metadata["publication_allowed"] is True
    assert "unanswered_name_does_not_block_confirmation_or_handoff" in metadata["conversation_regressions"]

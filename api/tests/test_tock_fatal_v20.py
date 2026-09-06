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
    / "sdr-qualification-v19-optional-name-once.json"
)
BUILDER = ROOT / "api" / "scripts" / "build_tock_fatal_v20.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_tock_fatal_v20", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate() -> dict:
    return _module().build(json.loads(SOURCE.read_text(encoding="utf-8")))


def _nodes(bundle: dict) -> dict[str, dict]:
    return {node["id"]: node for node in bundle["nodes"]}


def test_name_is_optional_but_authored_for_one_collection_attempt():
    persona = _nodes(_candidate())["persona:tock-fatal"]["data"]
    fields = {
        field["key"]: field
        for field in persona["qualification"]["fields"]
    }
    policy = persona["conversation_policy"]["question_policy"]

    assert fields["nome_cliente"]["required"] is False
    assert fields["nome_cliente"]["collection_mode"] == "ask_once_optional"
    assert fields["nome_cliente"]["question_node_id"] == "faq:tock-customer-name"
    assert policy["name_is_authored_collect_once"] is True
    assert policy["optional_collection_does_not_change_completion"] is True


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


def test_candidate_records_optional_collect_once_regression():
    metadata = _candidate()["metadata"]

    assert metadata["purpose"] == "tock_fatal_v20_optional_name_collect_once"
    assert metadata["publication_allowed"] is True
    assert "optional_name_question_is_recorded_once" in metadata["conversation_regressions"]

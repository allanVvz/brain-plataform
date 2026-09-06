from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v20-optional-name-collect-once.json"
BUILDER = ROOT / "api/scripts/build_tock_fatal_v21.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_tock_fatal_v21", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_confirmation_and_handoff_are_authored():
    result = _module().build(json.loads(SOURCE.read_text(encoding="utf-8")))
    nodes = {node["id"]: node for node in result["nodes"]}
    policy = nodes["persona:tock-fatal"]["data"]["conversation_policy"]
    handoff = nodes["rule:tock-safe-handoff"]["data"]["handoff_rule"]

    assert policy["confirmation_and_handoff"]["handoff_pre_notice_required"] is True
    assert handoff["condition"] == "qualification_complete"
    assert handoff["pre_notice_required"] is True
    assert result["metadata"]["purpose"] == "tock_fatal_v21_confirmation_then_handoff"


def test_only_persona_and_handoff_rule_change():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    result = _module().build(source)
    before = {node["id"]: node for node in source["nodes"]}
    after = {node["id"]: node for node in result["nodes"]}

    assert result["edges"] == source["edges"]
    assert {key for key in before if before[key] != after[key]} == {
        "persona:tock-fatal", "rule:tock-safe-handoff",
    }

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v21-confirmation-then-handoff.json"
BUILDER = ROOT / "api/scripts/build_tock_fatal_v22.py"


def test_retail_answers_must_be_persisted_before_reply():
    spec = importlib.util.spec_from_file_location("build_tock_fatal_v22", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.build(json.loads(SOURCE.read_text(encoding="utf-8")))
    fields = {
        field["key"]: field
        for node in result["nodes"]
        for field in (node.get("data", {}).get("qualification") or {}).get("fields", [])
        if field.get("key") in {"retail_need", "retail_style"}
    }
    for key in ("retail_need", "retail_style"):
        assert fields[key]["validation"]["extraction_required_when_expected"] is True
        assert fields[key]["validation"]["acknowledgement_requires_fact"] is True

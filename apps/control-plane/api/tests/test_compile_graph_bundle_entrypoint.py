from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "api" / "scripts" / "compile_graph_bundle.py"


def test_publication_plan_entrypoint_imports_production_control_plane():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"apps" / "control-plane" / "api"' in source
    assert "API_DIR = Path(__file__).resolve().parents[1]" not in source


def test_publication_plan_entrypoint_help_is_runnable():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PublicationPlan" in completed.stdout


def test_shipping_only_sales_bundle_compiles_against_active_baseline():
    baseline = ROOT / "data/graph_bundles/tock-fatal/unified-message-queue-v38.json"
    candidate = ROOT / "data/graph_bundles/tock-fatal/unified-message-queue-v39-shipping-only.json"
    bundle = json.loads(candidate.read_text(encoding="utf-8"))
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    fields = {field["key"] for field in persona["data"]["qualification"]["fields"]}
    assert persona["data"]["business_model"] == "sales"
    assert "forma_recebimento" not in fields
    assert "appointment_policy" not in persona["data"]
    assert not any(node["id"] == "faq:tock-store-visit" for node in bundle["nodes"])
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(candidate), "--against-bundle", str(baseline), "--next-version", "39"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    plan = json.loads(completed.stdout)
    assert plan["validation_errors"] == []
    assert plan["runtime_checksum"] != bundle["metadata"]["baseline_publication"]["checksum"]

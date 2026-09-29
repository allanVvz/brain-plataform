from __future__ import annotations

import subprocess
import sys
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


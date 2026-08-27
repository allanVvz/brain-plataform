from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "vps" / "environment_evidence.py"


def test_environment_evidence_is_structured_and_reusable(tmp_path: Path):
    output = tmp_path / "environment.json"
    result = subprocess.run([
        sys.executable, str(SCRIPT), "collect", "--output", str(output),
        "--disk-percent", "20", "--disk-limit", "85",
        "--unsafe-table-grants", "0", "--unsafe-function-grants", "0",
        "--tables-without-rls", "0", "--backup-ok", "true",
        "--restore-ok", "true",
    ], capture_output=True, text=True, env=os.environ)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "production_environment_evidence"
    assert payload["ok"] is True
    verified = subprocess.run([
        sys.executable, str(SCRIPT), "verify", "--input", str(output), "--strict",
    ], capture_output=True, text=True, env=os.environ)
    assert verified.returncode == 0, verified.stdout

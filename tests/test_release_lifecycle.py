from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "vps" / "release_lifecycle.py"
SHA = "a" * 40
PREVIOUS = "b" * 40


def run_lifecycle(tmp_path: Path, *args: str, ok: bool = True):
    env = {**os.environ, "DEPLOY_STATE_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    assert (result.returncode == 0) is ok, result.stderr
    return result


def prepare(tmp_path: Path):
    run_lifecycle(
        tmp_path,
        "prepare",
        "--candidate-sha", SHA,
        "--previous-sha", PREVIOUS,
        "--impact-class", "conversational",
    )


def test_lifecycle_is_durable_idempotent_and_authorized(tmp_path: Path):
    prepare(tmp_path)
    run_lifecycle(tmp_path, "pause-claims", "--reason", "controlled deploy")
    control_dir = tmp_path / "control"
    marker = control_dir / "claims-paused.json"
    assert marker.exists()
    if os.name != "nt":
        assert stat.S_IMODE(control_dir.stat().st_mode) == 0o755
        assert stat.S_IMODE(marker.stat().st_mode) == 0o644
    for stage in (
        "queue_drained", "migration_complete", "candidate_healthy",
        "awaiting_resume_authorization",
    ):
        run_lifecycle(tmp_path, "advance", "--stage", stage)
    run_lifecycle(
        tmp_path, "resume-claims", "--candidate-sha", SHA, ok=False,
    )
    run_lifecycle(
        tmp_path, "authorize-resume", "--actor", "operator",
        "--reason", "release reviewed",
    )
    run_lifecycle(tmp_path, "resume-claims", "--candidate-sha", SHA)
    assert not (tmp_path / "control" / "claims-paused.json").exists()
    state = json.loads((tmp_path / "lifecycle.json").read_text(encoding="utf-8"))
    assert state["resume_authorization"]["actor"] == "operator"
    assert (tmp_path / "lifecycle-events.ndjson").read_text(encoding="utf-8").count("\n") >= 8


def test_unfinished_release_cannot_be_replaced(tmp_path: Path):
    prepare(tmp_path)
    result = run_lifecycle(
        tmp_path,
        "prepare",
        "--candidate-sha", "c" * 40,
        "--previous-sha", SHA,
        "--impact-class", "api",
        ok=False,
    )
    assert "unfinished" in result.stderr

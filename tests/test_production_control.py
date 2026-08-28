from __future__ import annotations

import asyncio
import json
from pathlib import Path

from services import production_control
from workers.base_worker import BaseWorker


def test_claim_pause_marker_is_fail_closed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PRODUCTION_CONTROL_DIR", str(tmp_path))
    (tmp_path / "claims-paused.json").write_text("not-json", encoding="utf-8")

    assert production_control.claims_pause() == {
        "paused": True,
        "reason": "invalid_claims_pause_marker",
    }


def test_valid_pause_marker_and_absence(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PRODUCTION_CONTROL_DIR", str(tmp_path))
    marker = tmp_path / "claims-paused.json"
    marker.write_text(json.dumps({"paused": True, "reason": "deploy"}), encoding="utf-8")
    assert production_control.claims_are_paused() is True
    marker.unlink()
    assert production_control.claims_are_paused() is False


def test_stop_requested_before_start_exits_without_claiming():
    class Worker(BaseWorker):
        interval = 60

        def __init__(self):
            super().__init__()
            self.cycles = 0

        def _run_cycle(self) -> None:
            self.cycles += 1

    worker = Worker()
    worker.request_stop()
    asyncio.run(worker.start())
    assert worker.cycles == 0

from __future__ import annotations

import sys
import time
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from workers.wa_validator_worker import WaValidatorWorker
from workers import wa_validator_worker as worker_module


def test_worker_executes_claimed_session_outside_api(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker_module.supabase_client,
        "claim_next_wa_validator_session",
        lambda worker_id: {
            "claimed": True,
            "session": {"id": "session-1", "status": "running"},
        },
    )

    async def _run(session_id, *, claimed_session):
        calls.append((session_id, claimed_session["status"]))
        return claimed_session

    monkeypatch.setattr(worker_module.wa_validator_service, "run_session_direct", _run)
    worker = WaValidatorWorker()
    worker._last_retention = time.monotonic()

    worker._run_cycle()

    assert calls == [("session-1", "running")]


def test_worker_retention_defaults_to_dry_run(monkeypatch):
    calls = []
    monkeypatch.delenv("WA_VALIDATOR_RETENTION_ENABLED", raising=False)
    monkeypatch.setattr(
        worker_module.supabase_client,
        "claim_next_wa_validator_session",
        lambda _worker_id: {"claimed": False, "state": "empty"},
    )
    monkeypatch.setattr(
        worker_module.wa_validator_service,
        "cleanup_expired_artifacts",
        lambda **kwargs: calls.append(kwargs) or {"lead_count": 0, "session_count": 0},
    )
    monkeypatch.setattr(worker_module.sre_logger, "info", lambda *_args, **_kwargs: None)
    worker = WaValidatorWorker()

    worker._run_cycle()

    assert calls == [{"hours": 12, "dry_run": True}]

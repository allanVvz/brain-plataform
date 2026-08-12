from workers.inactivity_recovery_worker import InactivityRecoveryWorker


def test_worker_is_disabled_without_explicit_enable(monkeypatch):
    monkeypatch.delenv("INACTIVITY_RECOVERY_ENABLED", raising=False)
    monkeypatch.setattr(
        "workers.inactivity_recovery_worker.supabase_client.list_inactivity_recovery_candidates",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not scan")),
    )
    InactivityRecoveryWorker()._run_cycle()


def test_dry_run_does_not_claim_or_write(monkeypatch):
    monkeypatch.setenv("INACTIVITY_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("INACTIVITY_RECOVERY_DRY_RUN", "true")
    monkeypatch.setenv("INACTIVITY_RECOVERY_ENABLED_FROM", "2026-08-12T00:00:00Z")
    monkeypatch.setattr(
        "workers.inactivity_recovery_worker.supabase_client.list_inactivity_recovery_candidates",
        lambda **_: [{"id": "inbound-1"}],
    )
    monkeypatch.setattr(
        "workers.inactivity_recovery_worker.supabase_client.claim_inactivity_recovery_candidate",
        lambda **_: (_ for _ in ()).throw(AssertionError("dry-run must not claim")),
    )
    InactivityRecoveryWorker()._run_cycle()

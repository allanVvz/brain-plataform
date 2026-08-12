from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/117_wa_validator_queue_and_retention.sql").read_text(
    encoding="utf-8",
)
ROUTE = (ROOT / "api/routes/wa_validator.py").read_text(encoding="utf-8")
WORKER = (ROOT / "api/workers/wa_validator_worker.py").read_text(encoding="utf-8")


def test_validator_queue_claim_is_atomic_and_skips_locked_rows():
    assert "data->>'status'='queued'" in SQL
    assert "FOR UPDATE SKIP LOCKED" in SQL
    assert "'status','running'" in SQL


def test_run_direct_route_only_queues_and_worker_owns_long_execution():
    route = ROUTE[ROUTE.index('@router.post("/run-direct")'):ROUTE.index('@router.get("/retention")')]
    assert "enqueue_session_direct" in route
    assert "await wa_validator_service.run_session_direct" not in route
    assert "asyncio.run(" in WORKER
    assert "claimed_session=session" in WORKER


def test_retention_is_locked_canonical_and_aborts_real_outbounds():
    assert "pg_advisory_xact_lock" in SQL
    assert "metadata->'validation'->>'is_validation'" in SQL
    assert "metadata->>'validation_session_id'" in SQL
    assert "lead_id,'') LIKE 'validator\\_%'" in SQL
    assert "l.nome" not in SQL
    assert "validator retention aborted: real outbound linkage" in SQL
    assert "metadata->'identities'->>'remote_jid'" in SQL
    assert "metadata->'identities'->>'remote_jid_alt'" in SQL
    assert "OR b.locked_at IS NOT NULL" in SQL
    assert "'pending_send','retry','awaiting_proof'" in SQL
    assert "p_dry_run" in SQL


def test_retention_preserves_recent_rows_and_emits_one_aggregate_event():
    assert "l.created_at < v_cutoff" in SQL
    assert "s.created_at < v_cutoff" in SQL
    assert SQL.count("'wa_validator_retention_applied'") == 1


def test_retention_preserves_old_non_terminal_session_leads():
    assert "FROM public.wa_validator_sessions protected" in SQL
    assert "protected.created_at >= v_cutoff" in SQL
    assert "coalesce(protected.data->>'status','') IN (" in SQL
    assert "'queued','starting','running'" in SQL
    assert "nullif(l.metadata->'validation'->>'session_id','')" in SQL


def test_retention_http_endpoint_is_always_read_only():
    route = ROUTE[ROUTE.index('@router.get("/retention")'):ROUTE.index('@router.post("/analyze")')]
    assert "dry_run=True" in route
    assert "dry_run:" not in route

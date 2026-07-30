from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "supabase" / "migrations" / "065_whatsapp_monotonic_delivery.sql"
).read_text(encoding="utf-8").lower()
COMMIT_MIGRATION = (
    ROOT / "supabase" / "migrations" / "066_conversation_commit_idempotency.sql"
).read_text(encoding="utf-8").lower()


def test_hotfix_reuses_existing_tables_and_has_atomic_envelope():
    assert "create table" not in MIGRATION
    assert "enqueue_whatsapp_envelope" in MIGRATION
    assert "on conflict (idempotency_key) do nothing" in MIGRATION
    assert "insert into public.messages" in MIGRATION


def test_expired_attempts_are_quarantined_before_claim():
    claim = MIGRATION.split(
        "create or replace function public.claim_whatsapp_buffer", 1
    )[1]
    assert "quarantine_expired_whatsapp_attempts" in claim
    assert "decision_attempt_started_at" in claim
    assert "provider_attempt_started_at" in claim
    assert "waiting_human" in MIGRATION


def test_delivery_reconciliation_is_binding_scoped_and_monotonic():
    reconcile = MIGRATION.split(
        "create or replace function public.reconcile_whatsapp_delivery", 1
    )[1].split(
        "create or replace function public.complete_whatsapp_outbound_result", 1
    )[0]
    assert reconcile.count("channel_binding_id = p_binding_id") >= 8
    assert "and status = 'sent'" in reconcile
    assert "and status = 'delivered'" in reconcile
    assert "status not in ('delivered', 'read', 'failed')" in reconcile
    assert "whatsapp.delivery_ack_ignored" in reconcile


def test_three_distinct_recent_violations_pause_the_binding():
    assert "count(distinct payload->>'violation_key')" in MIGRATION
    assert "now() - interval '5 minutes'" in MIGRATION
    assert "if v_count >= 3" in MIGRATION
    assert "'safety_paused', true" in MIGRATION
    assert "connection_status = 'safety_paused'" in MIGRATION


def test_conversation_callback_claim_reuses_the_inbound_lock():
    assert "create table" not in COMMIT_MIGRATION
    assert "claim_conversation_commit" in COMMIT_MIGRATION
    assert "complete_conversation_commit" in COMMIT_MIGRATION
    assert "from public.lead_buffer" in COMMIT_MIGRATION
    assert "for update" in COMMIT_MIGRATION
    assert "channel_binding_id = p_binding_id" in COMMIT_MIGRATION
    assert "v_buffer.lead_ref is distinct from p_lead_ref" in COMMIT_MIGRATION
    assert "'{conversation_commit}'" in COMMIT_MIGRATION
    assert "'status', 'completed'" in COMMIT_MIGRATION

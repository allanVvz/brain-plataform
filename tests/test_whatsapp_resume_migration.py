from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resume_requeues_only_inbound_turns_without_completed_commit():
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "092_resume_only_uncommitted_inbound.sql"
    ).read_text(encoding="utf-8")

    assert "direction = 'inbound'" in migration
    assert "status = 'waiting_human'" in migration
    assert "payload->'conversation_commit' IS NULL" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "decision_attempt_started_at" in migration


def test_resume_migration_does_not_delete_or_rewrite_conversation_history():
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "092_resume_only_uncommitted_inbound.sql"
    ).read_text(encoding="utf-8").upper()

    assert "DELETE FROM" not in migration
    assert "UPDATE PUBLIC.MESSAGES" not in migration
    assert "UPDATE PUBLIC.LEADS" not in migration


def test_resume_requeue_stagger_preserves_uncommitted_inbound_filter():
    """Migration 110 (fixing 109) re-defines the same function to space out
    available_at.

    It must keep every safety property migration 092 established (same
    candidate filter, same lock mode, same idempotency-marker cleanup) —
    staggering is additive, not a behavior regression.
    """
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "110_fix_stagger_requeue_for_update.sql"
    ).read_text(encoding="utf-8")

    assert "direction = 'inbound'" in migration
    assert "status = 'waiting_human'" in migration
    assert "payload->'conversation_commit' IS NULL" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "decision_attempt_started_at" in migration
    # The actual staggering: available_at is offset per row instead of a flat now().
    assert "row_number() OVER" in migration
    assert "now() + ((candidates.rn - 1)" in migration


def test_resume_requeue_stagger_does_not_combine_for_update_with_window_function():
    """Regression test for the 109 bug (2026-08-10).

    Postgres rejects "FOR UPDATE" in the same SELECT as a window function
    ("FOR UPDATE is not allowed with window functions") -- 109 combined
    row_number() OVER (...) and FOR UPDATE SKIP LOCKED in one CTE, so every
    call to requeue_waiting_human_whatsapp_buffer raised and the backlog
    never actually got requeued, even though resume_lead() reported success.
    The locking CTE must not itself compute row_number().
    """
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "110_fix_stagger_requeue_for_update.sql"
    ).read_text(encoding="utf-8")

    locked_cte = migration.split("locked AS (", 1)[1].split(")", 1)[0]
    assert "FOR UPDATE SKIP LOCKED" in locked_cte
    assert "row_number()" not in locked_cte


def test_resume_requeue_stagger_does_not_delete_or_rewrite_conversation_history():
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "110_fix_stagger_requeue_for_update.sql"
    ).read_text(encoding="utf-8").upper()

    assert "DELETE FROM" not in migration
    assert "UPDATE PUBLIC.MESSAGES" not in migration
    assert "UPDATE PUBLIC.LEADS" not in migration

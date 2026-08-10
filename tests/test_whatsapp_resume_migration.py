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
    """Migration 109 re-defines the same function to space out available_at.

    It must keep every safety property migration 092 established (same
    candidate filter, same lock mode, same idempotency-marker cleanup) —
    staggering is additive, not a behavior regression.
    """
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "109_stagger_requeue_on_resume.sql"
    ).read_text(encoding="utf-8")

    assert "direction = 'inbound'" in migration
    assert "status = 'waiting_human'" in migration
    assert "payload->'conversation_commit' IS NULL" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "decision_attempt_started_at" in migration
    # The actual staggering: available_at is offset per row instead of a flat now().
    assert "row_number() OVER" in migration
    assert "now() + ((candidates.rn - 1)" in migration


def test_resume_requeue_stagger_does_not_delete_or_rewrite_conversation_history():
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "109_stagger_requeue_on_resume.sql"
    ).read_text(encoding="utf-8").upper()

    assert "DELETE FROM" not in migration
    assert "UPDATE PUBLIC.MESSAGES" not in migration
    assert "UPDATE PUBLIC.LEADS" not in migration

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

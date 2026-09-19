from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "supabase" / "migrations" / "148_reactivation_pair_revision_and_projection.sql"
).read_text(encoding="utf-8").lower()


def test_regeneration_uses_a_new_atomic_pair_identity_without_new_tables():
    assert "create table" not in MIGRATION
    assert "pg_advisory_xact_lock" in MIGRATION
    assert "coalesce(max(queue_revision),0)+1" in MIGRATION
    assert "select max(queue_revision) into v_latest_revision" in MIGRATION
    assert "'{idempotency_key}'" in MIGRATION
    assert "':apology:1:r'" in MIGRATION
    assert "':context:2:r'" in MIGRATION
    assert "status='superseded'" in MIGRATION


def test_queue_projection_returns_the_two_actual_predecessors_for_a_pair():
    projection = MIGRATION.split("create or replace function public.list_actionable_message_queue_v1", 1)[1]
    assert "latest_message.content as latest_message" in projection
    assert "first_preview.content as first_preview_text" in projection
    assert "'latest_message',latest_message" in projection
    assert "'first_preview_text',first_preview_text" in projection
    assert "when queue_sequence=2 then first_preview_text" in projection
    assert "s.status='superseded' then null" in projection

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "137_canonical_asset_content_dedup.sql"
)


def test_asset_content_dedup_migration_contract():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "add column if not exists content_sha256 text" in sql
    assert "content_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "alter column approval_status set default 'pending'" in sql
    assert "create unique index if not exists uq_assets_persona_content_sha256" in sql
    assert "on public.assets(persona_id, content_sha256)" in sql
    assert "where persona_id is not null and content_sha256 is not null" in sql
    assert "create table" not in sql

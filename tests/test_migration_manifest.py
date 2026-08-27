from pathlib import Path

from scripts.migration_manifest import build_manifest, verify_applied


def test_manifest_is_dynamic_and_checksum_changes_with_sql(tmp_path: Path):
    first = tmp_path / "001_first.sql"
    second = tmp_path / "002_second.sql"
    first.write_text("select 1;", encoding="utf-8")
    second.write_text("select 2;", encoding="utf-8")
    before = build_manifest(tmp_path)
    assert before["count"] == 2
    assert before["latest"] == "002_second.sql"
    assert verify_applied(before, {"001_first.sql", "002_second.sql"}) == []
    assert verify_applied(before, {"001_first.sql"}) == ["002_second.sql"]
    second.write_text("select 3;", encoding="utf-8")
    after = build_manifest(tmp_path)
    assert after["manifest_sha256"] != before["manifest_sha256"]


def test_production_migration_image_requires_embedded_manifest():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "infra" / "migrate.Dockerfile").read_text(encoding="utf-8")
    assert "REQUIRE_MIGRATION_MANIFEST=true" in dockerfile
    assert "MIGRATION_MANIFEST.json" in dockerfile

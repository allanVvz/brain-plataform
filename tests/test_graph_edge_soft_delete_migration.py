from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "048_allow_invalid_legacy_edge_deactivation.sql"


def test_edge_validator_only_runs_for_active_new_state():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "drop trigger if exists trg_validate_knowledge_edge_contract" in sql
    assert "before insert or update on public.knowledge_edges" in sql
    assert "new.metadata->>'active'" in sql
    assert "= true" in sql
    assert "execute function public.validate_knowledge_edge_contract()" in sql


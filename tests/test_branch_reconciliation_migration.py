from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_branch_reconciliation_is_atomic_and_service_role_only():
    sql = (ROOT / "supabase" / "migrations" /
           "116_reconcile_active_conversation_branches.sql").read_text(encoding="utf-8")
    lowered = " ".join(sql.lower().split())
    assert "set state='dropped', completed_at=now()" in lowered
    assert "not (branch_anchor_node_id = any(v_active_branches))" in lowered
    assert "foreach v_branch in array v_active_branches" in lowered
    assert "from public, anon, authenticated" in lowered
    assert "to service_role" in lowered

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "138_resume_binding_without_releasable_backlog.sql"
).read_text(encoding="utf-8").lower()
ROUTE = (
    ROOT / "apps" / "control-plane" / "api" / "routes" / "release_queue.py"
).read_text(encoding="utf-8")


def test_empty_resume_is_atomic_audited_and_persona_scoped():
    assert "create or replace function public.resume_safety_paused_binding_v1" in MIGRATION
    assert "where id = p_binding_id" in MIGRATION
    assert "and persona_id = p_persona_id" in MIGRATION
    assert "set connection_status = 'connected'" in MIGRATION
    assert "'safety_paused', false" in MIGRATION
    assert "'safety_resume_empty_backlog', true" in MIGRATION
    assert "'whatsapp.binding_resumed_without_releasable_backlog'" in MIGRATION
    assert "'item_count', 0" in MIGRATION


def test_empty_resume_rpc_is_service_role_only():
    signature = "resume_safety_paused_binding_v1(\n  uuid, uuid, text, text, text, uuid\n)"
    assert f"revoke all on function public.{signature}" in MIGRATION
    assert f"grant execute on function public.{signature}" in MIGRATION


def test_route_uses_empty_resume_only_after_canonical_candidate_filter():
    candidate_pos = ROUTE.index("build_safety_paused_batch_candidates")
    empty_pos = ROUTE.index("if not lead_buffer_ids")
    resume_pos = ROUTE.index("resume_safety_paused_binding_without_backlog")
    assert candidate_pos < empty_pos < resume_pos

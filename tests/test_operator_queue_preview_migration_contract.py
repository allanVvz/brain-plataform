from pathlib import Path


SQL = (Path(__file__).resolve().parents[1] / "supabase/migrations/157_operator_replay_blocked_inbound.sql").read_text(encoding="utf-8").lower()


def test_operator_replay_is_explicit_atomic_and_inert():
    claim = SQL.split("create or replace function public.claim_queue_operator_preview_v1", 1)[1]
    claim = claim.split("create or replace function public.release_queue_operator_preview_claim_v1", 1)[0]
    assert "status not in ('waiting_human','dead_letter')" in claim
    assert "conversation_turn_proofs" in claim
    assert "already has a decision or outbound" in claim
    assert "newer.id)>(v_row.created_at,v_row.id)" in claim
    assert "queue_preview_claim_mode','operator_replay'" in claim
    assert "ai_paused=false,handoff_level='none'" in claim
    assert "pending_reconfirmation" in claim
    assert "messaging.queue.operator_preview_claimed" in claim
    assert "insert into public.messages" not in claim
    assert "insert into public.lead_buffer" not in claim


def test_failed_operator_preview_restores_prior_pause_and_handoff_state():
    release = SQL.split("create or replace function public.release_queue_operator_preview_claim_v1", 1)[1]
    release = release.split("create or replace function public.list_actionable_message_queue_v1", 1)[0]
    assert "operator_preview_prior_ai_paused" in release
    assert "operator_preview_prior_handoff_level" in release
    assert "conversation_turn_proofs" in release
    assert "messaging.queue.operator_preview_failed" in release


def test_projection_exposes_generate_preview_only_for_blocked_inbound_fallback():
    wrapper = SQL.split("create or replace function public.list_actionable_message_queue_v1", 1)[1]
    assert "queue_state'='blocked'" in wrapper
    assert "proof_id' is null" in wrapper
    assert "can_generate_preview',true" in wrapper
    assert "generate_preview_reason" in wrapper
    assert "create table" not in SQL

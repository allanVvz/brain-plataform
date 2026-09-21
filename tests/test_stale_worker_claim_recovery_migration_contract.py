from pathlib import Path


SQL = (Path(__file__).resolve().parents[1] / "supabase/migrations/159_recover_stale_worker_claim.sql").read_text(encoding="utf-8").lower()


def _claim_body() -> str:
    body = SQL.split("create or replace function public.claim_queue_operator_preview_v1", 1)[1]
    return body.split("create or replace function public.list_actionable_message_queue_v1", 1)[0]


def test_operator_preview_accepts_a_stale_worker_level_processing_claim():
    claim = _claim_body()
    assert "status not in ('waiting_human','dead_letter','processing')" in claim
    assert "v_row.status='processing'" in claim
    assert "v_row.locked_at is null or v_row.locked_at > now() - interval '5 minutes'" in claim
    assert "inbound worker claim is still processing" in claim


def test_stale_worker_claim_recovery_requires_no_proof_or_outbound_before_release():
    claim = _claim_body()
    processing_branch = claim.split("if v_row.status='processing' then", 1)[1]
    processing_branch = processing_branch.split("else", 1)[0]
    assert "conversation_turn_proofs" in processing_branch
    assert "already has a decision or outbound" in processing_branch
    assert "messaging.queue.stale_worker_claim_released" in processing_branch


def test_stale_worker_claim_recovery_clears_every_in_flight_marker():
    claim = _claim_body()
    processing_branch = claim.split("if v_row.status='processing' then", 1)[1]
    processing_branch = processing_branch.split("else", 1)[0]
    for marker in (
        "'conversation_commit'",
        "'decision_attempt_started_at'",
        "'decision_attempt_worker'",
        "'provider_attempt_started_at'",
        "'provider_attempt_worker'",
    ):
        assert marker in processing_branch, f"missing cleared marker: {marker}"


def test_existing_conversation_commit_recovery_branch_is_preserved():
    claim = _claim_body()
    assert "inbound conversation commit is still processing" in claim
    assert "messaging.queue.stale_commit_released" in claim
    assert "inbound already has a conversation commit" in claim


def test_final_checks_still_guard_lead_scope_supersession_and_pause():
    claim = _claim_body()
    assert "inbound lead scope changed" in claim
    assert "inbound is superseded by a newer customer message" in claim
    assert "inbound is paused in the operational queue" in claim
    assert "insert into public.messages" not in claim
    assert "insert into public.lead_buffer" not in claim


def test_projection_relabels_a_stale_processing_inbound_as_blocked_and_recoverable():
    wrapper = SQL.split("create or replace function public.list_actionable_message_queue_v1", 1)[1]
    assert "queue_state'='pending_response'" in wrapper
    assert "status='processing' and lb.locked_at < now() - interval '5 minutes'" in wrapper
    assert "can_generate_preview',true" in wrapper
    assert "'status','blocked','queue_state','blocked'" in wrapper


def test_no_new_table_or_destructive_statement():
    assert "create table" not in SQL
    assert "drop table" not in SQL
    assert "delete from" not in SQL
    assert "truncate" not in SQL

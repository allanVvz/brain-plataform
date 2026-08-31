from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/133_conversation_turn_exactly_once_v5.sql").read_text(
    encoding="utf-8"
)


def test_v5_locks_and_replays_before_any_outbox_creation():
    lookup = SQL.index("FROM public.conversation_turn_proofs")
    delegate = SQL.index("public.commit_graph_turn_and_outbox_v4")
    assert "pg_advisory_xact_lock" in SQL[:lookup]
    assert lookup < delegate
    assert "'deduplicated',true" in SQL
    assert "journey_action=none" in SQL


def test_v5_records_only_questions_with_an_outbound():
    assert "CASE WHEN p_outbound_buffer IS NULL THEN '[]'::jsonb" in SQL
    assert "'asked_field_keys',v_asked_field_keys" in SQL
    assert "'asked_question_node_ids',v_asked_question_ids" in SQL
    assert "model_reply_preserved" in SQL


def test_v5_surfaces_non_secret_reason_detail_and_hint():
    assert "reason_class" in SQL
    assert "original_sqlstate" in SQL
    assert "PG_EXCEPTION_DETAIL" in SQL
    assert "PG_EXCEPTION_HINT" in SQL
    assert "lookup_existing_proof_before_retry" in SQL


def test_retry_release_is_function_only_and_clears_transient_claim_markers():
    assert "release_conversation_commit_for_retry_v1" in SQL
    assert "decision_attempt_started_at" in SQL
    assert "decision_attempt_worker" in SQL
    assert "WHERE canonical_inbound_id=p_canonical_inbound_id" in SQL
    assert "'status','completed'" in SQL

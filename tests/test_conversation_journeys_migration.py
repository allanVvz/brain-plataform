from pathlib import Path


SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
       "118_conversation_journeys_and_sales_conversions.sql").read_text(encoding="utf-8")


def test_journeys_are_current_once_and_ledgers_are_scoped():
    assert "CREATE TABLE IF NOT EXISTS public.conversation_journeys" in SQL
    assert "idx_conversation_journeys_one_current" in SQL
    assert "WHERE is_current" in SQL
    assert "ADD COLUMN IF NOT EXISTS journey_id" in SQL
    assert "DROP CONSTRAINT IF EXISTS conversation_ledgers_persona_id_lead_ref_key" in SQL
    assert "idx_conversation_ledgers_per_journey" in SQL
    assert "UPDATE public.conversation_turn_proofs p SET journey_id=l.journey_id" in SQL


def test_legacy_backfill_never_infers_confirmation_or_conversion():
    backfill = SQL[SQL.index("-- Backfill exactly one journey"):SQL.index("ALTER TABLE public.conversation_ledgers")]
    assert "'legacy_backfill'" in backfill
    assert "'collecting'" in backfill
    assert "qualification_confirmed_at" not in backfill
    assert "sales_conversions" not in backfill


def test_purchase_and_qualification_both_evaluate_same_atomic_gate():
    assert "record_purchase_completed_v1" in SQL
    assert "mark_conversation_journey_qualification_v1" in SQL
    assert SQL.count("maybe_open_next_conversation_journey_v1(") >= 3
    assert "conversion_type='purchase' AND c.completed_at IS NOT NULL" in SQL
    assert "qualification_confirmed_at IS NULL" in SQL
    assert "previous_journey_id=v_origin.id" in SQL


def test_conversion_history_is_non_destructive_and_idempotent():
    assert "UNIQUE(persona_id,source,idempotency_key)" in SQL
    assert "transition_history" in SQL
    assert "idempotency_history" in SQL
    transition = SQL[SQL.index("transition_sales_conversion_status_v1"):]
    assert "DELETE FROM public.sales_conversions" not in transition
    assert "DELETE FROM public.conversation_journeys" not in transition


def test_recovery_is_locking_non_proactive_and_pause_safe():
    claim = SQL[SQL.index("claim_inactivity_recovery_candidate_v1"):]
    assert "FOR UPDATE SKIP LOCKED" in claim
    assert "pending_response_detected" in claim
    assert "status='retry'" in claim
    assert "INSERT INTO public.messages" not in claim
    assert "direction='outbound'" in claim


def test_trigger_functions_are_not_publicly_executable():
    assert (
        "REVOKE ALL ON FUNCTION public.assign_conversation_ledger_journey_v1() "
        "FROM PUBLIC,anon,authenticated;"
    ) in SQL
    assert (
        "REVOKE ALL ON FUNCTION public.assign_conversation_proof_journey_v1() "
        "FROM PUBLIC,anon,authenticated;"
    ) in SQL
    assert "trg_project_conversation_journey_from_proof_v1" in SQL
    assert (
        "REVOKE ALL ON FUNCTION public.project_conversation_journey_from_proof_v1() "
        "FROM PUBLIC,anon,authenticated;"
    ) in SQL

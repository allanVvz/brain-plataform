from pathlib import Path


SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
       "118_conversation_journeys_and_sales_conversions.sql").read_text(encoding="utf-8")
STATE_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
             "121_sdr_journey_state_machine.sql").read_text(encoding="utf-8")
POST_HANDOFF_SQL = (Path(__file__).parents[1] / "supabase" / "migrations" /
                    "122_preserve_post_handoff_journey.sql").read_text(encoding="utf-8")


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


def test_legacy_purchase_gate_is_superseded_without_opening_a_new_journey():
    assert "record_purchase_completed_v1" in SQL
    assert "mark_conversation_journey_qualification_v1" in SQL
    assert SQL.count("maybe_open_next_conversation_journey_v1(") >= 3
    assert "conversion_type='purchase' AND c.completed_at IS NOT NULL" in SQL
    assert "qualification_confirmed_at IS NULL" in SQL
    assert "previous_journey_id=v_origin.id" in SQL
    gate = STATE_SQL[
        STATE_SQL.index("maybe_open_next_conversation_journey_v1"):
        STATE_SQL.index("assign_conversation_ledger_journey_v1")
    ]
    assert "'new_journey_created',false" in gate
    assert "current_request_remains_open" in gate
    assert "INSERT INTO public.conversation_journeys" not in gate


def test_conversion_history_is_non_destructive_and_idempotent():
    assert "UNIQUE(persona_id,source,idempotency_key)" in SQL
    assert "transition_history" in SQL
    assert "idempotency_history" in SQL
    transition = SQL[SQL.index("transition_sales_conversion_status_v1"):]
    assert "DELETE FROM public.sales_conversions" not in transition
    assert "DELETE FROM public.conversation_journeys" not in transition
    assert "ALTER TABLE public.conversation_journeys ENABLE ROW LEVEL SECURITY" in SQL
    assert "ALTER TABLE public.sales_conversions ENABLE ROW LEVEL SECURITY" in SQL


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


def test_state_machine_records_idempotent_events_and_closes_only_on_terminal_outcome():
    assert "record_conversation_journey_event_v1" in STATE_SQL
    for event in (
        "sale_recorded", "appointment_booked", "delivered",
        "service_completed", "cancelled",
    ):
        assert event in STATE_SQL
    assert "lead_first_conversion" in STATE_SQL
    assert "'recurrence',NOT v_first" in STATE_SQL
    assert "idempotency key belongs to a different journey event" in STATE_SQL
    assert "is_current=false,state='closed'" in STATE_SQL
    assert "new_demand_after_closed_request" in STATE_SQL
    assert "CREATE TABLE" not in STATE_SQL


def test_context_batch_and_cas_repair_are_current_journey_scoped():
    assert "JOIN journey j ON j.id=l.journey_id" in STATE_SQL
    assert "repair_conversation_ledger_branch_v1" in STATE_SQL
    assert "p_expected_revision" in STATE_SQL
    assert "p_apply boolean DEFAULT false" in STATE_SQL
    assert "clear_active_branch_only" in STATE_SQL


def test_post_handoff_support_proof_preserves_the_terminal_journey():
    assert "v_confirmation_state='post_qualification_support'" in POST_HANDOFF_SQL
    assert "THEN state ELSE 'handed_off' END" in POST_HANDOFF_SQL
    support = POST_HANDOFF_SQL[
        POST_HANDOFF_SQL.index("v_confirmation_state='post_qualification_support'"):
        POST_HANDOFF_SQL.index("IF jsonb_typeof(v_missing)")
    ]
    assert "'awaiting_confirmation'" not in support
    assert "RETURN NEW" in support
    assert "CREATE TABLE" not in POST_HANDOFF_SQL
    assert "DELETE FROM" not in POST_HANDOFF_SQL

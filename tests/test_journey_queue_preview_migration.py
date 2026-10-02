from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "supabase/migrations"


def test_journey_preview_migration_preserves_the_existing_atomic_commit():
    previous = (ROOT / "128_confirm_branch_offering_within_journey.sql").read_text()
    candidate = (ROOT / "161_allow_journey_queue_preview.sql").read_text()
    previous_function = previous[previous.index("CREATE OR REPLACE FUNCTION"):]
    candidate_function = candidate[candidate.index("CREATE OR REPLACE FUNCTION"):]

    expected = previous_function.replace(
        "p_outbound_buffer->>'status' <> 'awaiting_proof' THEN\n"
        "      RAISE EXCEPTION 'v3 outbound must be created awaiting_proof' USING ERRCODE='23514';",
        "p_outbound_buffer->>'status' NOT IN ('awaiting_proof','preview_ready')\n"
        "       OR (p_outbound_buffer->>'status'='preview_ready'\n"
        "           AND coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false)) THEN\n"
        "      RAISE EXCEPTION 'v3 outbound must be awaiting_proof or an inert preview_ready'\n"
        "        USING ERRCODE='23514';",
        1,
    ).replace(
        "WHEN coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN 'sent'\n"
        "      ELSE 'pending_send' END);",
        "WHEN coalesce((p_outbound_buffer->'payload'->>'validation')::boolean,false) THEN 'sent'\n"
        "      WHEN p_outbound_buffer->>'status'='preview_ready' THEN 'preview_ready'\n"
        "      ELSE 'pending_send' END);",
        1,
    )

    assert candidate_function == expected
    assert "CREATE TABLE" not in candidate.upper()
    assert "DROP TABLE" not in candidate.upper()

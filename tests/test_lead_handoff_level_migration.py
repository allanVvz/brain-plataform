from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _migration(name: str) -> str:
    return (ROOT / "supabase" / "migrations" / name).read_text(encoding="utf-8")


def test_handoff_level_column_and_generated_ai_paused():
    migration = _migration("103_lead_handoff_level.sql")

    assert "handoff_level text NOT NULL DEFAULT 'none'" in migration
    assert "CHECK (handoff_level IN ('none', 'partial', 'full'))" in migration
    assert "GENERATED ALWAYS AS (handoff_level = 'full') STORED" in migration
    assert "ALTER TABLE public.leads DROP COLUMN ai_paused" in migration


def test_backfill_scopes_update_and_disables_binding_integrity_trigger():
    """Regression test: a blanket UPDATE public.leads fires
    trg_enforce_lead_channel_binding (migration 067) on every row with no
    WHEN guard, which aborted the real deploy over pre-existing
    channel_binding_id/persona_id drift on an unrelated row. The backfill
    must be scoped to ai_paused=true and bracket itself with
    DISABLE/ENABLE TRIGGER for that one statement.
    """
    migration = _migration("103_lead_handoff_level.sql")
    assert "ALTER TABLE public.leads DISABLE TRIGGER trg_enforce_lead_channel_binding;" in migration
    assert "UPDATE public.leads SET handoff_level = 'full' WHERE ai_paused = true;" in migration
    assert "ALTER TABLE public.leads ENABLE TRIGGER trg_enforce_lead_channel_binding;" in migration
    disable_at = migration.index("DISABLE TRIGGER trg_enforce_lead_channel_binding")
    update_at = migration.index("UPDATE public.leads SET handoff_level = 'full'")
    enable_at = migration.index("ENABLE TRIGGER trg_enforce_lead_channel_binding", update_at)
    assert disable_at < update_at < enable_at


def test_handoff_rpcs_only_sweep_buffer_when_level_is_full():
    migration = _migration("103_lead_handoff_level.sql")

    # Every RPC that writes handoff_level must gate the lead_buffer sweep to
    # waiting_human behind level='full' -- a 'partial' handoff must never
    # stop inbound messages from being claimed, or the AI stops running.
    assert migration.count("IF p_level = 'full' THEN") == 3
    assert "p_level text DEFAULT 'full'" in migration


def test_handoff_rpcs_reject_invalid_level():
    migration = _migration("103_lead_handoff_level.sql")
    assert migration.count("RAISE EXCEPTION 'invalid handoff level: %', p_level") == 3


def test_reset_conversation_ledger_branch_v3_never_touches_facts():
    migration = _migration("103_lead_handoff_level.sql")
    start = migration.index("CREATE OR REPLACE FUNCTION public.reset_conversation_ledger_branch_v3")
    end = migration.index("$$;", start)
    body = migration[start:end].upper()

    assert "PG_ADVISORY_XACT_LOCK" in body
    assert "ACTIVE_BRANCH_NODE_ID = NULL" in body
    assert "CONVERSATION_FACTS" not in body
    assert "DROP" not in body
    assert "DELETE" not in body


def test_reset_conversation_ledger_branch_v3_is_service_role_only():
    migration = _migration("103_lead_handoff_level.sql")
    assert (
        "REVOKE ALL ON FUNCTION public.reset_conversation_ledger_branch_v3(uuid, bigint)\n"
        "  FROM PUBLIC, anon, authenticated;"
    ) in migration
    assert (
        "GRANT EXECUTE ON FUNCTION public.reset_conversation_ledger_branch_v3(uuid, bigint)\n"
        "  TO service_role;"
    ) in migration


def test_backdate_lead_messages_is_service_role_only_and_relative():
    migration = _migration("104_backdate_lead_messages.sql")
    assert "created_at = created_at - (p_hours || ' hours')::interval" in migration
    assert "FROM PUBLIC, anon, authenticated;" in migration
    assert "TO service_role;" in migration

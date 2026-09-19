from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "supabase" / "migrations" / "145_actionable_message_queue_preview.sql"
).read_text(encoding="utf-8").lower()
PERSISTENCE_MIGRATION = (
    ROOT / "supabase" / "migrations" / "154_persist_queue_preview_and_preserve_position.sql"
).read_text(encoding="utf-8").lower()


def test_preview_uses_the_existing_buffer_and_stays_inert_until_explicit_send():
    assert "create table" not in MIGRATION
    assert "'preview_ready'" in MIGRATION
    assert "p_action not in ('pause','resume','send_preview')" in MIGRATION
    assert "v_row.status<>'preview_ready'" in MIGRATION
    assert "new.status <> 'pending_send'" in MIGRATION


def test_resume_uses_the_outbounds_published_schedule_instead_of_fixed_hours():
    control = MIGRATION.split("create or replace function public.control_message_queue_v2", 1)[1]
    assert "v_hours:=v_row.payload->'published_business_hours'" in control
    assert "politica_publicada_indisponivel" in control
    assert "'08:00'" not in control
    assert "'20:00'" not in control


def test_only_a_technical_unproven_inbound_can_generate_a_preview():
    claim = MIGRATION.split("create or replace function public.claim_queue_preview_v1", 1)[1]
    assert "v_row.status <> 'waiting_human'" in claim
    assert "conversation_turn_proofs" in claim
    assert "conversation.technical_failure" in claim
    assert "conversation.technical_handoff" in claim


def test_projection_is_global_fifo_and_is_not_limited_by_client_history_fetching():
    projection = MIGRATION.split("create or replace function public.list_actionable_message_queue_v1", 1)[1]
    assert "not exists" in projection
    assert "newer.direction='inbound'" in projection
    assert "order by coalesce(available_at,created_at), created_at, id" in projection
    assert "awaiting_customer" in projection
    assert "offset greatest(p_offset,0) limit greatest(least(p_limit,100),1)" in projection


def test_preview_is_admitted_by_the_existing_atomic_proof_commit_not_a_new_path():
    assert "commit_graph_turn_and_outbox_v4" in MIGRATION
    assert "'preview_ready'')" in MIGRATION
    assert "v_definition !~ v_pattern" in MIGRATION
    assert "execute regexp_replace(v_definition,v_pattern,v_new,'g')" in MIGRATION


def test_queue_rpcs_are_not_public():
    for function in (
        "claim_queue_preview_v1(uuid,uuid)",
        "release_queue_preview_claim_v1(uuid,text)",
        "control_message_queue_v2(uuid[],text,uuid)",
        "list_actionable_message_queue_v1(uuid[],text,text,integer,integer)",
    ):
        assert f"revoke all on function public.{function}" in MIGRATION
        assert f"grant execute on function public.{function}" in MIGRATION


def test_persisted_preview_clears_claim_and_keeps_the_inbound_position():
    assert "v_outbound.status = 'awaiting_proof'" in PERSISTENCE_MIGRATION
    assert "v_outbound.status not in ('preview_ready','pending_send','processing','sent','delivered','read')" in PERSISTENCE_MIGRATION
    assert "payload, '{}'::jsonb) - 'queue_preview_claim'" in PERSISTENCE_MIGRATION
    assert "queue_position_epoch" in PERSISTENCE_MIGRATION
    assert "list_actionable_message_queue_v1" in PERSISTENCE_MIGRATION
    assert "list_actionable_message_queue_v149" in PERSISTENCE_MIGRATION
    assert "then (payload->>'queue_position_epoch')::double precision" in PERSISTENCE_MIGRATION

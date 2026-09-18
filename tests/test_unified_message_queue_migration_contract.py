from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "supabase/migrations/141_unified_message_queue.sql").read_text(encoding="utf-8").lower()


def test_unified_queue_keeps_lead_buffer_canonical_without_a_new_message_table():
    assert "create table" not in MIGRATION
    assert "control_message_queue_v1" in MIGRATION
    assert "lead_buffer" in MIGRATION


def test_reprocess_cannot_replay_a_completed_or_accepted_turn():
    assert "conversation_turn_proofs" in MIGRATION
    assert "turno_canonico_ja_concluido" in MIGRATION
    assert "somente_inbound_pode_ser_reprocessado" in MIGRATION
    assert "entrega_ou_estado_terminal" in MIGRATION


def test_queue_actions_are_auditable_and_idempotent():
    assert "system_events" in MIGRATION
    assert "acao_idempotente_ja_registrada" in MIGRATION
    assert "messaging.queue." in MIGRATION
    assert "scheduled_for" in MIGRATION
    assert "actor_user_id" in MIGRATION


def test_proactive_messages_have_an_independent_proof_identity_and_published_evidence():
    assert "commit_proactive_queue_proof_v1" in MIGRATION
    assert "proactive:" in MIGRATION
    assert "proactive proof requires published evidence nodes" in MIGRATION
    assert "message_origin <> 'proactive'" in MIGRATION

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "supabase/migrations/131_graph_media_batch_outbox.sql").read_text(encoding="utf-8")
REPAIR = (ROOT / "supabase/migrations/132_repair_literal_conversation_fact.sql").read_text(encoding="utf-8")
RUNTIME = (ROOT / "api/services/conversation_runtime.py").read_text(encoding="utf-8")
WORKER = (ROOT / "api/workers/whatsapp_dispatch_worker.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8")


def test_media_batch_commit_is_atomic_bounded_and_burst_safe():
    assert "commit_graph_turn_and_outbox_v5" in MIGRATION
    assert "v_count<1 OR v_count>20" in MIGRATION
    assert "IF v_result->>'state'='burst_superseded' THEN RETURN v_result" in MIGRATION
    assert "v5 atomic commit refuses preexisting batch item" in MIGRATION
    assert "status='awaiting_proof'" in MIGRATION


def test_media_batch_releases_only_the_next_item_in_same_scope():
    assert "release_next_graph_media_batch_item" in MIGRATION
    for fragment in (
        "persona_id=v_current.persona_id",
        "lead_ref=v_current.lead_ref",
        "channel_binding_id=v_current.channel_binding_id",
        "v_index+1",
    ):
        assert fragment in MIGRATION
    complete = WORKER.index("complete_whatsapp_outbound(")
    release = WORKER.index("release_next_graph_media_batch_item", complete)
    assert release > complete


def test_runtime_and_template_share_the_media_contract():
    assert "commit_graph_turn_and_outbox_v5" in RUNTIME
    assert "graph media batch requires an Evolution binding" in RUNTIME
    assert '"media_batch": response.media_batch' in RUNTIME
    assert "'media'" in TEMPLATE
    assert "content_delivery" in TEMPLATE
    assert "confidence" in TEMPLATE


def test_literal_repair_is_generic_cas_guarded_and_dry_run_by_default():
    assert "p_apply boolean DEFAULT false" in REPAIR
    assert "ledger revision conflict" in REPAIR
    assert "evidence is not literal in source message" in REPAIR
    assert "field owner is absent from ledger publication" in REPAIR
    assert "ignored_twice" in REPAIR
    assert "Cintia" not in REPAIR
    assert "estrada_de_chao" not in REPAIR

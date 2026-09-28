from __future__ import annotations

from services import whatsapp_outbox
from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker


def test_campaign_uses_atomic_repository_admission(monkeypatch):
    binding = {"id": "binding-1", "persona_id": "persona-1", "provider": "meta_cloud"}
    monkeypatch.setattr(whatsapp_outbox, "resolve_lead_binding", lambda lead: binding)
    monkeypatch.setattr(whatsapp_outbox, "_recipient_for_lead", lambda lead: "5511999999999")
    monkeypatch.setattr(whatsapp_outbox, "_observe_duplicate_content", lambda **kwargs: None)
    monkeypatch.setattr(whatsapp_outbox.control_plane_client, "published_outbound_policy", lambda _: {})
    monkeypatch.setattr(whatsapp_outbox.supabase_client, "enqueue_whatsapp_envelope",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("generic outbox bypass")))
    observed = []
    monkeypatch.setattr(whatsapp_outbox.supabase_client, "admit_campaign_outbound",
                        lambda **kwargs: observed.append(kwargs) or {"admitted": True, "buffer_id": "buffer-1"})
    result = whatsapp_outbox.enqueue_outbound(
        lead={"id": 1, "persona_id": "persona-1", "telefone": "5511999999999"},
        text="Ola", sender_type="campaign", message_id="campaign:1", correlation_id="campaign:1",
        campaign_scope={"campaign_id": "campaign-1", "campaign_revision": 1,
                        "campaign_recipient_id": "recipient-1", "campaign_step": 1,
                        "policy_checksum": "sha256:abc"},
    )
    assert result["admitted"] is True
    assert observed[0]["buffer"]["message_origin"] == "campaign"


def test_dispatch_rechecks_campaign_before_provider_call(monkeypatch):
    from workers import whatsapp_dispatch_worker as module

    calls = []
    monkeypatch.setattr(module.supabase_client, "authorize_campaign_dispatch", lambda _: False)
    monkeypatch.setattr(module.supabase_client, "complete_whatsapp_buffer",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    worker = object.__new__(WhatsAppDispatchWorker)
    worker._dispatch_outbound({"id": "buffer-1", "message_origin": "campaign"})
    assert calls[0][0] == ("buffer-1", "waiting_human")


def test_reactivation_with_new_reply_on_another_binding_stops_before_provider(monkeypatch):
    from workers import whatsapp_dispatch_worker as module

    calls = []
    monkeypatch.setattr(module.supabase_client, "reactivation_dispatch_blocked", lambda _: True)
    monkeypatch.setattr(module.supabase_client, "complete_whatsapp_buffer",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(module.supabase_client, "get_workflow_binding_by_id",
                        lambda _: (_ for _ in ()).throw(AssertionError("provider path reached")))
    worker = object.__new__(WhatsAppDispatchWorker)
    worker._dispatch_outbound({"id": "buffer-2", "message_origin": "proactive"})
    assert calls[0][0] == ("buffer-2", "waiting_human")

"""Every queued outbound obeys its sender's state at send time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import outbound_gate
from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker

WRITTEN = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
META = {"id": "b-meta", "provider": "meta_cloud", "active": True, "persona_id": "p", "metadata": {}}
EVOLUTION = {"id": "b-evo", "provider": "evolution_baileys", "active": True, "persona_id": "p", "metadata": {}}


def _row(sender="agent", **extra):
    return {"id": "out-1", "persona_id": "p", "lead_ref": 7, "direction": "outbound",
            "channel_binding_id": "b-meta", "correlation_id": "c-1",
            "created_at": WRITTEN.isoformat(), "payload": {"text": "oi", "sender_type": sender}, **extra}


def _human_reply(minutes_after):
    return {"direction": "outbound", "role": "human", "metadata": {"sender_type": "human"},
            "created_at": (WRITTEN + timedelta(minutes=minutes_after)).isoformat()}


def test_active_lead_and_channel_send():
    assert outbound_gate.decide(_row(), binding=META, lead={"handoff_level": "none"}) == ("send", None)


def test_paused_lead_holds_the_agent_but_never_the_person():
    paused = {"handoff_level": "full", "ai_paused": True}
    assert outbound_gate.decide(_row(), binding=META, lead=paused) == ("hold", "lead_paused")
    assert outbound_gate.decide(_row("human"), binding=META, lead=paused) == ("send", None)


def test_agent_message_is_superseded_once_a_person_answered_after_it():
    paused = {"handoff_level": "full"}
    assert outbound_gate.decide(_row(), binding=META, lead=paused, messages=[_human_reply(2)]) == (
        "supersede", "person_answered")
    assert outbound_gate.decide(_row(), binding=META, lead=paused, messages=[_human_reply(-2)]) == (
        "hold", "lead_paused")


def test_paused_channel_holds_everyone():
    paused_channel = {**META, "connection_status": "safety_paused"}
    assert outbound_gate.decide(_row("human"), binding=paused_channel, lead={}) == ("hold", "channel_paused")


def test_holds_clear_only_when_their_reason_clears():
    assert outbound_gate.hold_cleared("lead_paused", binding=META, lead={"handoff_level": "none"}) is True
    assert outbound_gate.hold_cleared("lead_paused", binding=META, lead={"handoff_level": "partial"}) is False
    assert outbound_gate.hold_cleared("channel_paused", binding={**META, "metadata": {"safety_paused": True}}, lead={}) is False
    assert outbound_gate.hold_cleared("unknown", binding=META, lead={}) is False


@pytest.mark.parametrize(("binding", "rate"), [
    (META, 20.0), (EVOLUTION, 1.0), ({**EVOLUTION, "metadata": {"send_rate_per_second": 2}}, 2.0),
    ({"id": "x", "provider": "other"}, 5.0),
])
def test_rate_defaults_per_provider_and_binding_override(binding, rate):
    assert outbound_gate.rate_for(binding) == rate


def test_pacing_is_per_channel_and_never_blocks_another_channel():
    clock = {"t": 100.0}
    slept = []
    pacer = outbound_gate.SendRate(clock=lambda: clock["t"], sleep=slept.append)
    assert pacer.wait(EVOLUTION) == 0          # first message on the phone: right away
    assert pacer.wait(EVOLUTION) == pytest.approx(1.0)  # next one waits a second
    assert pacer.wait(META) == 0               # Meta channel is not slowed by Evolution
    assert pacer.wait(META) == pytest.approx(0.05)
    assert slept == [pytest.approx(1.0), pytest.approx(0.05)]


def _worker(monkeypatch, *, binding, lead, messages=()):
    ws = __import__("workers.whatsapp_dispatch_worker", fromlist=["x"])
    calls = {"held": [], "completed": [], "sent": []}
    monkeypatch.setattr(ws.supabase_client, "get_workflow_binding_by_id", lambda _i: binding)
    monkeypatch.setattr(ws.supabase_client, "get_lead_by_ref", lambda _r: lead)
    monkeypatch.setattr(ws.supabase_client, "get_messages", lambda *_a, **_k: list(messages))
    monkeypatch.setattr(ws.supabase_client, "hold_whatsapp_outbound", lambda row, reason: calls["held"].append(reason))
    monkeypatch.setattr(ws.supabase_client, "complete_whatsapp_buffer", lambda *a, **k: calls["completed"].append((a, k)))
    monkeypatch.setattr(ws.event_emitter, "emit", lambda *a, **k: None)
    monkeypatch.setattr(ws.whatsapp_outbox, "validate_direct_binding", lambda _b: None)

    class Provider:
        def send_text(self, _binding, recipient, text):
            calls["sent"].append((recipient, text))
            return {"messages": [{"id": "wamid.1"}]}

    monkeypatch.setattr(ws, "get_provider", lambda _name: Provider())
    monkeypatch.setattr(ws.supabase_client, "mark_whatsapp_attempt", lambda *a: True)
    monkeypatch.setattr(ws.supabase_client, "complete_whatsapp_outbound", lambda *a, **k: calls["completed"].append(("ok", k)))
    worker = WhatsAppDispatchWorker.__new__(WhatsAppDispatchWorker)
    worker._send_rate = outbound_gate.SendRate(sleep=lambda _s: None)
    worker.worker_id = "test"
    return worker, calls


def test_dispatcher_holds_agent_reply_for_a_paused_lead(monkeypatch):
    worker, calls = _worker(monkeypatch, binding=META, lead={"id": 7, "handoff_level": "full", "external_contact_id": "5511999999999"})
    worker._dispatch_outbound(_row())
    assert calls["held"] == ["lead_paused"] and calls["sent"] == []


def test_dispatcher_sends_a_person_even_when_the_agent_is_paused(monkeypatch):
    worker, calls = _worker(monkeypatch, binding=META, lead={"id": 7, "handoff_level": "full", "external_contact_id": "5511999999999"})
    worker._dispatch_outbound(_row("human"))
    assert calls["held"] == [] and calls["sent"] == [("5511999999999", "oi")]


def test_dispatcher_holds_on_a_paused_channel_instead_of_dropping(monkeypatch):
    worker, calls = _worker(monkeypatch, binding={**META, "metadata": {"safety_paused": True}}, lead={"id": 7})
    worker._dispatch_outbound(_row("human"))
    assert calls["held"] == ["channel_paused"]
    assert not any(args and args[0] and "waiting_human" in str(args) for args, _ in calls["completed"])


def _failing_send(monkeypatch, error):
    worker, calls = _worker(monkeypatch, binding=META, lead={"id": 7, "external_contact_id": "5511999999999"})
    ws = __import__("workers.whatsapp_dispatch_worker", fromlist=["x"])

    class Provider:
        def send_text(self, *_a):
            raise error

    monkeypatch.setattr(ws, "get_provider", lambda _name: Provider())
    retried = []
    worker._retry_or_dead_letter = lambda row, exc: retried.append(exc)
    events = []
    monkeypatch.setattr(ws.event_emitter, "emit", lambda name, **k: events.append(name))
    return worker, calls, retried, events


def test_outside_24h_window_fails_the_message_plainly_without_retry(monkeypatch):
    from services.whatsapp_providers.meta import OutsideCustomerServiceWindow
    worker, calls, retried, events = _failing_send(monkeypatch, OutsideCustomerServiceWindow("code=131047"))
    worker._dispatch_group([_row("human")])
    assert calls["completed"] == [(("out-1", "failed"), {"error": "Fora da janela de 24h da Meta — envie um template"})]
    assert retried == [] and events == ["whatsapp.outbound_outside_window"]


def test_other_provider_errors_keep_the_retry_path(monkeypatch):
    worker, calls, retried, events = _failing_send(monkeypatch, RuntimeError("boom"))
    worker._dispatch_group([_row("human")])
    assert len(retried) == 1 and calls["completed"] == [] and events == []


def test_sweep_releases_only_cleared_holds(monkeypatch):
    ws = __import__("workers.whatsapp_dispatch_worker", fromlist=["x"])
    released = []
    held = [
        {"id": "h1", "lead_ref": 1, "channel_binding_id": "b-meta", "payload": {"queue_hold_reason": "lead_paused"}},
        {"id": "h2", "lead_ref": 2, "channel_binding_id": "b-meta", "payload": {"queue_hold_reason": "lead_paused"}},
    ]
    monkeypatch.setattr(ws.supabase_client, "list_held_whatsapp_outbound", lambda: held)
    monkeypatch.setattr(ws.supabase_client, "get_workflow_binding_by_id", lambda _i: META)
    monkeypatch.setattr(ws.supabase_client, "get_lead_by_ref", lambda ref: {"handoff_level": "none" if ref == 1 else "full"})
    monkeypatch.setattr(ws.supabase_client, "release_held_whatsapp_outbound", lambda row: released.append(row["id"]))
    monkeypatch.setattr(ws.event_emitter, "emit", lambda *a, **k: None)
    monkeypatch.setattr(WhatsAppDispatchWorker, "_last_hold_sweep", 0.0)
    worker = WhatsAppDispatchWorker.__new__(WhatsAppDispatchWorker)
    worker._release_cleared_holds()
    assert released == ["h1"]

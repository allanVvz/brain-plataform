"""Business hours switch the agent off, except in a dialogue that is still going."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import agent_schedule
from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker

HOURS = {
    "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
    "graph_version": 38, "graph_checksum": "sha256:published",
}
NIGHT = datetime(2026, 10, 7, 2, 25, tzinfo=timezone.utc)   # 23:25 in Sao Paulo
NOON = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)    # 12:00 in Sao Paulo
OPENING = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)  # 08:00 in Sao Paulo


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    agent_schedule._policy_cache.clear()
    monkeypatch.setattr(
        agent_schedule.control_plane_client, "published_outbound_policy",
        lambda _persona: {"published_business_hours": HOURS},
    )


def _outbound(minutes_before, *, status="sent"):
    return {"direction": "outbound", "status": status,
            "created_at": (NIGHT - timedelta(minutes=minutes_before)).isoformat()}


def test_open_hours_never_defer():
    assert agent_schedule.deferral("p", messages=[], inbound_at=NOON, now=NOON) is None


def test_closed_and_idle_defers_to_the_next_opening():
    assert agent_schedule.deferral("p", messages=[], inbound_at=NIGHT, now=NIGHT) == OPENING


def test_closed_dialogue_in_progress_keeps_the_agent_on():
    assert agent_schedule.deferral("p", messages=[_outbound(3)], inbound_at=NIGHT, now=NIGHT) is None


def test_dialogue_paused_longer_than_the_grace_turns_the_agent_off():
    assert agent_schedule.deferral("p", messages=[_outbound(11)], inbound_at=NIGHT, now=NIGHT) == OPENING


def test_customer_follow_ups_alone_do_not_count_as_a_dialogue():
    inbound = {"direction": "inbound", "status": "buffered", "created_at": (NIGHT - timedelta(minutes=2)).isoformat()}
    assert agent_schedule.deferral("p", messages=[inbound], inbound_at=NIGHT, now=NIGHT) == OPENING


def test_failed_outbound_is_not_a_dialogue():
    assert agent_schedule.deferral("p", messages=[_outbound(1, status="failed")], inbound_at=NIGHT, now=NIGHT) == OPENING


def test_no_hours_means_the_agent_is_always_on(monkeypatch):
    monkeypatch.setattr(
        agent_schedule.control_plane_client, "published_outbound_policy",
        lambda _persona: {"published_business_hours": None, "graph_checksum": "sha256:x"},
    )
    assert agent_schedule.deferral("utzig", messages=[], inbound_at=NIGHT, now=NIGHT) is None


def test_a_failed_policy_lookup_never_silences_the_agent(monkeypatch):
    def down(_persona):
        raise RuntimeError("control plane unavailable")

    monkeypatch.setattr(agent_schedule.control_plane_client, "published_outbound_policy", down)
    assert agent_schedule.deferral("p", messages=[], inbound_at=NIGHT, now=NIGHT) is None


def _worker_row(**extra):
    return {
        "id": "buf-1", "persona_id": "p", "lead_ref": 7, "direction": "inbound",
        "created_at": NIGHT.isoformat(), "channel_binding_id": "b", "correlation_id": "c",
        "payload": {"text": "oi"}, **extra,
    }


def _stub_worker(monkeypatch, *, messages, paused=False):
    deferred, reached_binding = [], []
    ws = __import__("workers.whatsapp_dispatch_worker", fromlist=["x"])
    monkeypatch.setattr(ws.supabase_client, "get_persona_by_id", lambda _i: {"id": "p", "slug": "tock"})
    monkeypatch.setattr(ws.supabase_client, "get_lead_by_ref", lambda _r: {"id": 7, "ai_paused": paused})
    monkeypatch.setattr(ws.supabase_client, "get_messages", lambda *_a, **_k: messages)
    monkeypatch.setattr(ws.supabase_client, "defer_whatsapp_inbound", lambda *a: deferred.append(a))
    monkeypatch.setattr(ws.supabase_client, "complete_whatsapp_buffer", lambda *a, **k: None)
    monkeypatch.setattr(ws.event_emitter, "emit", lambda *a, **k: None)

    def stop(_binding_id):
        reached_binding.append(True)
        raise StopIteration("binding step reached")

    monkeypatch.setattr(ws.supabase_client, "get_workflow_binding_by_id", stop)
    return deferred, reached_binding


def _run(monkeypatch, row, **kw):
    deferred, reached = _stub_worker(monkeypatch, **kw)
    # the clock is the real one; the policy fixture pins HOURS, so force "now" into the night
    real = agent_schedule.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return NIGHT.astimezone(tz) if tz else NIGHT.replace(tzinfo=None)

    monkeypatch.setattr(agent_schedule, "datetime", Clock)
    worker = WhatsAppDispatchWorker.__new__(WhatsAppDispatchWorker)
    try:
        worker._dispatch_inbound(row)
    except StopIteration:
        pass
    return deferred, reached


def test_worker_defers_an_idle_inbound_without_calling_the_agent(monkeypatch):
    deferred, reached = _run(monkeypatch, _worker_row(), messages=[])
    assert deferred == [("buf-1", OPENING.isoformat(), "outside_business_hours")]
    assert reached == []


def test_worker_lets_an_ongoing_dialogue_through_to_the_agent(monkeypatch):
    deferred, reached = _run(monkeypatch, _worker_row(), messages=[_outbound(2)])
    assert deferred == [] and reached == [True]


def test_internal_validation_traffic_is_never_deferred(monkeypatch):
    row = _worker_row(payload={"text": "oi", "validation_transport": True, "sender": "wa-validator"})
    deferred, reached = _run(monkeypatch, row, messages=[])
    assert deferred == [] and reached == [True]

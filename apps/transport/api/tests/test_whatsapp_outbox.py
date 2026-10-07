from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from services import whatsapp_outbox
from services.whatsapp_outbox import _published_schedule, _recipient_for_lead


def test_recipient_prefers_canonical_external_identity():
    lead = {
        "external_contact_id": "5511999999999",
        "telefone": "5511888888888",
        "metadata": {"identities": {"remote_jid_alt": "5511777777777@s.whatsapp.net"}},
    }

    assert _recipient_for_lead(lead) == "5511777777777"


def test_recipient_falls_back_to_phone_for_manual_lead():
    assert _recipient_for_lead({"telefone": "+55 (11) 98888-7777"}) == "5511988887777"


@pytest.mark.parametrize("lead", [{}, {"telefone": "123"}, {"external_contact_id": "abc@lid"}])
def test_recipient_rejects_missing_or_invalid_identity(lead):
    with pytest.raises(HTTPException) as exc:
        _recipient_for_lead(lead)
    assert exc.value.status_code == 409


def test_published_schedule_defers_until_next_published_opening():
    result = _published_schedule(
        {"published_business_hours": {
            "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
            "graph_checksum": "sha256:published",
        }},
        now=datetime(2026, 9, 19, 0, 30, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["closed"] is True
    assert result["available_at"] == "2026-09-19T11:00:00+00:00"


def test_published_schedule_keeps_open_window_sendable():
    result = _published_schedule(
        {"published_business_hours": {
            "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
            "graph_checksum": "sha256:published",
        }},
        now=datetime(2026, 9, 18, 14, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["closed"] is False


def test_published_schedule_rejects_unpinned_policy():
    with pytest.raises(HTTPException) as exc:
        _published_schedule({"published_business_hours": {"timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00"}})
    assert exc.value.status_code == 409


_NIGHT = {
    "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
    "graph_checksum": "sha256:published", "graph_version": 38,
}


def _stub_envelope_dependencies(monkeypatch, *, policy=None):
    monkeypatch.setattr(whatsapp_outbox, "resolve_lead_binding", lambda lead: {"id": "binding"})
    monkeypatch.setattr(whatsapp_outbox, "_recipient_for_lead", lambda lead: "5511999999999")
    monkeypatch.setattr(whatsapp_outbox, "_observe_duplicate_content", lambda **_: None)
    monkeypatch.setattr(
        whatsapp_outbox.control_plane_client, "published_outbound_policy",
        lambda persona_id: {"published_business_hours": policy},
    )


@pytest.fixture
def after_hours(monkeypatch):
    """23:15 in Sao Paulo, outside the published 08:00-20:00 window."""
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 7, 2, 15, tzinfo=timezone.utc).astimezone(tz) if tz else datetime(2026, 10, 7, 2, 15)
    monkeypatch.setattr(whatsapp_outbox, "datetime", _Clock)


def test_human_attendance_is_sent_now_even_outside_the_published_window(monkeypatch, after_hours):
    _stub_envelope_dependencies(monkeypatch, policy=_NIGHT)
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="oi", sender_type="human",
        message_id="manual:1", correlation_id="manual:1", message_origin="manual",
    )
    assert envelope["buffer"]["message_origin"] == "manual"
    assert envelope["buffer"]["status"] == "pending_send"
    assert "available_at" not in envelope["buffer"]
    assert "published_business_hours" not in envelope["buffer"]["payload"]
    assert "published_business_hours" not in envelope["message"]["metadata"]


def test_human_attendance_does_not_depend_on_the_policy_lookup(monkeypatch):
    _stub_envelope_dependencies(monkeypatch)

    def unavailable(_persona_id):
        raise RuntimeError("control-plane down")

    monkeypatch.setattr(whatsapp_outbox.control_plane_client, "published_outbound_policy", unavailable)
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="oi", sender_type="human",
        message_id="manual:2", correlation_id="manual:2",
    )
    assert envelope["buffer"]["status"] == "pending_send"


def test_agent_reply_is_never_held_at_the_door_even_after_closing(monkeypatch, after_hours):
    # Closing time switches the agent off at the INBOUND (agent_schedule); a
    # reply the agent is already producing mid-dialogue goes out right away.
    _stub_envelope_dependencies(monkeypatch, policy=_NIGHT)
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="oi", sender_type="agent",
        message_id="agent:2", correlation_id="agent:2",
        metadata={"published_business_hours": {**_NIGHT}},
    )
    assert envelope["buffer"]["status"] == "pending_send"
    assert "available_at" not in envelope["buffer"]
    assert "published_business_hours" not in envelope["message"]["metadata"]


def test_agent_reply_awaiting_proof_carries_no_window_after_closing(monkeypatch, after_hours):
    # Proof promotion later turns this row into pending_send; an available_at
    # stamped here would hold the very reply the dialogue is waiting for.
    _stub_envelope_dependencies(monkeypatch, policy=_NIGHT)
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="oi", sender_type="agent",
        message_id="agent:5", correlation_id="agent:5", initial_status="awaiting_proof",
        metadata={"published_business_hours": {**_NIGHT}},
    )
    assert envelope["buffer"]["status"] == "awaiting_proof"
    assert "available_at" not in envelope["buffer"]
    assert "published_business_hours" not in envelope["buffer"]["payload"]


@pytest.mark.parametrize("origin", ["proactive", "system"])
def test_system_started_sends_still_wait_for_the_next_opening(monkeypatch, after_hours, origin):
    _stub_envelope_dependencies(monkeypatch, policy=_NIGHT)
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="bom dia", sender_type="agent",
        message_id=f"{origin}:1", correlation_id=f"{origin}:1", message_origin=origin,
    )
    assert envelope["buffer"]["status"] == "buffered"
    assert envelope["buffer"]["available_at"].startswith("2026-10-07T11:00:00")


def test_manual_envelope_without_published_hours_remains_sendable(monkeypatch):
    monkeypatch.setattr(whatsapp_outbox, "resolve_lead_binding", lambda lead: {"id": "binding"})
    monkeypatch.setattr(whatsapp_outbox, "_recipient_for_lead", lambda lead: "5511999999999")
    monkeypatch.setattr(whatsapp_outbox, "_observe_duplicate_content", lambda **_: None)
    monkeypatch.setattr(
        whatsapp_outbox.control_plane_client,
        "published_outbound_policy",
        lambda _persona_id: {"published_business_hours": None, "graph_checksum": "sha256:appointment"},
    )

    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="oi", sender_type="agent",
        message_id="agent:1", correlation_id="agent:1", message_origin="proactive",
    )

    assert envelope["buffer"]["status"] == "pending_send"
    assert envelope["message"]["metadata"]["published_business_hours"] is None


def test_preview_envelope_remains_inert_until_operator_sends(monkeypatch):
    policy = {
        "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
        "graph_checksum": "sha256:published", "graph_version": 3,
    }
    monkeypatch.setattr(whatsapp_outbox, "resolve_lead_binding", lambda lead: {"id": "binding"})
    monkeypatch.setattr(whatsapp_outbox, "_recipient_for_lead", lambda lead: "5511999999999")
    monkeypatch.setattr(whatsapp_outbox, "_observe_duplicate_content", lambda **_: None)
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="preview", sender_type="agent",
        message_id="preview:1", correlation_id="preview:1", initial_status="preview_ready",
        metadata={"published_business_hours": policy}, queue_position_epoch=1726650000.0,
    )
    assert envelope["buffer"]["status"] == "preview_ready"
    assert envelope["buffer"]["payload"]["published_business_hours"] == policy
    assert envelope["buffer"]["payload"]["queue_position_epoch"] == 1726650000.0

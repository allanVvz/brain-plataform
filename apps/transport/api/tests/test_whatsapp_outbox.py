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


def test_manual_envelope_fetches_published_policy_when_not_pinned(monkeypatch):
    policy = {
        "timezone": "America/Sao_Paulo", "start": "00:00", "end": "23:59",
        "graph_checksum": "sha256:published", "graph_version": 3,
    }
    monkeypatch.setattr(whatsapp_outbox, "resolve_lead_binding", lambda lead: {"id": "binding"})
    monkeypatch.setattr(whatsapp_outbox, "_recipient_for_lead", lambda lead: "5511999999999")
    monkeypatch.setattr(whatsapp_outbox, "_observe_duplicate_content", lambda **_: None)
    monkeypatch.setattr(
        whatsapp_outbox.control_plane_client,
        "published_outbound_policy",
        lambda persona_id: {"published_business_hours": policy},
    )
    envelope = whatsapp_outbox.prepare_outbound_envelope(
        lead={"id": 7, "persona_id": "persona"}, text="oi", sender_type="human",
        message_id="manual:1", correlation_id="manual:1", message_origin="manual",
    )
    assert envelope["buffer"]["message_origin"] == "manual"
    assert envelope["message"]["metadata"]["published_business_hours"] == policy


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

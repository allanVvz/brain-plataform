"""Regression coverage for duplicate-content observability and idempotency.

Row-identity idempotency (idempotency_key/correlation_id) only stops a
literal re-dispatch of the same lead_buffer row. It does not stop an
operator/agent typing the same answer again as a brand-new send when a
prior send's delivery ACK never came back (the Evolution/Baileys gap
documented in docs/architecture/WHATSAPP_N8N_RUNTIME.md section 4). These
tests prove that only canonical row identity suppresses a send; repeated copy
is observable but remains a distinct outbound for a distinct inbound.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import whatsapp_outbox


def _lead(**overrides):
    return {
        "id": 7,
        "persona_id": "persona-1",
        "channel_binding_id": "binding-1",
        "external_contact_id": "5551982608510",
        "metadata": {},
        **overrides,
    }


def _binding(**overrides):
    return {
        "id": "binding-1",
        "persona_id": "persona-1",
        "provider": "meta_cloud",
        "active": True,
        "connection_status": "connected",
        "whatsapp_phone_number_id": "phone-id",
        "provider_secret_ciphertext": "encrypted-token",
        "metadata": {
            "decision_owner": "deterministic",
            "transport_mode": "provider_direct",
        },
        **overrides,
    }


def _patch_common(monkeypatch, *, binding, existing_idempotent=None,
                   duplicate_row=None, envelope_calls=None, violation_calls=None):
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client, "get_workflow_binding_by_id", lambda _id: binding,
    )
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_whatsapp_buffer_by_idempotency",
        lambda _key: existing_idempotent,
    )

    calls = {"find_duplicate": []}

    def find_duplicate(**kwargs):
        calls["find_duplicate"].append(kwargs)
        return duplicate_row

    monkeypatch.setattr(
        whatsapp_outbox.supabase_client, "find_recent_duplicate_whatsapp_outbound", find_duplicate,
    )

    def record_violation(**kwargs):
        if violation_calls is not None:
            violation_calls.append(kwargs)
        return {"violation_count": 1, "safety_paused": False}

    monkeypatch.setattr(
        whatsapp_outbox.supabase_client, "record_whatsapp_safety_violation", record_violation,
    )

    def enqueue_envelope(*, buffer, message):
        if envelope_calls is not None:
            envelope_calls.append({"buffer": buffer, "message": message})
        return {"buffer_id": "buffer-1", "message_id": "msg-1", "status": "pending_send",
                "deduplicated": False}

    monkeypatch.setattr(
        whatsapp_outbox.supabase_client, "enqueue_whatsapp_envelope", enqueue_envelope,
    )
    return calls


def test_identical_content_for_a_distinct_inbound_is_enqueued(monkeypatch):
    """A repeated text is logged, but a new canonical inbound still sends."""
    binding = _binding()
    violation_calls: list[dict] = []
    event_calls: list[dict] = []
    envelope_calls: list[dict] = []
    _patch_common(
        monkeypatch, binding=binding,
        duplicate_row={"id": "buffer-old", "status": "sent"},
        envelope_calls=envelope_calls,
        violation_calls=violation_calls,
    )
    monkeypatch.setattr(
        whatsapp_outbox.event_emitter,
        "emit",
        lambda *args, **kwargs: event_calls.append({"args": args, "kwargs": kwargs}),
    )

    result = whatsapp_outbox.enqueue_outbound(
        lead=_lead(), text="Allan", sender_type="human",
        message_id="manual:1", correlation_id="corr-1",
    )

    assert result["buffer_id"] == "buffer-1"
    assert result["deduplicated"] is False
    assert len(envelope_calls) == 1
    assert violation_calls == []
    assert len(event_calls) == 1
    assert event_calls[0]["args"][0] == "whatsapp.duplicate_content_suppressed"
    assert event_calls[0]["kwargs"]["level"] == "warning"


def test_allows_send_when_no_recent_duplicate(monkeypatch):
    binding = _binding()
    envelope_calls: list[dict] = []
    _patch_common(monkeypatch, binding=binding, duplicate_row=None, envelope_calls=envelope_calls)

    result = whatsapp_outbox.enqueue_outbound(
        lead=_lead(), text="Chevrolet Onix", sender_type="human",
        message_id="manual:2", correlation_id="corr-2",
    )

    assert result["buffer_id"] == "buffer-1"
    assert len(envelope_calls) == 1


def test_binding_can_disable_the_guard(monkeypatch):
    binding = _binding(metadata={
        "decision_owner": "deterministic",
        "transport_mode": "provider_direct",
        "duplicate_guard_enabled": False,
    })
    envelope_calls: list[dict] = []
    # Even though a duplicate technically exists, the disabled flag must
    # short-circuit before the lookup is even consulted.
    calls = _patch_common(
        monkeypatch, binding=binding,
        duplicate_row={"id": "buffer-old", "status": "sent"},
        envelope_calls=envelope_calls,
    )

    result = whatsapp_outbox.enqueue_outbound(
        lead=_lead(), text="Allan", sender_type="human",
        message_id="manual:3", correlation_id="corr-3",
    )

    assert result["buffer_id"] == "buffer-1"
    assert calls["find_duplicate"] == []


def test_binding_can_override_the_default_window(monkeypatch):
    binding = _binding(metadata={
        "decision_owner": "deterministic",
        "transport_mode": "provider_direct",
        "duplicate_guard_window_seconds": 900,
    })
    calls = _patch_common(monkeypatch, binding=binding, duplicate_row=None)

    whatsapp_outbox.enqueue_outbound(
        lead=_lead(), text="Allan", sender_type="human",
        message_id="manual:4", correlation_id="corr-4",
    )

    assert calls["find_duplicate"][0]["window_seconds"] == 900


def test_non_positive_configured_window_falls_back_to_default(monkeypatch):
    binding = _binding(metadata={
        "decision_owner": "deterministic",
        "transport_mode": "provider_direct",
        "duplicate_guard_window_seconds": 0,
    })
    calls = _patch_common(monkeypatch, binding=binding, duplicate_row=None)

    whatsapp_outbox.enqueue_outbound(
        lead=_lead(), text="Allan", sender_type="human",
        message_id="manual:5", correlation_id="corr-5",
    )

    assert calls["find_duplicate"][0]["window_seconds"] == (
        whatsapp_outbox.DEFAULT_DUPLICATE_GUARD_WINDOW_SECONDS
    )


@pytest.mark.parametrize(
    ("first", "second", "equal"),
    [
        ("Allan", "allan", True),
        ("  Allan  ", "Allan", True),
        ("Chevrolet   Onix", "chevrolet onix", True),
        ("Allan", "Allan Souza", False),
        ("", "", True),
    ],
)
def test_normalize_whatsapp_text_matches_expected_equivalence(first, second, equal):
    normalized_first = whatsapp_outbox.supabase_client.normalize_whatsapp_text(first)
    normalized_second = whatsapp_outbox.supabase_client.normalize_whatsapp_text(second)
    assert (normalized_first == normalized_second) is equal

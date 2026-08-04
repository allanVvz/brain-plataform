from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import agents_service, supabase_client


def test_resume_lead_requeues_waiting_human_messages(monkeypatch):
    calls = []
    monkeypatch.setattr(
        supabase_client, "get_lead_by_ref",
        lambda lead_ref: {"metadata": {}},
    )
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append(("update_lead", lead_ref, payload)),
    )
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer",
        lambda lead_ref: calls.append(("requeue", lead_ref)) or 2,
    )

    assert agents_service.resume_lead(42) is True
    assert calls == [
        ("update_lead", 42, {"ai_paused": False}),
        ("requeue", 42),
    ]


def test_resume_lead_still_succeeds_if_requeue_fails(monkeypatch):
    monkeypatch.setattr(
        supabase_client, "get_lead_by_ref", lambda lead_ref: {"metadata": {}}
    )
    monkeypatch.setattr(supabase_client, "update_lead", lambda lead_ref, payload: None)

    def _boom(lead_ref):
        raise RuntimeError("rpc unavailable")

    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", _boom
    )

    # ai_paused was already cleared; a requeue failure must not surface as
    # a failed resume, only get logged for follow-up.
    assert agents_service.resume_lead(42) is True


def test_resume_lead_fails_if_update_lead_fails(monkeypatch):
    monkeypatch.setattr(
        supabase_client, "get_lead_by_ref", lambda lead_ref: {"metadata": {}}
    )

    def _boom(lead_ref, payload):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(supabase_client, "update_lead", _boom)
    called = []
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer",
        lambda lead_ref: called.append(lead_ref),
    )

    assert agents_service.resume_lead(42) is False
    assert called == []


def test_resume_lead_clears_sticky_handoff_flag_in_conversation_state(monkeypatch):
    lead = {
        "metadata": {
            "conversation_state": {
                "conversation_state": "handoff",
                "clarification_attempts": 2,
                "appointment_request": {"nome_cliente": "Allan"},
            },
            "other_field": "kept",
        }
    }
    monkeypatch.setattr(supabase_client, "get_lead_by_ref", lambda lead_ref: lead)
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append(("update_lead", lead_ref, payload)),
    )
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    assert agents_service.resume_lead(42) is True
    assert calls == [
        (
            "update_lead",
            42,
            {
                "ai_paused": False,
                "metadata": {
                    "conversation_state": {
                        "conversation_state": "",
                        "clarification_attempts": 0,
                        "appointment_request": {"nome_cliente": "Allan"},
                    },
                    "other_field": "kept",
                },
            },
        ),
    ]


def test_resume_lead_clears_sticky_handoff_flag_in_legacy_vitoria_state(monkeypatch):
    lead = {
        "metadata": {
            "vitoria_state": {
                "conversation_state": "handoff",
                "items": [{"product_slug": "x"}],
            },
        }
    }
    monkeypatch.setattr(supabase_client, "get_lead_by_ref", lambda lead_ref: lead)
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append(("update_lead", lead_ref, payload)),
    )
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    assert agents_service.resume_lead(42) is True
    assert calls[0][2]["metadata"]["vitoria_state"]["conversation_state"] == ""
    assert calls[0][2]["metadata"]["vitoria_state"]["clarification_attempts"] == 0
    assert calls[0][2]["metadata"]["vitoria_state"]["items"] == [{"product_slug": "x"}]


def test_resume_lead_leaves_metadata_untouched_when_not_handed_off(monkeypatch):
    lead = {"metadata": {"conversation_state": {"conversation_state": "collecting"}}}
    monkeypatch.setattr(supabase_client, "get_lead_by_ref", lambda lead_ref: lead)
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append(("update_lead", lead_ref, payload)),
    )
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    assert agents_service.resume_lead(42) is True
    assert calls == [("update_lead", 42, {"ai_paused": False})]


def test_resume_lead_tolerates_lead_lookup_failure(monkeypatch):
    def _boom(lead_ref):
        raise RuntimeError("lookup unavailable")

    monkeypatch.setattr(supabase_client, "get_lead_by_ref", _boom)
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append(("update_lead", lead_ref, payload)),
    )
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    # A broken lookup must not block the resume — it only means the sticky
    # flag (if any) won't be cleared this time.
    assert agents_service.resume_lead(42) is True
    assert calls == [("update_lead", 42, {"ai_paused": False})]

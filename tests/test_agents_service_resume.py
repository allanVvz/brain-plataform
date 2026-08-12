from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import agents_service, graph_agent_runtime_v3, supabase_client


def test_pause_lead_writes_handoff_level_full(monkeypatch):
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append((lead_ref, payload)),
    )
    assert agents_service.pause_lead(42) is True
    assert calls == [(42, {"handoff_level": "full"})]


def test_acknowledge_partial_handoff_writes_handoff_level_none(monkeypatch):
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append((lead_ref, payload)),
    )
    assert agents_service.acknowledge_partial_handoff(42) is True
    assert calls == [(42, {"handoff_level": "none"})]


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
        (
            "update_lead",
            42,
            {"handoff_level": "none", "metadata": {"pending_reconfirmation": True}},
        ),
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

    # handoff_level was already cleared; a requeue failure must not surface
    # as a failed resume, only get logged for follow-up.
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
                "handoff_level": "none",
                "metadata": {
                    "conversation_state": {
                        "conversation_state": "",
                        "clarification_attempts": 0,
                        "appointment_request": {"nome_cliente": "Allan"},
                    },
                    "other_field": "kept",
                    "pending_reconfirmation": True,
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
    assert calls[0][2]["metadata"]["pending_reconfirmation"] is True


def test_resume_lead_marks_pending_reconfirmation_when_not_handed_off(monkeypatch):
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
    assert calls == [
        (
            "update_lead",
            42,
            {
                "handoff_level": "none",
                "metadata": {
                    "conversation_state": {"conversation_state": "collecting"},
                    "pending_reconfirmation": True,
                },
            },
        ),
    ]


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
    # flag (if any) won't be cleared this time, and no v3 ledger reset is
    # attempted (no lead to check the binding of).
    assert agents_service.resume_lead(42) is True
    assert calls == [("update_lead", 42, {"handoff_level": "none"})]


def test_resume_lead_preserves_v3_ledger_and_asked_questions(monkeypatch):
    lead = {"metadata": {}, "persona_id": "persona-1", "channel_binding_id": "binding-1"}
    monkeypatch.setattr(supabase_client, "get_lead_by_ref", lambda lead_ref: lead)
    monkeypatch.setattr(
        supabase_client, "get_workflow_binding_by_id",
        lambda binding_id: {"metadata": {"runtime_version": graph_agent_runtime_v3.RUNTIME_VERSION}},
    )
    reset_calls = []
    monkeypatch.setattr(
        supabase_client, "reset_conversation_ledger_branch_v3",
        lambda *, persona_id, lead_ref: reset_calls.append((persona_id, lead_ref)),
    )
    monkeypatch.setattr(supabase_client, "update_lead", lambda lead_ref, payload: None)
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    assert agents_service.resume_lead(42) is True
    assert reset_calls == []


def test_resume_lead_skips_v3_ledger_reset_for_non_v3_binding(monkeypatch):
    lead = {"metadata": {}, "persona_id": "persona-1", "channel_binding_id": "binding-1"}
    monkeypatch.setattr(supabase_client, "get_lead_by_ref", lambda lead_ref: lead)
    monkeypatch.setattr(
        supabase_client, "get_workflow_binding_by_id",
        lambda binding_id: {"metadata": {}},
    )
    reset_calls = []
    monkeypatch.setattr(
        supabase_client, "reset_conversation_ledger_branch_v3",
        lambda *, persona_id, lead_ref: reset_calls.append((persona_id, lead_ref)),
    )
    monkeypatch.setattr(supabase_client, "update_lead", lambda lead_ref, payload: None)
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    assert agents_service.resume_lead(42) is True
    assert reset_calls == []


def test_resume_lead_tolerates_v3_ledger_reset_failure(monkeypatch):
    lead = {"metadata": {}, "persona_id": "persona-1", "channel_binding_id": "binding-1"}
    monkeypatch.setattr(supabase_client, "get_lead_by_ref", lambda lead_ref: lead)

    def _boom(binding_id):
        raise RuntimeError("binding lookup unavailable")

    monkeypatch.setattr(supabase_client, "get_workflow_binding_by_id", _boom)
    calls = []
    monkeypatch.setattr(
        supabase_client, "update_lead",
        lambda lead_ref, payload: calls.append(("update_lead", lead_ref, payload)),
    )
    monkeypatch.setattr(
        supabase_client, "requeue_waiting_human_whatsapp_buffer", lambda lead_ref: 0
    )

    assert agents_service.resume_lead(42) is True
    assert calls and calls[0][0] == "update_lead"

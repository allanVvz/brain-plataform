from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import agents_service, supabase_client


def test_resume_lead_requeues_waiting_human_messages(monkeypatch):
    calls = []
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

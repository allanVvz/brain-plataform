"""PATCH /leads/{lead_ref} — manual edits to nome/produto/nota comercial.

The critical, non-obvious behavior: editing the commercial note must not
only update the display-only metadata.commercial_note mirror, it must also
merge into metadata.conversation_state.appointment_request (the AI's actual
working memory) and drop those keys from missing_fields — otherwise the AI
would keep asking for information a human operator already filled in.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _request():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "user-1", "role": "admin"}))


def test_update_lead_info_merges_note_into_appointment_request_and_clears_missing(monkeypatch):
    from routes import leads

    lead = {
        "id": 29,
        "persona_id": "persona-1",
        "nome": "Allan",
        "interesse_produto": "chapeacao",
        "metadata": {
            "commercial_note": {"vehicle_model": "Tracker 2024"},
            "conversation_state": {
                "business_model": "appointment",
                "missing_fields": ["vehicle_size", "condition", "desired_date"],
                "appointment_request": {
                    "customer_name": "Allan",
                    "vehicle_model": "Tracker 2024",
                },
            },
        },
    }
    saved = {}

    monkeypatch.setattr(leads.supabase_client, "get_lead_by_ref", lambda _ref: lead)
    monkeypatch.setattr(leads.auth_service, "assert_persona_access", lambda *a, **k: None)

    def fake_update(lead_ref, data):
        saved["lead_ref"] = lead_ref
        saved["data"] = data

    monkeypatch.setattr(leads.supabase_client, "update_lead", fake_update)
    monkeypatch.setattr(
        leads.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {**lead, "metadata": saved.get("data", {}).get("metadata", lead["metadata"])},
    )
    monkeypatch.setattr(leads.event_emitter, "emit", lambda *a, **k: None)

    body = leads.LeadInfoUpdateBody(
        commercial_note={"condition": "risco fundo na porta", "desired_date": "amanha"},
    )
    result = leads.update_lead_info(29, body, _request())

    assert result["ok"] is True
    metadata = saved["data"]["metadata"]
    state = metadata["conversation_state"]
    assert state["appointment_request"]["condition"] == "risco fundo na porta"
    assert state["appointment_request"]["desired_date"] == "amanha"
    # already-filled fields untouched
    assert state["appointment_request"]["vehicle_model"] == "Tracker 2024"
    # answered fields removed from missing_fields, unrelated ones kept
    assert state["missing_fields"] == ["vehicle_size"]
    assert metadata["commercial_note"]["condition"] == "risco fundo na porta"
    assert metadata["commercial_note"]["source"] == "manual"


def test_update_lead_info_updates_nome_and_interesse_produto(monkeypatch):
    from routes import leads

    lead = {"id": 5, "persona_id": "persona-1", "nome": "Old", "metadata": {}}
    saved = {}

    monkeypatch.setattr(leads.supabase_client, "get_lead_by_ref", lambda _ref: lead)
    monkeypatch.setattr(leads.auth_service, "assert_persona_access", lambda *a, **k: None)
    monkeypatch.setattr(
        leads.supabase_client,
        "update_lead",
        lambda ref, data: saved.update({"ref": ref, "data": data}),
    )
    monkeypatch.setattr(leads.event_emitter, "emit", lambda *a, **k: None)

    body = leads.LeadInfoUpdateBody(nome="Allan Roberto", interesse_produto="vitrificacao")
    leads.update_lead_info(5, body, _request())

    assert saved["data"]["nome"] == "Allan Roberto"
    assert saved["data"]["interesse_produto"] == "vitrificacao"
    assert "metadata" not in saved["data"]


def test_update_lead_info_rejects_blank_nome(monkeypatch):
    from fastapi import HTTPException
    from routes import leads

    lead = {"id": 7, "persona_id": "persona-1", "nome": "Someone", "metadata": {}}
    monkeypatch.setattr(leads.supabase_client, "get_lead_by_ref", lambda _ref: lead)
    monkeypatch.setattr(leads.auth_service, "assert_persona_access", lambda *a, **k: None)

    body = leads.LeadInfoUpdateBody(nome="   ")
    try:
        leads.update_lead_info(7, body, _request())
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400


def test_update_lead_info_requires_at_least_one_field(monkeypatch):
    from fastapi import HTTPException
    from routes import leads

    lead = {"id": 8, "persona_id": "persona-1", "nome": "Someone", "metadata": {}}
    monkeypatch.setattr(leads.supabase_client, "get_lead_by_ref", lambda _ref: lead)
    monkeypatch.setattr(leads.auth_service, "assert_persona_access", lambda *a, **k: None)

    body = leads.LeadInfoUpdateBody()
    try:
        leads.update_lead_info(8, body, _request())
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400

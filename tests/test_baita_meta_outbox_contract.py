"""Regression coverage for provider-direct WhatsApp manual sends."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import whatsapp_outbox


def _lead(**overrides):
    return {
        "id": 7,
        "persona_id": "persona-baita",
        "channel_binding_id": "binding-baita",
        "external_contact_id": "5551982608510",
        "metadata": {},
        **overrides,
    }


def _binding(**overrides):
    return {
        "id": "binding-baita",
        "persona_id": "persona-baita",
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


def test_baita_accepts_meta_or_evolution_but_rejects_n8n(monkeypatch):
    evolution = _binding(
        provider="evolution_baileys",
        provider_instance_key="brain-baita",
        whatsapp_phone_number_id=None,
    )
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: evolution,
    )
    assert whatsapp_outbox.resolve_lead_binding(_lead()) == evolution

    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: _binding(metadata={
            "decision_owner": "deterministic",
            "transport_mode": "n8n_adapter",
            "n8n_outbound_webhook_url": "https://n8n.invalid/hook",
        }),
    )
    with pytest.raises(HTTPException, match="transporte direto"):
        whatsapp_outbox.resolve_lead_binding(_lead())

    for legacy_binding in (
        _binding(metadata={
            "decision_owner": "deterministic",
            "transport_mode": "provider_direct",
            "outbound_webhook_url": "http://n8n:5678/webhook/legacy",
        }),
        _binding(n8n_workflow_id="legacy-workflow"),
    ):
        monkeypatch.setattr(
            whatsapp_outbox.supabase_client,
            "get_workflow_binding_by_id",
            lambda _id, value=legacy_binding: value,
        )
        with pytest.raises(HTTPException, match="Webhooks n8n"):
            whatsapp_outbox.resolve_lead_binding(_lead())


def test_provider_direct_rejects_missing_credential_and_invalid_recipient(monkeypatch):
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: _binding(provider_secret_ciphertext=None),
    )
    with pytest.raises(HTTPException, match="sem credencial"):
        whatsapp_outbox.resolve_lead_binding(_lead())

    assert whatsapp_outbox._recipient_for_lead(_lead(external_contact_id="5511987654321")) == "5511987654321"
    with pytest.raises(HTTPException, match="Destinatario WhatsApp"):
        whatsapp_outbox._recipient_for_lead(_lead(external_contact_id="broken@lid"))


def test_baita_valid_binding_is_ready_for_direct_meta(monkeypatch):
    binding = _binding()
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_workflow_binding_by_id",
        lambda _id: binding,
    )
    assert whatsapp_outbox.resolve_lead_binding(_lead()) == binding


def test_legacy_lead_without_binding_is_repaired_from_active_persona_channel(monkeypatch):
    binding = _binding()
    updates = []
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_active_whatsapp_binding",
        lambda persona_id: binding if persona_id == "persona-baita" else None,
    )
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "update_lead",
        lambda lead_id, payload: updates.append((lead_id, payload)),
    )
    lead = _lead(channel_binding_id=None)

    assert whatsapp_outbox.resolve_lead_binding(lead) == binding
    assert lead["channel_binding_id"] == "binding-baita"
    assert updates == [(7, {"channel_binding_id": "binding-baita"})]


def test_missing_persona_channel_has_actionable_error(monkeypatch):
    monkeypatch.setattr(
        whatsapp_outbox.supabase_client,
        "get_active_whatsapp_binding",
        lambda _persona_id: None,
    )
    with pytest.raises(HTTPException, match="Mensageria da persona nao configurada"):
        whatsapp_outbox.resolve_lead_binding(_lead(channel_binding_id=None))

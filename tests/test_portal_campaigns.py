from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from routes import portal


def request_for(user: dict, access: list[dict]):
    return SimpleNamespace(state=SimpleNamespace(user=user, persona_access=access))


AURORA_VIEW_ONLY = request_for(
    {"id": "u1", "role": "user", "account_type": "client"},
    [{"persona_id": "p1", "persona_slug": "aurora", "can_view": True, "can_edit": False, "can_manage": False}],
)
AURORA_EDITOR = request_for(
    {"id": "u1", "role": "user", "account_type": "client"},
    [{"persona_id": "p1", "persona_slug": "aurora", "can_view": True, "can_edit": True, "can_manage": False}],
)


def _stub_persona(monkeypatch, slug_to_persona: dict):
    monkeypatch.setattr(portal.supabase_client, "get_persona", lambda slug: slug_to_persona.get(slug))


def _preview_body(**overrides):
    payload = {
        "persona_slug": "aurora",
        "purpose": "ofertas_e_novidades",
        "campaign_kind": "consent_request",
        "import_batch_ids": ["batch-1"],
        "audience_id": "audience-1",
    }
    payload.update(overrides)
    return portal.PortalCampaignPreviewBody.model_validate(payload)


def test_campaign_preview_rejects_persona_outside_user_access(monkeypatch):
    _stub_persona(monkeypatch, {"other": {"id": "p2", "slug": "other"}})
    with pytest.raises(HTTPException) as exc:
        portal.portal_campaign_preview(_preview_body(persona_slug="other"), AURORA_EDITOR)
    assert exc.value.status_code == 403


def test_campaign_preview_rejects_view_only_user(monkeypatch):
    _stub_persona(monkeypatch, {"aurora": {"id": "p1", "slug": "aurora"}})
    with pytest.raises(HTTPException) as exc:
        portal.portal_campaign_preview(_preview_body(), AURORA_VIEW_ONLY)
    assert exc.value.status_code == 403


def test_campaign_preview_injects_resolved_persona_id_not_client_supplied(monkeypatch):
    _stub_persona(monkeypatch, {"aurora": {"id": "p1", "slug": "aurora"}})
    captured = {}
    monkeypatch.setattr(
        portal.campaigns_service, "preview_campaign",
        lambda payload: captured.update(payload) or {"ok": True},
    )
    portal.portal_campaign_preview(_preview_body(), AURORA_EDITOR)
    assert captured["persona_id"] == "p1"
    assert "persona_slug" not in captured


def test_create_campaign_rejects_view_only_user(monkeypatch):
    _stub_persona(monkeypatch, {"aurora": {"id": "p1", "slug": "aurora"}})
    body = portal.PortalCampaignCreateBody.model_validate({
        "persona_slug": "aurora", "purpose": "ofertas_e_novidades",
        "campaign_kind": "consent_request", "import_batch_ids": ["batch-1"],
        "audience_id": "audience-1", "name": "Campanha",
        "expected_preview_checksum": "sha256:0123456789abcdef",
        "idempotency_key": "idem-key-12345678", "reason": "Teste controlado",
    })
    with pytest.raises(HTTPException) as exc:
        portal.portal_create_campaign(body, AURORA_VIEW_ONLY)
    assert exc.value.status_code == 403


def test_pause_campaign_rejects_persona_mismatch(monkeypatch):
    _stub_persona(monkeypatch, {"aurora": {"id": "p1", "slug": "aurora"}})
    monkeypatch.setattr(
        portal.campaigns_service, "get_campaign_detail",
        lambda _campaign_id: {"campaign": {"persona_id": "someone-elses-persona", "status": "draft"}},
    )
    body = portal.PortalCampaignStatusBody(expected_revision=1, idempotency_key="idem-key-12345678", reason="Pausar")
    with pytest.raises(HTTPException) as exc:
        portal.portal_pause_campaign("campaign-1", body, AURORA_EDITOR, persona_slug="aurora")
    assert exc.value.status_code == 404


def test_pause_campaign_succeeds_for_editor_on_own_persona(monkeypatch):
    _stub_persona(monkeypatch, {"aurora": {"id": "p1", "slug": "aurora"}})
    monkeypatch.setattr(
        portal.campaigns_service, "get_campaign_detail",
        lambda _campaign_id: {"campaign": {"persona_id": "p1", "status": "draft"}},
    )
    monkeypatch.setattr(
        portal.campaigns_service, "update_campaign_status",
        lambda campaign_id, **kwargs: {"ok": True, "campaign_id": campaign_id, "status": kwargs["status"]},
    )
    body = portal.PortalCampaignStatusBody(expected_revision=1, idempotency_key="idem-key-12345678", reason="Pausar")
    result = portal.portal_pause_campaign("campaign-1", body, AURORA_EDITOR, persona_slug="aurora")
    assert result == {"ok": True, "campaign_id": "campaign-1", "status": "paused"}

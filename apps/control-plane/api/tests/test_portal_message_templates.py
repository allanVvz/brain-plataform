"""Portal-side template lifecycle routes: thin auth/persona-scope wrappers
around the exact same campaigns_service functions the admin routes use.

Exercises the route functions directly (bypassing HTTP/TestClient plumbing,
which has no existing precedent for `routes/portal.py`) with auth/persona
resolution monkeypatched, mirroring how `test_message_templates.py` isolates
the service layer.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routes import portal
from services import auth_service, campaigns_service


@pytest.fixture(autouse=True)
def _fake_auth(monkeypatch):
    monkeypatch.setattr(auth_service, "assert_persona_capability", lambda *_a, **_k: None)
    monkeypatch.setattr(auth_service, "current_user", lambda _request: {"id": "user-1"})


@pytest.fixture(autouse=True)
def _fake_persona(monkeypatch):
    monkeypatch.setattr(
        portal.supabase_client, "get_persona",
        lambda slug: {"id": "persona-1", "slug": slug} if slug == "vz-lupas" else None,
    )


def test_edit_delegates_to_campaigns_service(monkeypatch):
    monkeypatch.setattr(
        campaigns_service, "get_message_template",
        lambda _id: {"id": "tpl-1", "persona_id": "persona-1"},
    )
    called = {}
    monkeypatch.setattr(
        campaigns_service, "edit_message_template",
        lambda template_id, **kwargs: called.update(template_id=template_id, **kwargs) or {"ok": True},
    )

    body = portal.PortalTemplateEditBody(
        expected_revision=1, idempotency_key="key-1", reason="ajuste",
        components=[{"type": "BODY", "text": "Novo texto"}],
    )
    result = portal.portal_edit_template(
        "tpl-1", body, request=None, persona_slug="vz-lupas",
    )

    assert result == {"ok": True}
    assert called["template_id"] == "tpl-1"
    assert called["patch"] == {"components": [{"type": "BODY", "text": "Novo texto"}]}
    assert called["actor_user_id"] == "user-1"


def test_submit_delegates_to_campaigns_service(monkeypatch):
    monkeypatch.setattr(
        campaigns_service, "get_message_template",
        lambda _id: {"id": "tpl-1", "persona_id": "persona-1"},
    )
    called = {}
    monkeypatch.setattr(
        campaigns_service, "submit_message_template",
        lambda template_id, **kwargs: called.update(template_id=template_id, **kwargs) or {"ok": True},
    )

    body = portal.PortalTemplateActionBody(expected_revision=1, idempotency_key="key-1", reason="lancamento")
    result = portal.portal_submit_template("tpl-1", body, request=None, persona_slug="vz-lupas")

    assert result == {"ok": True}
    assert called["template_id"] == "tpl-1"


def test_sync_delegates_to_campaigns_service(monkeypatch):
    monkeypatch.setattr(
        campaigns_service, "get_message_template",
        lambda _id: {"id": "tpl-1", "persona_id": "persona-1"},
    )
    monkeypatch.setattr(
        campaigns_service, "sync_message_template_status",
        lambda template_id: {"id": template_id, "meta_approval_status": "approved"},
    )

    result = portal.portal_sync_template("tpl-1", request=None, persona_slug="vz-lupas")

    assert result["meta_approval_status"] == "approved"


def test_template_from_another_persona_is_404(monkeypatch):
    monkeypatch.setattr(
        campaigns_service, "get_message_template",
        lambda _id: {"id": "tpl-1", "persona_id": "some-other-persona"},
    )

    body = portal.PortalTemplateActionBody(expected_revision=1, idempotency_key="key-1", reason="r")
    with pytest.raises(HTTPException) as exc:
        portal.portal_submit_template("tpl-1", body, request=None, persona_slug="vz-lupas")

    assert exc.value.status_code == 404


def test_unknown_persona_slug_is_404():
    body = portal.PortalTemplateActionBody(expected_revision=1, idempotency_key="key-1", reason="r")
    with pytest.raises(HTTPException) as exc:
        portal.portal_submit_template("tpl-1", body, request=None, persona_slug="no-such-persona")

    assert exc.value.status_code == 404

"""PATCH/GET /personas/{slug}/routing.

Regression coverage for a real bug found live this session: the routing UI
only ever read `personas.process_mode` (a legacy column), never the
`workflow_bindings.metadata.decision_owner` that actually governs live
WhatsApp dispatch. decision_owner had been changed directly on a binding
(as production hotfixes did repeatedly) without process_mode ever being
touched — so the settings UI showed a stale engine while automation
silently ran something else. Also covers the newly-added automation_mode
(persona.config.portal.automation_mode) and the "orquestrador" placeholder
engine, both discovered missing during the same investigation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _admin_request():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "admin-1", "role": "admin"}))


def _routing_row(**overrides):
    base = {
        "slug": "aurora",
        "id": "persona-1",
        "process_mode": "internal",
        "config": {},
        "outbound_webhook_url": None,
        "outbound_webhook_secret": None,
        "inbound_webhook_token": None,
        "migration_applied": True,
        "routing_source": "persona_columns",
    }
    base.update(overrides)
    return base


def test_mask_routing_prefers_live_decision_owner_over_stale_process_mode(monkeypatch):
    from routes import personas

    monkeypatch.setattr(
        personas.supabase_client,
        "get_workflow_bindings",
        lambda _persona_id: [
            {"active": True, "metadata": {"decision_owner": "n8n_agents"}},
        ],
    )
    # process_mode says "internal" (deterministic) but the live binding says
    # n8n_agents — the binding must win.
    masked = personas._mask_routing(_routing_row(process_mode="internal"))
    assert masked["conversation_mode"] == "n8n_agents"
    assert masked["model_required"] is True


def test_mask_routing_falls_back_to_process_mode_without_a_binding(monkeypatch):
    from routes import personas

    monkeypatch.setattr(personas.supabase_client, "get_workflow_bindings", lambda _id: [])
    masked = personas._mask_routing(_routing_row(process_mode="n8n"))
    assert masked["conversation_mode"] == "n8n_agents"


def test_mask_routing_ignores_inactive_bindings(monkeypatch):
    from routes import personas

    monkeypatch.setattr(
        personas.supabase_client,
        "get_workflow_bindings",
        lambda _id: [{"active": False, "metadata": {"decision_owner": "n8n_agents"}}],
    )
    masked = personas._mask_routing(_routing_row(process_mode="internal"))
    assert masked["conversation_mode"] == "deterministic"


def test_mask_routing_exposes_automation_mode_from_persona_config(monkeypatch):
    from routes import personas

    monkeypatch.setattr(personas.supabase_client, "get_workflow_bindings", lambda _id: [])
    masked = personas._mask_routing(
        _routing_row(config={"portal": {"automation_mode": "human_only"}}),
    )
    assert masked["automation_mode"] == "human_only"


def test_mask_routing_defaults_automation_mode_to_ai_with_handoff(monkeypatch):
    from routes import personas

    monkeypatch.setattr(personas.supabase_client, "get_workflow_bindings", lambda _id: [])
    masked = personas._mask_routing(_routing_row(config={}))
    assert masked["automation_mode"] == "ai_with_handoff"


def test_update_routing_accepts_orquestrador_without_requiring_deepseek(monkeypatch):
    """Regression test: orquestrador has no backend implementation yet, so
    switching to it must never require (or touch) DeepSeek provisioning —
    only mark the binding so the dispatch worker's existing
    'unsupported decision owner' guard takes over."""
    from routes import personas

    routing = _routing_row()
    binding_updates = []

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: routing)
    monkeypatch.setattr(
        personas.supabase_client,
        "get_workflow_bindings",
        lambda _id: [{"id": "binding-1", "active": True, "metadata": {}}],
    )
    monkeypatch.setattr(
        personas.supabase_client,
        "update_workflow_binding",
        lambda binding_id, update: binding_updates.append((binding_id, update)),
    )
    monkeypatch.setattr(personas.supabase_client, "update_persona_routing", lambda _slug, _payload: routing)
    monkeypatch.setattr(personas.supabase_client, "insert_event", lambda *a, **k: None)
    monkeypatch.setattr(personas.supabase_client, "get_persona", lambda _slug: {**routing, "name": "Aurora"})

    def _boom(*_a, **_k):
        raise AssertionError("orquestrador must not touch DeepSeek integration lookup")

    monkeypatch.setattr(personas.supabase_client, "get_persona_integration_connection", _boom)

    def _boom_resync(*_a, **_k):
        raise AssertionError("orquestrador must not resync an n8n workflow")

    monkeypatch.setattr(personas.deepseek_n8n_service, "resync_workflow_for_persona", _boom_resync)

    body = personas.RoutingUpdate(conversation_mode="orquestrador")
    personas.update_routing("aurora", body, _admin_request())

    assert binding_updates[0][1]["metadata"]["decision_owner"] == "orquestrador"


def test_update_routing_rejects_unknown_conversation_mode(monkeypatch):
    from fastapi import HTTPException
    from routes import personas

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: _routing_row())

    body = personas.RoutingUpdate(conversation_mode="magic")
    try:
        personas.update_routing("aurora", body, _admin_request())
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_update_routing_n8n_agents_resyncs_the_live_workflow(monkeypatch):
    """Regression test: switching to n8n_agents used to only update
    workflow_bindings metadata (webhook url / workflow id) — it never
    rebuilt or republished the actual n8n workflow content, which had to be
    done by hand over SSH every time all session. The settings UI action
    must trigger that resync itself."""
    from routes import personas

    routing = _routing_row()
    resynced = []

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: routing)
    monkeypatch.setattr(
        personas.supabase_client,
        "get_workflow_bindings",
        lambda _id: [{"id": "binding-1", "active": True, "metadata": {}}],
    )
    monkeypatch.setattr(personas.supabase_client, "update_workflow_binding", lambda *a, **k: None)
    monkeypatch.setattr(personas.supabase_client, "update_persona_routing", lambda _slug, _payload: routing)
    monkeypatch.setattr(personas.supabase_client, "insert_event", lambda *a, **k: None)
    monkeypatch.setattr(
        personas.supabase_client,
        "get_persona_integration_connection",
        lambda _id, _service: {
            "enabled": True,
            "config_json": {
                "n8n_workflow_id": "wf-1",
                "n8n_credential_id": "cred-1",
                "conversation_webhook_path": "aurora/conversation",
            },
        },
    )
    monkeypatch.setattr(personas.supabase_client, "get_persona", lambda _slug: {**routing, "name": "Aurora"})
    monkeypatch.setattr(personas.supabase_client, "save_persona_integration_connection", lambda *a, **k: None)
    monkeypatch.setenv("N8N_BASE_URL", "http://n8n:5678")

    def fake_resync(persona, deepseek_config):
        resynced.append((persona.get("slug"), deepseek_config))
        return {**deepseek_config, "n8n_workflow_id": "wf-1", "conversation_webhook_path": "aurora/conversation"}

    monkeypatch.setattr(personas.deepseek_n8n_service, "resync_workflow_for_persona", fake_resync)

    body = personas.RoutingUpdate(conversation_mode="n8n_agents")
    personas.update_routing("aurora", body, _admin_request())

    assert resynced[0][1]["n8n_workflow_id"] == "wf-1"


def test_update_routing_auto_creates_the_workflow_when_credential_exists_but_workflow_is_missing(monkeypatch):
    """Regression test for the exact bug found live: baita-conveniencia had
    a DeepSeek credential already provisioned (enabled, connected) but no
    n8n_workflow_id — switching to n8n_agents in the UI errored with
    "Configure a chave DeepSeek..." even though a key was already
    configured. The fix must build the workflow from the existing
    credential instead of demanding the key again."""
    from routes import personas

    routing = _routing_row()
    saved_configs = []

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: routing)
    monkeypatch.setattr(
        personas.supabase_client,
        "get_workflow_bindings",
        lambda _id: [{"id": "binding-1", "active": True, "metadata": {}}],
    )
    monkeypatch.setattr(personas.supabase_client, "update_workflow_binding", lambda *a, **k: None)
    monkeypatch.setattr(personas.supabase_client, "update_persona_routing", lambda _slug, _payload: routing)
    monkeypatch.setattr(personas.supabase_client, "insert_event", lambda *a, **k: None)
    monkeypatch.setattr(
        personas.supabase_client,
        "get_persona_integration_connection",
        lambda _id, _service: {
            "enabled": True,
            "config_json": {"n8n_credential_id": "cred-existing"},  # no n8n_workflow_id
        },
    )
    monkeypatch.setattr(personas.supabase_client, "get_persona", lambda _slug: {**routing, "name": "Baita"})
    monkeypatch.setattr(
        personas.supabase_client,
        "save_persona_integration_connection",
        lambda data: saved_configs.append(data),
    )
    monkeypatch.setenv("N8N_BASE_URL", "http://n8n:5678")

    monkeypatch.setattr(
        personas.deepseek_n8n_service,
        "resync_workflow_for_persona",
        lambda _persona, config: {
            **config,
            "n8n_workflow_id": "wf-brand-new",
            "conversation_webhook_path": "baita-conveniencia/conversation",
        },
    )

    body = personas.RoutingUpdate(conversation_mode="n8n_agents")
    result = personas.update_routing("baita-conveniencia", body, _admin_request())

    assert result is not None  # did not raise HTTPException
    assert saved_configs[0]["config_json"]["n8n_workflow_id"] == "wf-brand-new"
    assert saved_configs[0]["service"] == "deepseek"


def test_update_routing_still_rejects_n8n_agents_with_no_credential_at_all(monkeypatch):
    """A persona that was never connected to DeepSeek at all (no
    credential, so no raw key exists anywhere to build one from) must
    still get a clear error, not a crash trying to auto-provision."""
    from fastapi import HTTPException
    from routes import personas

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: _routing_row())
    monkeypatch.setattr(
        personas.supabase_client,
        "get_persona_integration_connection",
        lambda _id, _service: None,
    )

    def _boom(*_a, **_k):
        raise AssertionError("must not attempt to resync without a credential")

    monkeypatch.setattr(personas.deepseek_n8n_service, "resync_workflow_for_persona", _boom)

    body = personas.RoutingUpdate(conversation_mode="n8n_agents")
    try:
        personas.update_routing("aurora", body, _admin_request())
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 409


def test_update_routing_writes_automation_mode_to_persona_portal_config(monkeypatch):
    from routes import personas

    routing = _routing_row(config={"portal": {"other": "kept"}})
    saved_config = {}

    class _FakeUpdateChain:
        def eq(self, *_a, **_k):
            return self

        def execute(self):
            return SimpleNamespace(data=[{}])

    class _FakeTable:
        def update(self, payload):
            saved_config.update(payload.get("config") or {})
            return _FakeUpdateChain()

    class _FakeClient:
        def table(self, _name):
            return _FakeTable()

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: routing)
    monkeypatch.setattr(personas.supabase_client, "get_persona", lambda _slug: {**routing, "config": routing["config"]})
    monkeypatch.setattr(personas.supabase_client, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(personas.supabase_client, "get_workflow_bindings", lambda _id: [])
    monkeypatch.setattr(personas.supabase_client, "insert_event", lambda *a, **k: None)

    body = personas.RoutingUpdate(automation_mode="human_only")
    personas.update_routing("aurora", body, _admin_request())

    assert saved_config["portal"]["automation_mode"] == "human_only"
    assert saved_config["portal"]["other"] == "kept"


def test_update_routing_rejects_invalid_automation_mode(monkeypatch):
    from fastapi import HTTPException
    from routes import personas

    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _user: True)
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _slug: _routing_row())

    body = personas.RoutingUpdate(automation_mode="sometimes")
    try:
        personas.update_routing("aurora", body, _admin_request())
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400

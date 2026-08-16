from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from middleware.auth import is_public_path


def test_public_menu_contract_does_not_expose_nested_admin_routes():
    assert is_public_path("/api/menu/baita-conveniencia") is True
    assert is_public_path("/api/menu/baita-conveniencia/admin-assets") is False
    assert is_public_path("/api/menu/baita-conveniencia/admin-blocks") is False


def test_internal_diagnostics_and_docs_require_session():
    assert is_public_path("/health") is True
    assert is_public_path("/health/ready") is True
    assert is_public_path("/health/storage") is False
    assert is_public_path("/docs") is False
    assert is_public_path("/openapi.json") is False


def test_all_n8n_orchestrated_conversation_steps_bypass_session_auth():
    """Every step n8n calls token-authenticated must skip the session gate.

    Confirmed live 2026-08-08: /internal/conversations/technical-failure was
    added in the graph_agent_runtime_v3 rollout (dd7e8ae) alongside context/
    decide/commit/fail-safe-handoff, but never added here. n8n's Aurora
    workflow sent the correct X-Webhook-Token, but the global session
    middleware rejected it with "Sessao obrigatoria" before the request ever
    reached routes.conversations._authorize's own token check -- so every
    workflow error fell through its own quarantine/failsafe node too,
    terminating the execution before it ever reached Respond to Webhook and
    producing an HTTP 200 with an empty body for the real caller.
    """
    for path in (
        "/internal/conversations/context",
        "/internal/conversations/decide",
        "/internal/conversations/commit",
        "/internal/conversations/fail-safe-handoff",
        "/internal/conversations/technical-failure",
    ):
        assert is_public_path(path) is True, path


def test_internal_journey_events_use_webhook_auth_but_operator_route_requires_session():
    assert is_public_path("/internal/agents/leads/42/journey-events") is True
    assert is_public_path("/internal/agents/leads/not-a-number/journey-events") is False
    assert is_public_path("/agents/leads/42/journey-events") is False

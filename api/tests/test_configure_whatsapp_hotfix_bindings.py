"""Regression test for the 2026-08-01 deploy-time binding revert.

configure_whatsapp_hotfix_bindings.py runs on every deploy
(ops/vps/deploy.sh's configure_whatsapp_bindings step) and used to
unconditionally force both the Meta and Evolution bindings back to
decision_owner=deterministic — silently undoing an intentional activation
of Aurora's n8n_agents flow on the very next deploy. Baita/meta_cloud
must always be forced back (it never uses the agentic engine); Aurora/
evolution_baileys should be left alone when it's already a complete,
valid n8n_agents configuration.
"""
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.configure_whatsapp_hotfix_bindings import _is_complete_n8n_agents_binding


def test_complete_n8n_agents_binding_is_recognized():
    binding = {
        "n8n_workflow_id": "wf-123",
        "metadata": {
            "decision_owner": "n8n_agents",
            "conversation_webhook_url": "http://n8n:5678/webhook/aurora/conversation",
        },
    }
    assert _is_complete_n8n_agents_binding(binding) is True


def test_deterministic_binding_is_not_preserved():
    binding = {"n8n_workflow_id": None, "metadata": {"decision_owner": "deterministic"}}
    assert _is_complete_n8n_agents_binding(binding) is False


def test_half_configured_n8n_agents_binding_is_not_preserved():
    """decision_owner flipped to n8n_agents but missing a workflow id or
    webhook is exactly as dangerous as before — must still be reset."""
    missing_workflow = {
        "n8n_workflow_id": None,
        "metadata": {
            "decision_owner": "n8n_agents",
            "conversation_webhook_url": "http://n8n:5678/webhook/aurora/conversation",
        },
    }
    assert _is_complete_n8n_agents_binding(missing_workflow) is False

    missing_webhook = {
        "n8n_workflow_id": "wf-123",
        "metadata": {"decision_owner": "n8n_agents", "conversation_webhook_url": ""},
    }
    assert _is_complete_n8n_agents_binding(missing_webhook) is False


def test_empty_binding_is_not_preserved():
    assert _is_complete_n8n_agents_binding({}) is False

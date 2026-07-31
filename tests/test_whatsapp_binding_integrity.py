from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import supabase_client


def test_binding_integrity_migration_covers_switch_backfill_and_trigger():
    sql = (
        ROOT
        / "supabase"
        / "migrations"
        / "067_whatsapp_binding_integrity.sql"
    ).read_text(encoding="utf-8")

    assert "activate_persona_whatsapp_binding" in sql
    assert "idx_workflow_bindings_one_active_whatsapp_per_persona" in sql
    assert "UPDATE public.leads" in sql
    assert "whatsapp.binding_activated" in sql
    assert "whatsapp.binding_backfilled" in sql
    assert "CREATE TRIGGER trg_enforce_lead_channel_binding" in sql
    assert "Lead channel binding belongs to another persona" in sql
    assert "'transport_mode', 'provider_direct'" in sql


def test_provider_direct_guard_removes_and_rejects_every_legacy_n8n_route():
    sql = (
        ROOT
        / "supabase"
        / "migrations"
        / "069_block_legacy_n8n_direct_transport.sql"
    ).read_text(encoding="utf-8")

    assert "- 'outbound_webhook_url'" in sql
    assert "- 'n8n_outbound_webhook_url'" in sql
    assert "- 'conversation_webhook_url'" in sql
    assert "n8n_workflow_id = NULL" in sql
    assert "CREATE TRIGGER trg_enforce_whatsapp_provider_direct_contract" in sql
    assert "Provider-direct WhatsApp binding cannot reference n8n" in sql
    assert "whatsapp.binding_n8n_route_removed" in sql


def test_activate_binding_uses_single_transactional_rpc(monkeypatch):
    captured = {}

    class Query:
        def execute(self):
            return SimpleNamespace(data={
                "ok": True,
                "provider": "evolution_baileys",
                "binding_id": "binding-2",
                "rebound_leads": 6,
            })

    class Client:
        def rpc(self, name, payload):
            captured.update({"name": name, "payload": payload})
            return Query()

    monkeypatch.setattr(supabase_client, "get_client", lambda: Client())

    result = supabase_client.activate_whatsapp_binding(
        persona_id="persona-1",
        binding_id="binding-2",
        provider="evolution_baileys",
        source="test",
    )

    assert result["rebound_leads"] == 6
    assert captured == {
        "name": "activate_persona_whatsapp_binding",
        "payload": {
            "p_persona_id": "persona-1",
            "p_binding_id": "binding-2",
            "p_provider": "evolution_baileys",
            "p_source": "test",
        },
    }

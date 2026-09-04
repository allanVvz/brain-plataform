from __future__ import annotations

import json

import pytest

from scripts import resync_graph_agent_workflows as resync
from services import deepseek_n8n_service


MODEL_BINDING = {
    "model": "fixture-model",
    "endpoint": "https://models.example.test/chat/completions",
    "reply_source": "fixture-model",
}


def _personas():
    return {
        "aurora": {
            "id": "persona-aurora",
            "slug": "aurora",
            "name": "Aurora",
            "config": {"agent_slug": "sdr_qualificacao_carro"},
        },
        "vz-lupas": {
            "id": "persona-vz-lupas",
            "slug": "vz-lupas",
            "name": "VZ Lupas",
            "config": {"agent_slug": "sdr_sales_retail"},
        },
    }


def _install_read_fixtures(monkeypatch, *, incomplete_vz=False):
    personas = _personas()
    configs = {
        slug: {
            "n8n_credential_id": f"credential-{slug}",
            "n8n_workflow_id": f"workflow-{slug}",
            **MODEL_BINDING,
        }
        for slug in personas
    }
    if incomplete_vz:
        configs["vz-lupas"].pop("endpoint")

    monkeypatch.setattr(
        resync.supabase_client,
        "get_persona",
        lambda slug: personas.get(slug),
    )
    monkeypatch.setattr(
        resync.supabase_client,
        "get_active_graph_publication",
        lambda persona_id: {"id": f"publication-{persona_id}"},
    )
    monkeypatch.setattr(
        resync.supabase_client,
        "get_persona_integration_connection",
        lambda persona_id, service: {
            "id": f"connection-{persona_id}",
            "persona_id": persona_id,
            "service": service,
            "config_json": configs[personas_by_id(personas, persona_id)["slug"]],
        },
    )
    monkeypatch.setattr(
        resync.supabase_client,
        "get_workflow_bindings",
        lambda persona_id: [{
            "id": f"binding-{persona_id}",
            "active": True,
            "n8n_workflow_id": f"workflow-{personas_by_id(personas, persona_id)['slug']}",
            "metadata": {},
        }],
    )
    monkeypatch.setattr(resync.n8n_client, "get_workflow", lambda _workflow_id: {})
    return personas, configs


def personas_by_id(personas, persona_id):
    return next(persona for persona in personas.values() if persona["id"] == persona_id)


def test_joint_resync_prepares_both_personas_before_any_mutation(monkeypatch):
    _install_read_fixtures(monkeypatch, incomplete_vz=True)
    mutations = []
    monkeypatch.setattr(
        resync.deepseek_n8n_service,
        "resync_workflow_for_persona",
        lambda *_args, **_kwargs: mutations.append("workflow"),
    )
    monkeypatch.setattr(
        resync.supabase_client,
        "save_persona_integration_connection",
        lambda *_args, **_kwargs: mutations.append("connection"),
    )

    with pytest.raises(RuntimeError, match="audited model binding incomplete for vz-lupas"):
        resync.run(
            ["aurora", "vz-lupas"],
            active_personas={"aurora", "vz-lupas"},
        )

    assert mutations == []


def test_joint_resync_is_idempotent_and_keeps_bindings_isolated(monkeypatch):
    _personas_by_slug, configs = _install_read_fixtures(monkeypatch)
    workflow_calls = []
    saved_connections = []
    events = []
    binding_updates = []

    def sync(persona, config, *, activate_workflow):
        workflow_calls.append((persona["slug"], activate_workflow))
        return {
            **config,
            "n8n_workflow_id": f"workflow-{persona['slug']}",
            "workflow_checksum": f"sha256:{persona['slug']}",
            "workflow_template": "graph_agentic_v3",
            "conversation_webhook_path": f"{persona['slug']}/conversation",
            "model": config["model"],
            "endpoint": config["endpoint"],
            "reply_source": config["reply_source"],
        }

    monkeypatch.setattr(
        resync.deepseek_n8n_service,
        "resync_workflow_for_persona",
        sync,
    )
    monkeypatch.setattr(
        resync.supabase_client,
        "save_persona_integration_connection",
        lambda value: saved_connections.append(value),
    )
    monkeypatch.setattr(
        resync.supabase_client,
        "insert_event",
        lambda value, source: events.append((value, source)),
    )
    monkeypatch.setattr(
        resync,
        "_binding_update",
        lambda persona, binding, result: binding_updates.append(
            (persona["slug"], binding["id"], result["conversation_webhook_path"])
        )
        or binding["id"],
    )

    first = resync.run(
        ["aurora", "vz-lupas"],
        active_personas={"aurora", "vz-lupas"},
    )
    second = resync.run(
        ["aurora", "vz-lupas"],
        active_personas={"aurora", "vz-lupas"},
    )

    assert first == second
    assert workflow_calls == [
        ("aurora", True),
        ("vz-lupas", True),
        ("aurora", True),
        ("vz-lupas", True),
    ]
    assert {item["config_json"]["n8n_workflow_id"] for item in saved_connections} == {
        "workflow-aurora",
        "workflow-vz-lupas",
    }
    assert {item[1] for item in binding_updates} == {
        "binding-persona-aurora",
        "binding-persona-vz-lupas",
    }
    assert {item[2] for item in binding_updates} == {
        "aurora/conversation",
        "vz-lupas/conversation",
    }
    assert len(events) == 4
    assert configs["aurora"] is not configs["vz-lupas"]


def test_aurora_and_vz_render_same_template_without_cross_persona_knowledge():
    personas = _personas()
    rendered = {
        slug: deepseek_n8n_service._workflow_for_persona(
            persona,
            credential_id=f"credential-{slug}",
            credential_name=f"Brain DeepSeek - {slug}",
            model_binding=MODEL_BINDING,
        )
        for slug, persona in personas.items()
    }

    aurora = rendered["aurora"]
    vz_lupas = rendered["vz-lupas"]
    assert [
        (node["id"], node["type"]) for node in aurora["nodes"]
    ] == [
        (node["id"], node["type"]) for node in vz_lupas["nodes"]
    ]
    assert aurora["connections"] == vz_lupas["connections"]
    assert aurora["meta"]["binding"]["pipeline_contract"] == "conversation_v3"
    assert vz_lupas["meta"]["binding"]["pipeline_contract"] == "conversation_v3"
    assert "vz-lupas" not in json.dumps(aurora, ensure_ascii=False).lower()
    assert "vz lupas" not in json.dumps(aurora, ensure_ascii=False).lower()
    assert "aurora" not in json.dumps(vz_lupas, ensure_ascii=False).lower()

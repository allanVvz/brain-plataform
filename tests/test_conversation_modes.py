from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import personas, whatsapp
from services import conversation_runtime, wa_validator_service
from services.sdr_documents import compile_persona_documents
from workers.whatsapp_dispatch_worker import WhatsAppDispatchWorker


def test_active_whatsapp_binding_accepts_every_contact():
    binding = {"metadata": {"mode": "active", "allowlist": []}}
    assert whatsapp._allowed(binding, "551100000001") is True
    assert whatsapp._allowed(binding, "559999999999") is True


def test_routing_exposes_public_conversation_modes_without_new_storage():
    deterministic = personas._mask_routing(
        {"slug": "baita", "id": "p1", "process_mode": "internal"}
    )
    n8n = personas._mask_routing(
        {"slug": "baita", "id": "p1", "process_mode": "n8n"}
    )
    assert deterministic["conversation_mode"] == "deterministic"
    assert n8n["conversation_mode"] == "n8n_agents"
    assert deterministic["pipeline_contract"] == n8n["pipeline_contract"] == "conversation_v1"
    assert deterministic["classifier"] == n8n["classifier"] == "deterministic_v1"
    assert deterministic["model_required"] is False


def test_deterministic_worker_uses_canonical_pipeline_without_n8n(monkeypatch):
    calls: list[dict] = []
    completed: list[tuple] = []
    row = {
        "id": "buffer-1",
        "direction": "inbound",
        "persona_id": "persona-1",
        "lead_ref": 44,
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": "business-1",
        "external_message_id": "wamid-1",
        "correlation_id": "corr-1",
        "payload": {"text": "Oi"},
    }
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _id: {
            "id": "persona-1",
            "slug": "baita-conveniencia",
            "process_mode": "internal",
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _ref: {"id": 44, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda _lead_ref, limit=20: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _binding_id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {"decision_owner": "deterministic", "mode": "active"},
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.mark_whatsapp_attempt",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.conversation_runtime.execute_pipeline",
        lambda **kwargs: calls.append(kwargs)
        or {
            "handoff": False,
            "classifier": "deterministic_v1",
            "route": "SDR",
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.n8n_client.send_to_webhook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("deterministic mode must not call n8n")
        ),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *args, **kwargs: completed.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *_args, **_kwargs: None,
    )

    WhatsAppDispatchWorker()._dispatch_inbound(row)

    assert calls[0]["persona_slug"] == "baita-conveniencia"
    assert calls[0]["message_id"] == "wamid-1"
    assert completed[0][0] == ("buffer-1", "sent")


def test_n8n_and_local_modes_use_the_same_three_stage_contract():
    workflow = json.loads(
        (ROOT / "api" / "n8n-workflows" / "baita-vitoria.json").read_text(
            encoding="utf-8"
        )
    )
    urls = [
        node.get("parameters", {}).get("url", "")
        for node in workflow["nodes"]
    ]
    assert any("/internal/conversations/context" in url for url in urls)
    assert any("/internal/conversations/decide" in url for url in urls)
    assert any("/internal/conversations/commit" in url for url in urls)
    source = inspect.getsource(conversation_runtime.execute_pipeline)
    assert source.index("build_context(") < source.index("decide(") < source.index("commit(")
    assert workflow["meta"]["binding"]["classifier"] == "deterministic_v1"
    assert workflow["meta"]["binding"]["model_required"] is False


def test_wa_validator_generates_from_graph_without_model_or_allowlist(monkeypatch):
    graph = compile_persona_documents(
        ROOT / "docs" / "sdr",
        "baita-conveniencia",
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {
            "id": "persona-1",
            "slug": "baita-conveniencia",
            "name": "Baita Conveniência",
        },
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona_routing",
        lambda _slug: {"process_mode": "internal"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "insert_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        wa_validator_service.graph_json_v2_store,
        "load_current",
        lambda _slug: (7, graph),
    )
    monkeypatch.setattr(
        wa_validator_service.graph_json_v2_store,
        "latest_event",
        lambda _slug: {"payload": {"checksum": "graph-checksum"}},
    )

    result = wa_validator_service.generate_script(
        "baita-conveniencia",
        "compra_simples",
        "Vitoria",
    )

    script = result["script"]
    assert script["target"] == "Vitoria"
    assert script["target_phone"] == "+555131916538"
    assert script["meta"]["model"] == "none"
    assert script["meta"]["classifier"] == "deterministic_v1"
    assert script["meta"]["conversation_mode"] == "deterministic"
    assert script["expected_dialogue"]["unit_price"] is not None
    assert "get_router" not in inspect.getsource(
        wa_validator_service.generate_script
    )

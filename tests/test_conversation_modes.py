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
    assert n8n["model_required"] is True
    assert n8n["field_extractor"] == "deepseek-v4-flash"


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
    assert workflow["meta"]["binding"]["model_required"] is True
    assert workflow["meta"]["binding"]["field_extractor"] == "deepseek-v4-flash"


def test_aurora_agentic_workflow_uses_generated_prompt_and_golden_dataset_rag():
    """Regression test for the 2026-08-01 agentic-flow redesign.

    Draft agentic reply used to embed one hardcoded, Aurora-specific
    system prompt string directly in the workflow JSON, and grounded the
    model in rag_nodes (the deterministic engine's simple graph-node
    keyword filter) instead of the real Golden Dataset RAG layer
    (knowledge_rag_entries/knowledge_rag_chunks via search_active_rag_
    chunks). Any other persona put on this template would have gotten
    Aurora's literal prompt. The node must now consume the dynamically
    generated `system_prompt` and `rag_chunks` fields that
    conversation_runtime.build_context() produces per persona.
    """
    workflow = json.loads(
        (ROOT / "api" / "n8n-workflows" / "aurora-conversation.json").read_text(
            encoding="utf-8"
        )
    )
    draft_node = next(
        node for node in workflow["nodes"] if node["name"] == "Draft agentic reply"
    )
    body = draft_node["parameters"]["body"]
    assert "system_prompt" in body
    assert "rag_chunks" in body
    # No hardcoded business-specific vocabulary left in the workflow file.
    assert "estetica automotiva" not in body.lower()
    assert "estética automotiva" not in body.lower()


def test_aurora_agentic_workflow_requests_and_forwards_extracted_fields():
    """Regression test for the 2026-08-01 multi-field extraction fix.

    A customer answering several missing fields in one message ("meu
    nome é Allan, carro é Tracker 2024") only ever got the first one
    captured by deterministic_appointment._collect(). Draft agentic reply
    must tell the model which fields are still missing (so it knows what
    keys to use) and Merge model reply safely must parse and forward
    extracted_fields through to /internal/conversations/commit, which
    applies them via conversation_runtime._merge_extracted_fields.
    """
    workflow = json.loads(
        (ROOT / "api" / "n8n-workflows" / "aurora-conversation.json").read_text(
            encoding="utf-8"
        )
    )
    draft_node = next(
        node for node in workflow["nodes"] if node["name"] == "Draft agentic reply"
    )
    # The request tells the model which fields are still missing (so it
    # knows what keys to use); the instruction to return extracted_fields
    # itself lives in the dynamically-generated system_prompt (tested in
    # test_aurora_appointment_runtime.py), not hardcoded in this file.
    assert "missing_fields" in draft_node["parameters"]["body"]
    assert "informacoes_pendentes" in draft_node["parameters"]["body"]

    merge_node = next(
        node for node in workflow["nodes"] if node["name"] == "Merge model reply safely"
    )
    js_code = merge_node["parameters"]["jsCode"]
    assert "extracted_fields" in js_code
    assert "extractedFields" in js_code

    persist_node = next(
        node for node in workflow["nodes"] if node["name"] == "Persist once and enqueue send"
    )
    # response is forwarded wholesale, so extracted_fields rides along
    # without needing its own explicit mention here.
    assert "response: $json.response" in persist_node["parameters"]["body"]


def test_aurora_agentic_workflow_does_not_duplicate_the_price_safety_check():
    """Regression test for the 2026-08-02 finding: the Merge node's own
    'is this reply unsafe' check flagged any bare 'R$' + digit as unsafe,
    discarding a compliant DeepSeek reply that correctly asked for the
    customer's name after mentioning a starting price — falling back to
    the deterministic engine's plain price fact, which never asks
    anything. That safety guarantee already exists, correctly, exactly
    once, server-side (conversation_runtime._reply_confirms_price_or_
    schedule, which requires confirmation language AND a price/date token
    together) — the workflow must not duplicate a cruder version of it.
    """
    workflow = json.loads(
        (ROOT / "api" / "n8n-workflows" / "aurora-conversation.json").read_text(
            encoding="utf-8"
        )
    )
    merge_node = next(
        node for node in workflow["nodes"] if node["name"] == "Merge model reply safely"
    )
    js_code = merge_node["parameters"]["jsCode"]
    assert "unsafePatterns" not in js_code
    assert r"r\$" not in js_code


def test_n8n_workflow_js_code_nodes_never_contain_a_dangerous_line_comment():
    """Regression test for a real deploy break, 2026-08-02: a Code node's
    jsCode written as one continuous string with no real newlines silently
    loses everything after a `//` comment — including the return statement
    — and n8n fails the whole execution with "Code doesn't return items
    properly". Confirmed live: this exact mistake was made once already
    while adding an explanatory comment to the Merge node's jsCode.
    A `//` is only unsafe when the script has no real newlines at all (a
    genuinely multi-line script, like whatsapp-error-handler.json's, is
    normal JS and each `//` only swallows its own line, as intended).
    """
    for workflow_path in (ROOT / "api" / "n8n-workflows").glob("*.json"):
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        for node in workflow.get("nodes", []):
            js_code = node.get("parameters", {}).get("jsCode")
            if not js_code or "\n" in js_code:
                continue
            assert "//" not in js_code, (
                f"{workflow_path.name}::{node['name']} is a single-line "
                "script with a // comment — it will swallow everything "
                "after it, including any return statement. Use /* */ "
                "instead, or a real newline."
            )


def test_aurora_agentic_workflow_requests_and_forwards_identified_service_slug():
    """Regression test for the 2026-08-01 service-inference fix.

    A customer describing a symptom ("risco fundo na porta") got a reply
    that correctly recommended chapeacao, but the service was never
    captured structurally — extracted_fields only covers what the
    customer explicitly says. Draft agentic reply must expose the real
    service catalog (so the model can name a real slug) and Merge model
    reply safely must parse and forward identified_service_slug through
    to /internal/conversations/commit, which validates and applies it via
    conversation_runtime._resolve_identified_service.
    """
    workflow = json.loads(
        (ROOT / "api" / "n8n-workflows" / "aurora-conversation.json").read_text(
            encoding="utf-8"
        )
    )
    draft_node = next(
        node for node in workflow["nodes"] if node["name"] == "Draft agentic reply"
    )
    assert "servicos_disponiveis" in draft_node["parameters"]["body"]
    assert "available_services" in draft_node["parameters"]["body"]

    merge_node = next(
        node for node in workflow["nodes"] if node["name"] == "Merge model reply safely"
    )
    js_code = merge_node["parameters"]["jsCode"]
    assert "identified_service_slug" in js_code
    assert "identifiedServiceSlug" in js_code


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

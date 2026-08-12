from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest


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


def test_routing_exposes_public_conversation_modes_without_new_storage(monkeypatch):
    # No active binding for either persona here — _mask_routing now prefers
    # the live binding's decision_owner (the real production routing
    # switch) and only falls back to process_mode when none exists, which
    # is exactly the fallback path this test exercises.
    monkeypatch.setattr(personas.supabase_client, "get_workflow_bindings", lambda _id: [])
    deterministic = personas._mask_routing(
        {"slug": "baita", "id": "p1", "process_mode": "internal"}
    )
    n8n = personas._mask_routing(
        {"slug": "baita", "id": "p1", "process_mode": "n8n"}
    )
    assert deterministic["conversation_mode"] == "deterministic"
    assert n8n["conversation_mode"] == "n8n_agents"
    assert deterministic["pipeline_contract"] == n8n["pipeline_contract"] == "conversation_v1"
    assert deterministic["classifier"] == "deterministic_v1"
    assert n8n["classifier"] is None
    assert deterministic["model_required"] is False
    assert n8n["model_required"] is True
    assert n8n["field_extractor"] is None


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
            # Legacy persona-wide pause data must not override the lead's
            # eyebrow toggle state.
            "config": {"portal": {"automation_mode": "human_only"}},
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


def test_n8n_worker_rejects_empty_http_200_as_an_invalid_result(monkeypatch):
    row = {
        "id": "buffer-n8n",
        "direction": "inbound",
        "persona_id": "persona-1",
        "lead_ref": 44,
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": None,
        "external_message_id": "wamid-n8n",
        "correlation_id": "corr-n8n",
        "payload": {"text": "Quero atendimento"},
    }
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _id: {"id": "persona-1", "slug": "generic", "config": {}},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _ref: {"id": 44, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _id: {
            "id": "binding-1",
            "persona_id": "persona-1",
            "active": True,
            "metadata": {
                "decision_owner": "n8n_agents",
                "conversation_webhook_url": "https://n8n.example.test/webhook/generic",
            },
        },
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.mark_whatsapp_attempt",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.n8n_client.send_to_webhook",
        lambda *_args, **_kwargs: (200, "{}"),
    )

    with pytest.raises(RuntimeError, match="invalid result contract"):
        WhatsAppDispatchWorker()._dispatch_inbound(row)


def test_echo_guard_ignores_short_common_replies(monkeypatch):
    """Regression test for the 2026-08-04 Baita false-positive handoff.

    The bot-loop echo guard compares inbound text against recent outbound
    messages for an exact match. A customer replying "oi" — the same
    greeting the bot itself had sent earlier in the conversation — used to
    match and get permanently handed off on every message, even though this
    is completely ordinary conversation, not a WhatsApp-side echo loop.
    """
    calls: list[dict] = []
    handoffs: list[int] = []
    completed: list[tuple] = []
    row = {
        "id": "buffer-2",
        "direction": "inbound",
        "persona_id": "persona-1",
        "lead_ref": 44,
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": "business-1",
        "external_message_id": "wamid-2",
        "correlation_id": "corr-2",
        "payload": {"text": "oi"},
    }
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _id: {"id": "persona-1", "slug": "baita-conveniencia", "process_mode": "internal"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _ref: {"id": 44, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda _lead_ref, limit=20: [
            {"id": 627, "direction": "outbound", "content": "oi"},
        ],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.handoff_whatsapp_lead",
        lambda lead_ref: handoffs.append(lead_ref),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_workflow_binding_by_id",
        lambda _binding_id: {
            "id": "binding-1", "persona_id": "persona-1", "active": True,
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
        or {"handoff": False, "classifier": "deterministic_v1", "route": "SDR"},
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

    assert handoffs == []
    assert len(calls) == 1
    assert completed[0][0] == ("buffer-2", "sent")


def test_echo_guard_still_suppresses_long_distinctive_replies(monkeypatch):
    """The original protection must still hold for real echo candidates —
    a long, distinctive bot reply coming back verbatim as "inbound" is a
    genuine signal, unlike a short greeting."""
    handoffs: list[int] = []
    completed: list[tuple] = []
    events: list[tuple] = []
    long_text = "Vou encaminhar sua conversa para a Equipe Aurora confirmar o valor final."
    row = {
        "id": "buffer-3",
        "direction": "inbound",
        "persona_id": "persona-1",
        "lead_ref": 44,
        "channel_binding_id": "binding-1",
        "whatsapp_phone_number_id": "business-1",
        "external_message_id": "wamid-3",
        "correlation_id": "corr-3",
        "payload": {"text": long_text},
    }
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_persona_by_id",
        lambda _id: {"id": "persona-1", "slug": "aurora", "process_mode": "internal"},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_lead_by_ref",
        lambda _ref: {"id": 44, "ai_paused": False},
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.get_messages",
        lambda _lead_ref, limit=20: [
            {"id": 900, "direction": "outbound", "content": long_text},
        ],
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.handoff_whatsapp_lead",
        lambda lead_ref: handoffs.append(lead_ref),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.supabase_client.complete_whatsapp_buffer",
        lambda *args, **kwargs: completed.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "workers.whatsapp_dispatch_worker.event_emitter.emit",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    WhatsAppDispatchWorker()._dispatch_inbound(row)

    assert handoffs == [44]
    assert completed[0][0] == ("buffer-3", "waiting_human")
    assert events[0][0][0] == "whatsapp.bot_loop_suppressed"


def test_n8n_agentic_template_and_local_mode_are_distinct_contracts():
    workflow = json.loads(
        (ROOT / "api" / "n8n-workflows" / "persona-conversation-template.json").read_text(
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
    assert workflow["meta"]["template"] == "graph_agentic_v3"
    assert workflow["meta"]["binding"]["model_required"] is True
    assert "Model required for turn" in {
        node["name"] for node in workflow["nodes"]
    }
    gate = workflow["connections"]["Model required for turn"]["main"]
    assert gate[0][0]["node"] == "Build graph grounded agent request"
    assert gate[1][0]["node"] == "Align reply with qualification state"
    assert workflow["meta"]["binding"]["reply_source"] == "__REPLY_SOURCE__"
    assert workflow["meta"]["binding"]["model"] == "__MODEL__"
    assert workflow["meta"]["binding"]["endpoint"] == "__MODEL_ENDPOINT__"


def test_technical_failure_captures_which_node_failed_and_why_without_handoff():
    """Regression test for the 2026-08-04 Baita silent-failure investigation.

    The canonical template's old fail-safe node used to send a static
    reason: 'workflow_step_failed' to /internal/conversations/fail-safe-handoff
    on any pipeline error, and Baita's workflow settings additionally
    discarded error execution data (saveDataErrorExecution: 'none') — so a
    failure was neither visible in n8n's own execution history nor
    diagnosable from our own system_events. The reason expression must now
    include the error node name and the actual error payload,
    and error executions must be retained.
    """
    for filename in ("persona-conversation-template.json",):
        workflow = json.loads(
            (ROOT / "api" / "n8n-workflows" / filename).read_text(encoding="utf-8")
        )
        assert workflow["settings"]["saveDataErrorExecution"] == "all"
        fail_safe = next(
            node for node in workflow["nodes"] if node.get("id") == "failsafe"
        )
        assert fail_safe["name"] == "Quarantine technical failure"
        assert "/internal/conversations/technical-failure" in fail_safe["parameters"]["url"]
        assert "fail-safe-handoff" not in fail_safe["parameters"]["url"]
        body = fail_safe["parameters"]["body"]
        assert "failed_node" in body
        assert "$json.error" in body
        assert "http_code" in body
        assert "workflow_template" in body
        assert "JSON.stringify($json).slice" not in body
        assert "reason: 'workflow_step_failed'," not in body


def test_canonical_agentic_workflow_uses_compact_graph_context():
    workflow = json.loads((ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8"))
    code = next(node for node in workflow["nodes"] if node["name"] == "Build graph grounded agent request")["parameters"]["jsCode"]
    assert "context_cards" in code and "approved_chunks" in code
    assert "rendered_content" not in code
    assert "prompt_budget_exceeded" in code


def test_canonical_agentic_workflow_forwards_semantic_observations():
    workflow = json.loads((ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8"))
    request = next(node for node in workflow["nodes"] if node["name"] == "Build graph grounded agent request")["parameters"]["jsCode"]
    validate = next(node for node in workflow["nodes"] if node["name"] == "Validate agent response")["parameters"]["jsCode"]
    persist = next(node for node in workflow["nodes"] if node["name"] == "Persist once and enqueue send")["parameters"]["body"]
    assert "extracted_facts" in request and "extracted_facts" in validate
    assert "response: $json.response" in persist


def test_canonical_agentic_workflow_does_not_duplicate_the_price_safety_check():
    workflow = json.loads((ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8"))
    js_code = "\n".join(
        node.get("parameters", {}).get("jsCode", "")
        for node in workflow["nodes"]
    )
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


def test_canonical_agentic_workflow_uses_graph_branch_identity_for_service():
    workflow = json.loads((ROOT / "api/n8n-workflows/persona-conversation-template.json").read_text(encoding="utf-8"))
    request = next(node for node in workflow["nodes"] if node["name"] == "Build graph grounded agent request")["parameters"]["jsCode"]
    validate = next(node for node in workflow["nodes"] if node["name"] == "Validate agent response")["parameters"]["jsCode"]
    assert "branch_anchor_node_id" in request and "branch_anchor_node_id" in validate


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
        "get_workflow_bindings",
        lambda _persona_id: [],
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "insert_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_active_graph_publication",
        lambda _persona_id: None,
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
    _install_fake_wa_validator_session_store(monkeypatch)

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


def test_wa_validator_conversation_mode_follows_active_binding_not_legacy_process_mode(
    monkeypatch,
):
    """The validator must test the same engine real WhatsApp traffic uses.

    Confirmed live 2026-08-08: Aurora's legacy persona.process_mode column
    said "n8n", but the persona's actual active binding had already been
    switched to decision_owner="deterministic" (the engine really serving
    customers) without process_mode ever being updated -- the same class of
    staleness routes.personas._mask_routing was fixed for. The validator
    read only process_mode, so it POSTed every step to an n8n webhook
    nobody maintains and failed 8/8 with a JSON decode error, while real
    customers were being served correctly the whole time.
    """
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_workflow_bindings",
        lambda _persona_id: [
            {"active": True, "metadata": {"decision_owner": "deterministic"}},
        ],
    )

    assert (
        wa_validator_service._resolve_conversation_mode(
            "persona-1", {"process_mode": "n8n"}
        )
        == "deterministic"
    )


def _install_fake_wa_validator_session_store(monkeypatch) -> dict:
    """In-memory stand-in for the Supabase-backed WA Validator session store.

    Sessions moved out of a plain in-process dict into Supabase (2026-08-08,
    fixing "Sessão não encontrada" under multiple gunicorn workers), so
    tests that used to poke wa_validator_service._sessions directly now
    monkeypatch the three supabase_client functions it calls through.
    """
    store: dict[str, dict] = {}
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "get_wa_validator_session",
        lambda session_id: store.get(session_id),
    )

    def _upsert(session_id, data, persona_slug=None, flow_id=None):
        store[session_id] = data
        return data

    monkeypatch.setattr(
        wa_validator_service.supabase_client, "upsert_wa_validator_session", _upsert,
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "list_wa_validator_sessions",
        lambda limit=100, **_filters: list(store.values()),
    )
    def _claim(session_id):
        session = store.get(session_id)
        if not session:
            return {"claimed": False, "state": "missing"}
        if session.get("status") != "ready":
            return {"claimed": False, "state": session.get("status"), "session": session}
        session = {**session, "status": "running"}
        store[session_id] = session
        return {"claimed": True, "state": "running", "session": session}

    monkeypatch.setattr(
        wa_validator_service.supabase_client, "claim_wa_validator_session", _claim,
    )
    return store


def test_wa_validator_analyze_gaps_scores_zero_when_every_reply_fails(monkeypatch):
    """A session where the bot never actually replies must not score 100%.

    Confirmed live 2026-08-08: an Aurora session where all 8 steps failed
    with "(erro: ...)" still scored 100% overall_score, because bot_turns
    counted every role=="bot" entry -- including timed-out/errored ones --
    as a successful response. Score must reflect the failures already
    counted into `gaps`/`transport_or_reply`.
    """
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "insert_event", lambda *_a, **_k: None
    )
    store = _install_fake_wa_validator_session_store(monkeypatch)
    session_id = "session-all-failed"
    conversation = []
    for i in range(3):
        conversation.append({"role": "validator", "text": f"msg {i}"})
        conversation.append(
            {
                "role": "bot",
                "text": "(erro: Expecting value: line 1 column 1 (char 0))",
                "error": True,
                "error_detail": "Traceback (most recent call last): ...",
            }
        )
    store[session_id] = {
        "id": session_id,
        "persona_slug": "aurora",
        "flow_id": "compra_simples",
        "status": "done",
        "script": {
            "expected_knowledge": ["graph:10:sha256:abc"],
            "meta": {"graph_version": 10, "graph_checksum": "sha256:abc"},
        },
        "output": {"conversation": conversation},
        "insights": None,
        "created_at": "2026-08-08T00:00:00+00:00",
        "updated_at": "2026-08-08T00:00:00+00:00",
    }

    insights = wa_validator_service.analyze_gaps(session_id)

    assert insights["overall_score"] == 0
    assert any(gap["topic"] == "transport_or_reply" for gap in insights["gaps"])
    assert not insights["demonstrated"]


def test_wa_validator_run_direct_n8n_sends_webhook_token_and_reports_empty_body(
    monkeypatch,
):
    """Reproduces the live 2026-08-08 Aurora failure end to end, at the seam.

    Two bugs, both confirmed live: (1) the inline header construction built
    headers = {} whenever a token WAS configured, so X-Webhook-Token never
    reached n8n; (2) even with the correct token, n8n answered HTTP 200 with
    an empty body, and the old code's bare resp.json() turned that into an
    opaque JSONDecodeError. This drives run_session_direct's n8n_agents
    branch through a fake send_to_webhook and checks both are fixed: the
    real webhook token is threaded through as `secret`, and an empty body
    now raises a message that names the actual condition.
    """
    import asyncio as _asyncio

    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "test-token-123")
    monkeypatch.setenv("WA_VALIDATOR_DIRECT_WAIT", "1")

    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1", "slug": "aurora", "name": "Aurora"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona_routing",
        lambda _slug: {"process_mode": "n8n"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_workflow_bindings",
        lambda _persona_id: [
            {
                "active": True,
                "metadata": {
                    "decision_owner": "n8n_agents",
                    "conversation_webhook_url": "http://n8n:5678/webhook/aurora/conversation",
                },
            }
        ],
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "ensure_lead_for_persona",
        lambda **_kwargs: {"id": 999, "metadata": {}},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "update_lead", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {"channel_binding_id": "binding-1"},
    )
    captured_envelopes = []

    def fake_enqueue(**kwargs):
        captured_envelopes.append(kwargs)
        return {"buffer_id": "buf-1"}

    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "enqueue_whatsapp_envelope",
        fake_enqueue,
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "insert_event", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "get_messages", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_conversation_ledger",
        lambda *_a, **_k: None,
    )
    store = _install_fake_wa_validator_session_store(monkeypatch)

    captured_calls = []

    def fake_send_to_webhook(url, payload, **kwargs):
        captured_calls.append({"url": url, "payload": payload, "kwargs": kwargs})
        return 200, ""  # the exact failure mode confirmed live on the VPS

    monkeypatch.setattr(
        wa_validator_service.n8n_client, "send_to_webhook", fake_send_to_webhook
    )

    session_id = "session-n8n-empty-body"
    store[session_id] = {
        "id": session_id,
        "persona_slug": "aurora",
        "flow_id": "sdr_qualificacao_carro",
        "status": "ready",
        "script": {
            "meta": {"agent_slug": "aurora", "graph_version": 10, "graph_checksum": "abc"},
            "steps": [{"text": "Oi", "wait": 1}],
        },
        "output": None,
        "insights": None,
        "created_at": "2026-08-08T00:00:00+00:00",
        "updated_at": "2026-08-08T00:00:00+00:00",
    }

    _asyncio.run(wa_validator_service.run_session_direct(session_id))

    assert len(captured_calls) == 1
    assert captured_envelopes[0]["buffer"]["status"] == "waiting_human"
    assert captured_calls[0]["kwargs"]["secret"] == "test-token-123"
    # Confirmed live 2026-08-08: hardcoding "conversation_v1" here got every
    # step rejected by the workflow's own "pipeline contract mismatch"
    # guard, since real dispatch (and the binding's own declared contract)
    # uses "conversation_v3" for n8n_agents.
    assert captured_calls[0]["payload"]["pipeline_contract"] == "conversation_v3"

    session = wa_validator_service.get_session(session_id)
    bot_turn = next(
        turn for turn in session["output"]["conversation"] if turn["role"] == "bot"
    )
    assert bot_turn["error"] is True
    assert "empty body" in bot_turn["error_detail"]
    assert "empty body" in bot_turn["text"] or "erro" in bot_turn["text"].lower()


def test_wa_validator_direct_terminalizes_inert_inbound_only_after_v3_proof(
    monkeypatch,
):
    """Direct validation must never leave an inbound eligible for dispatch.

    The direct driver invokes n8n itself.  A ``buffered`` synthetic inbound
    can be claimed by the WhatsApp worker and remains visible to the next
    quiet-burst commit, which production exposed as ``burst_superseded``.
    Start inert and mark it terminal only after the v3 exactly-once audit.
    """
    import asyncio as _asyncio
    import json as _json

    monkeypatch.setenv("AI_BRAIN_WEBHOOK_TOKEN", "test-token-123")
    monkeypatch.setenv("WA_VALIDATOR_DIRECT_WAIT", "1")
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1", "slug": "aurora", "name": "Aurora"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona_routing",
        lambda _slug: {"process_mode": "n8n"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_workflow_bindings",
        lambda _persona_id: [{
            "active": True,
            "metadata": {
                "decision_owner": "n8n_agents",
                "pipeline_contract": "conversation_v3",
                "conversation_webhook_url": "http://n8n:5678/webhook/aurora/conversation",
            },
        }],
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "ensure_lead_for_persona",
        lambda **_kwargs: {"id": 999, "metadata": {}},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "update_lead", lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {"channel_binding_id": "binding-1"},
    )
    captured_envelopes = []

    def fake_enqueue(**kwargs):
        captured_envelopes.append(kwargs)
        return {"buffer_id": "buf-1"}

    monkeypatch.setattr(
        wa_validator_service.supabase_client, "enqueue_whatsapp_envelope", fake_enqueue,
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_whatsapp_buffer_by_idempotency",
        lambda _key: {},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_conversation_ledger",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "insert_event", lambda *_a, **_k: None,
    )
    terminalized = []
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "complete_whatsapp_buffer",
        lambda buffer_id, status, **_kwargs: terminalized.append((buffer_id, status)),
    )

    async def fake_wait_for_audit(*_args, **_kwargs):
        return {
            "inbound_count": 1,
            "decision_count": 1,
            "proof_count": 1,
            "valid_proof_count": 1,
            "outbound_count": 1,
            "outbound_released_after_proof": True,
            "commit_state": "completed",
            "prompt_tokens": 100,
            "model_calls": 1,
        }

    async def fake_wait_for_reply(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        wa_validator_service, "_wait_for_turn_audit_v3", fake_wait_for_audit,
    )
    monkeypatch.setattr(
        wa_validator_service, "_wait_for_reply_delivered", fake_wait_for_reply,
    )
    monkeypatch.setattr(
        wa_validator_service.n8n_client,
        "send_to_webhook",
        lambda *_a, **_k: (200, _json.dumps({
            "reply_text": "Oi!",
            "message_id": "out-1",
            "pipeline_contract": "conversation_v3",
        })),
    )
    store = _install_fake_wa_validator_session_store(monkeypatch)
    session_id = "session-n8n-inert-inbound"
    store[session_id] = {
        "id": session_id,
        "persona_slug": "aurora",
        "flow_id": "technical",
        "status": "ready",
        "script": {
            "meta": {"agent_slug": "aurora", "graph_version": 10, "graph_checksum": "abc"},
            "steps": [{"text": "Oi", "wait": 1}],
        },
        "output": None,
        "insights": None,
        "created_at": "2026-08-11T00:00:00+00:00",
        "updated_at": "2026-08-11T00:00:00+00:00",
    }

    _asyncio.run(wa_validator_service.run_session_direct(session_id))

    assert captured_envelopes[0]["buffer"]["status"] == "waiting_human"
    assert terminalized == [("buf-1", "sent")]
    assert wa_validator_service.get_session(session_id)["status"] == "done"


def _fake_graph(business_model: str):
    from types import SimpleNamespace

    persona_node = SimpleNamespace(
        node_type="persona", data={"business_model": business_model}
    )
    return SimpleNamespace(nodes=[persona_node])


def test_wa_validator_flows_excludes_commerce_flows_for_appointment_persona(
    monkeypatch,
):
    """Confirmed live 2026-08-08: the flow dropdown offered "compra_simples"

    for Aurora (business_model="appointment", no product nodes at all), and
    running it produced a looping, self-contradicting conversation -- not a
    pipeline bug, a nonsensical test. Flows must be scoped to what actually
    makes sense for the target persona's business model.
    """
    monkeypatch.setattr(
        wa_validator_service,
        "_published_graph",
        lambda _slug: (1, "checksum", _fake_graph("appointment")),
    )

    flow_ids = {f["id"] for f in wa_validator_service.flows("aurora")}

    assert "compra_simples" not in flow_ids
    assert "duvida_frete" not in flow_ids
    assert "sdr_qualificacao_carro" in flow_ids
    # Model-agnostic flows remain available for every persona.
    assert "atendente_humano" in flow_ids


def test_wa_validator_flows_unfiltered_without_persona_slug():
    all_ids = {f["id"] for f in wa_validator_service.flows()}
    assert "compra_simples" in all_ids
    assert "sdr_qualificacao_carro" in all_ids


def test_semantic_driver_can_defer_then_answer_field_spontaneously():
    driver = {
        "answers": {
            "nome_cliente": {"text": "Meu nome é Beatriz.", "value": "Beatriz"},
            "objective": {"text": "Quero conservar o carro.", "value": "conservar"},
        },
        "deferred_answer": {
            "field": "nome_cliente",
            "defer_text": "Prefiro não responder isso agora.",
            "later_text": "Ah, e meu nome é Beatriz.",
            "later_value": "Beatriz",
        },
    }
    state = {}

    deferred = wa_validator_service._next_semantic_driver_step(
        driver=driver,
        state=state,
        asked_field="nome_cliente",
        answered_fields=set(),
        active_anchor="paint",
        expected_active_branches=["paint"],
    )
    assert deferred["kind"] == "field_deferred"
    assert deferred["intended_facts"] == {}

    loose = wa_validator_service._next_semantic_driver_step(
        driver=driver,
        state=state,
        asked_field="objective",
        answered_fields=set(),
        active_anchor="paint",
        expected_active_branches=["paint"],
    )
    assert loose["kind"] == "loose_field_answer"
    assert loose["intended_facts"] == {"nome_cliente": "Beatriz"}

    next_answer = wa_validator_service._next_semantic_driver_step(
        driver=driver,
        state=state,
        asked_field="objective",
        answered_fields={"nome_cliente"},
        active_anchor="paint",
        expected_active_branches=["paint"],
    )
    assert next_answer["kind"] == "field_answer"
    assert next_answer["intended_facts"] == {"objective": "conservar"}


def test_wa_validator_generate_script_rejects_flow_incompatible_with_persona(
    monkeypatch,
):
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1", "slug": "aurora", "name": "Aurora"},
    )
    monkeypatch.setattr(
        wa_validator_service,
        "_build_graph_context",
        lambda _slug: ("", 1, "checksum", _fake_graph("appointment")),
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_active_graph_publication",
        lambda _persona_id: None,
    )

    with pytest.raises(ValueError, match="não é válido"):
        wa_validator_service.generate_script("aurora", "compra_simples", "Allan")


def test_wa_validator_run_direct_names_the_validation_lead_by_flow_and_graph_version(
    monkeypatch,
):
    """Validation leads must be identifiable at a glance in the leads list.

    Previously every validation lead was named "Validador [aurora]"
    regardless of which flow or graph version it ran against, so two
    sessions for the same persona were indistinguishable in the CRM. Name
    it "<flow_id> v<graph_version>" instead -- also makes a run against a
    since-republished graph version obvious from the name alone.
    """
    import asyncio as _asyncio

    monkeypatch.setenv("WA_VALIDATOR_DIRECT_WAIT", "1")
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona",
        lambda _slug: {"id": "persona-1", "slug": "aurora", "name": "Aurora"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_persona_routing",
        lambda _slug: {"process_mode": "internal"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_workflow_bindings",
        lambda _persona_id: [],
    )
    captured_lead_calls = []

    def fake_ensure_lead(**kwargs):
        captured_lead_calls.append(kwargs)
        return {"id": 999, "metadata": {}}

    monkeypatch.setattr(
        wa_validator_service.supabase_client, "ensure_lead_for_persona", fake_ensure_lead
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "update_lead", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "get_lead_by_ref",
        lambda _ref: {"channel_binding_id": "binding-1"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client,
        "enqueue_whatsapp_envelope",
        lambda **_kwargs: {"buffer_id": "buf-1"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "insert_event", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        wa_validator_service.conversation_runtime,
        "execute_pipeline",
        lambda **_kwargs: {"reply_text": "Oi!"},
    )
    monkeypatch.setattr(
        wa_validator_service.supabase_client, "get_messages", lambda *_a, **_k: []
    )
    store = _install_fake_wa_validator_session_store(monkeypatch)

    session_id = "session-naming"
    store[session_id] = {
        "id": session_id,
        "persona_slug": "aurora",
        "flow_id": "sdr_qualificacao_carro",
        "status": "ready",
        "script": {
            "meta": {"agent_slug": "aurora", "graph_version": 10, "graph_checksum": "abc"},
            "steps": [{"text": "Oi", "wait": 1}],
        },
        "output": None,
        "insights": None,
        "created_at": "2026-08-08T00:00:00+00:00",
        "updated_at": "2026-08-08T00:00:00+00:00",
    }

    _asyncio.run(wa_validator_service.run_session_direct(session_id))

    assert len(captured_lead_calls) == 1
    assert captured_lead_calls[0]["nome"] == "sdr_qualificacao_carro v10"


def test_wait_for_reply_delivered_returns_as_soon_as_a_new_message_lands(monkeypatch):
    """Regression test for the WA Validator message-batching gap (2026-08-08 report).

    Confirmed live: scripted steps advanced on a fixed sleep capped at 3s
    regardless of the real pipeline's latency, so several client messages
    could go out before the first reply landed -- concurrent turns for the
    same lead then raced graph_agent_runtime_v3's optimistic ledger lock,
    and every turn that lost the race silently produced no reply at all.
    """
    import asyncio as _asyncio

    call_count = {"n": 0}

    def fake_get_messages(_lead_ref, limit=200):
        call_count["n"] += 1
        # First two polls: no matching outbound. Third poll: the exact reply landed.
        return ([{
            "message_id": "ai:turn-1", "direction": "outbound", "content": "Resposta",
        }] if call_count["n"] >= 3 else [])

    monkeypatch.setattr(wa_validator_service.supabase_client, "get_messages", fake_get_messages)

    _asyncio.run(wa_validator_service._wait_for_reply_delivered(
        1, outbound_message_id="ai:turn-1", expected_reply="Resposta",
        max_wait_s=5.0, poll_interval_s=0.01,
    ))
    assert call_count["n"] == 3


def test_wait_for_reply_delivered_gives_up_after_max_wait(monkeypatch):
    import asyncio as _asyncio

    monkeypatch.setattr(
        wa_validator_service.supabase_client, "get_messages", lambda *_a, **_k: [{"id": 1}]
    )
    with pytest.raises(TimeoutError):
        _asyncio.run(wa_validator_service._wait_for_reply_delivered(
            1, outbound_message_id="ai:missing", expected_reply="Resposta",
            max_wait_s=0.05, poll_interval_s=0.01,
        ))

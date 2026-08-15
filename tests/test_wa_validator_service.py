from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import wa_validator_service as wv
from services import supabase_client


def test_wait_for_turn_audit_v3_tolerates_early_n8n_ack(monkeypatch):
    audits = iter([
        {
            "inbound_count": 1, "decision_count": 0, "proof_count": 0,
            "commit_state": None,
        },
        {
            "inbound_count": 1, "decision_count": 1, "proof_count": 1,
            "commit_state": "completed",
        },
    ])
    monkeypatch.setattr(
        wv.supabase_client, "audit_conversation_turn_v3", lambda _buffer_id: next(audits),
    )

    result = asyncio.run(wv._wait_for_turn_audit_v3(
        "buffer-1", max_wait_s=1, poll_interval_s=0,
    ))

    assert result["decision_count"] == 1
    assert result["proof_count"] == 1
    assert result["commit_state"] == "completed"


def test_customer_profile_is_resolved_from_the_packaged_api_tree():
    assert wv._CUSTOMER_PROFILES_PATH == API_ROOT / "evaluation" / "wa_validator_customer_profiles.json"
    assert wv._CUSTOMER_PROFILES_PATH.is_file()
    assert wv._customer_profile("appointment")["answers"]["nome_cliente"]["value"]


def test_bots_keeps_authorized_persona_when_graph_label_lookup_fails(monkeypatch):
    monkeypatch.setattr(wv.supabase_client, "get_personas", lambda: [
        {"id": "allowed-id", "slug": "allowed", "name": "Allowed"},
        {"id": "hidden-id", "slug": "hidden", "name": "Hidden"},
    ])
    monkeypatch.setattr(
        wv.graph_json_v2_store,
        "load_current",
        lambda _slug: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )

    result = wv.bots({"allowed-id"})

    assert [row["persona_slug"] for row in result] == ["allowed"]


def test_resolve_initial_state_defaults_to_cold_for_unrequested_or_unknown():
    assert wv._resolve_initial_state(None, "sdr_qualificacao_carro") == "cold"
    assert wv._resolve_initial_state("something_else", "sdr_qualificacao_carro") == "cold"


def test_resolve_initial_state_known_name_only_applies_to_name_collecting_flows():
    assert wv._resolve_initial_state("known_name", "sdr_qualificacao_carro") == "known_name"
    assert wv._resolve_initial_state("known_name", "sdr_troca_servico") == "known_name"
    # "duvida_frete" never collects a name -- nothing to pre-seed or omit,
    # so a request for known_name degrades to cold rather than silently
    # doing nothing while claiming a state that was never applied.
    assert wv._resolve_initial_state("known_name", "duvida_frete") == "cold"


def test_resolve_initial_state_random_only_ever_returns_the_two_valid_states():
    seen = {wv._resolve_initial_state("random", "sdr_qualificacao_carro") for _ in range(40)}
    assert seen == {"cold", "known_name"}
    # Same flow with no name-collection step: "random" must not fabricate a
    # "known_name" state it can't actually seed for.
    assert wv._resolve_initial_state("random", "duvida_frete") == "cold"


def _semantic_publication():
    return {
        "id": "publication-1", "version": 1, "checksum": "sha256:x",
        "document_json": _appointment_document(),
    }


def test_semantic_script_starts_with_one_graph_derived_turn():
    script = wv._semantic_appointment_script(
        publication=_semantic_publication(),
        flow_id="sdr_qualificacao_carro",
        initial_state="cold",
    )
    assert len(script["steps"]) == 1
    assert script["driver"]["mode"] == "semantic_graph_v1"
    assert script["driver"]["initial_known_fields"] == []
    assert script["steps"][0]["expected_branch_node_id"] == "branch:one"


def test_semantic_script_known_name_is_state_not_a_scripted_message():
    script = wv._semantic_appointment_script(
        publication=_semantic_publication(),
        flow_id="sdr_qualificacao_carro",
        initial_state="known_name",
    )
    assert script["driver"]["initial_known_fields"] == ["nome_cliente"]
    assert script["expected_dialogue"]["known_name"] == "Beatriz"
    assert all(
        "Beatriz" not in str(step.get("text") or "")
        for step in script["steps"]
    )


def test_semantic_script_uses_branch_as_service_existence_doubt_evidence():
    publication = _semantic_publication()
    publication["document_json"]["branch_contracts"]["branch:one"]["closure_node_ids"] = [
        "branch:one", "q:service", "q:name", "q:objective",
    ]

    script = wv._semantic_appointment_script(
        publication=publication,
        flow_id="sdr_qualificacao_carro",
        initial_state="cold",
    )
    assert script["driver"]["doubt"]["expected_evidence_node_ids"] == ["branch:one"]
    assert script["driver"]["expected_handoff"] is False


def test_published_service_existence_faq_accepts_faq_or_active_branch_evidence():
    publication = _semantic_publication()
    document = publication["document_json"]
    document["node_by_id"]["faq:service-exists"] = {
        "id": "faq:service-exists", "node_type": "faq", "title": "Vocês fazem Service One?",
        "data": {"question": "Vocês fazem Service One?"},
    }
    document["branch_contracts"]["branch:one"]["closure_node_ids"] = [
        "branch:one", "q:service", "q:name", "q:objective", "faq:service-exists",
    ]

    script = wv._semantic_appointment_script(
        publication=publication,
        flow_id="sdr_qualificacao_carro",
        initial_state="cold",
    )

    assert script["driver"]["doubt"]["expected_evidence_node_ids"] == [
        "faq:service-exists", "branch:one",
    ]


def test_schedule_faq_never_accepts_service_branch_as_schedule_evidence():
    publication = _semantic_publication()
    document = publication["document_json"]
    document["node_by_id"]["faq:schedule"] = {
        "id": "faq:schedule", "node_type": "faq", "title": "Vocês fazem Service One amanhã?",
        "data": {"question": "Vocês fazem Service One amanhã?"},
    }
    document["branch_contracts"]["branch:one"]["closure_node_ids"] = [
        "branch:one", "q:service", "q:name", "q:objective", "faq:schedule",
    ]

    script = wv._semantic_appointment_script(
        publication=publication,
        flow_id="sdr_qualificacao_carro",
        initial_state="cold",
    )

    assert script["driver"]["doubt"]["expected_evidence_node_ids"] == ["faq:schedule"]


def test_direct_run_is_queued_instead_of_executed_in_the_api(monkeypatch):
    monkeypatch.setattr(
        wv.supabase_client,
        "enqueue_wa_validator_session",
        lambda session_id, mode: {
            "queued": True,
            "state": "queued",
            "session": {"id": session_id, "status": "queued", "queue_mode": mode},
        },
    )

    result = wv.enqueue_session_direct("session-1")

    assert result == {
        "id": "session-1", "status": "queued", "queue_mode": "direct",
    }


def test_bootstrap_uses_active_publication_and_database_scopes_sessions(monkeypatch):
    calls = []
    monkeypatch.setattr(wv.supabase_client, "get_persona", lambda _slug: {
        "id": "persona-1", "slug": "generic", "name": "Generic",
    })
    monkeypatch.setattr(wv.supabase_client, "get_persona_routing", lambda _pid: {
        "process_mode": "n8n",
    })
    monkeypatch.setattr(wv.supabase_client, "get_workflow_bindings", lambda _pid: [{
        "active": True, "provider": "meta_cloud", "connection_status": "connected",
        "metadata": {"decision_owner": "n8n_agents"},
    }])
    monkeypatch.setattr(wv.supabase_client, "get_active_graph_publication", lambda _pid: {
        "version": 4,
        "checksum": "sha256:graph",
        "document_json": {"node_by_id": {"persona:generic": {
            "id": "persona:generic",
            "node_type": "persona",
            "title": "Generic Agent",
            "data": {
                "business_model": "appointment",
                "metadata": {"agent_slug": "generic-agent"},
            },
        }}},
    })
    monkeypatch.setattr(
        wv, "_published_graph",
        lambda _slug: (_ for _ in ()).throw(AssertionError("legacy graph must not load")),
    )

    def _sessions(**kwargs):
        calls.append(kwargs)
        return [{"id": "session-recent", "created_at": "2026-08-11T20:00:00Z"}]

    monkeypatch.setattr(wv, "list_sessions", _sessions)

    result = wv.bootstrap("generic")

    assert result["routing"]["conversation_mode"] == "n8n_agents"
    assert result["bot"]["agent_slug"] == "generic-agent"
    assert result["sessions"] == [{"id": "session-recent", "created_at": "2026-08-11T20:00:00Z"}]
    assert calls == [{"persona_slug": "generic", "since_hours": 12, "limit": 25}]


def test_bootstrap_falls_back_to_v2_when_no_active_publication(monkeypatch):
    graph = SimpleNamespace(nodes=[SimpleNamespace(
        node_type="persona",
        label="Legacy Agent",
        data={"business_model": "sales", "metadata": {"agent_slug": "legacy-agent"}},
    )])
    monkeypatch.setattr(wv.supabase_client, "get_persona", lambda _slug: {
        "id": "persona-legacy", "slug": "legacy", "name": "Legacy",
    })
    monkeypatch.setattr(
        wv.supabase_client, "get_persona_routing", lambda _slug: {"process_mode": "internal"},
    )
    monkeypatch.setattr(wv.supabase_client, "get_workflow_bindings", lambda _pid: [])
    monkeypatch.setattr(wv.supabase_client, "get_active_graph_publication", lambda _pid: None)
    monkeypatch.setattr(wv, "_published_graph", lambda _slug: (1, "sha256:legacy", graph))
    monkeypatch.setattr(wv, "list_sessions", lambda **_kwargs: [])

    result = wv.bootstrap("legacy")

    assert result["bot"]["bot_name"] == "Legacy Agent"
    assert result["bot"]["agent_slug"] == "legacy-agent"
    assert "compra_simples" in {flow["id"] for flow in result["flows"]}


def _persona_node(business_model: str):
    return SimpleNamespace(
        node_type="persona", data={"business_model": business_model},
    )


def _appointment_document():
    fields = [
        {
            "key": "servico", "owner_node_id": "branch:one", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:service",
        },
        {
            "key": "nome_cliente", "owner_node_id": "persona:one", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:name",
        },
        {
            "key": "objective", "owner_node_id": "branch:one", "required": True,
            "accepted_statuses": ["known"], "question_node_id": "q:objective",
        },
    ]
    questions = {
        "q:service": {"field_key": "servico", "text": "Qual serviço?"},
        "q:name": {"field_key": "nome_cliente", "text": "Qual seu nome?"},
        "q:objective": {"field_key": "objective", "text": "Qual seu objetivo?"},
    }
    return {
        "branch_anchors": ["branch:one"],
        "node_by_id": {
            "branch:one": {
                "id": "branch:one", "node_type": "product",
                "slug": "service-one", "title": "Service One", "data": {},
            },
            "faq:hours": {
                "id": "faq:hours", "node_type": "faq",
                "slug": "hours", "title": "Vocês atendem aos sábados?",
                "data": {"question": "Vocês atendem aos sábados?"},
            },
        },
        "branch_contracts": {
            "branch:one": {
                "fields": fields, "questions": questions,
                "closure_node_ids": ["branch:one", *questions, "faq:hours"],
            },
        },
    }


def test_generate_script_uses_the_v3_publication_version_when_one_is_active(monkeypatch):
    """Regression test for the false graph-lineage gap found live 2026-08-09.

    A persona actually running graph_agent_runtime_v3 (Aurora) reports the
    v3 compiler's own publication version/checksum on every real turn
    (graph_agent_runtime_v3.build_context() reads it from
    graph_publications, never from the legacy v2.1 store) -- a separate
    counter from the v2.1 store version _build_graph_context() returns.
    Before this fix, generate_script() baked the v2.1 version into
    expected_knowledge and the script label, so analyze_gaps() always
    compared two counters that could never match by design, reporting a
    false "high" severity gap and dragging overall_score down on a
    perfectly successful conversation. The v3 publication's own
    version/checksum, when one is active, is what a real turn actually
    reports, so it must be the "expected" baseline instead.
    """
    monkeypatch.setattr(wv.supabase_client, "get_persona", lambda slug: {"id": "persona-1", "name": "Aurora"})
    monkeypatch.setattr(
        wv, "_build_graph_context",
        lambda slug: ("kb context", 14, "sha256:legacy-v14", SimpleNamespace(nodes=[_persona_node("appointment")])),
    )
    monkeypatch.setattr(
        wv.supabase_client, "get_active_graph_publication",
        lambda persona_id: {
            "version": 40, "checksum": "sha256:real-v40",
            "document_json": _appointment_document(),
        },
    )
    monkeypatch.setattr(wv.supabase_client, "get_persona_routing", lambda slug: {})
    monkeypatch.setattr(wv.supabase_client, "get_workflow_bindings", lambda persona_id: [])
    monkeypatch.setattr(wv.supabase_client, "upsert_wa_validator_session", lambda *a, **k: None)
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *a, **k: None)

    result = wv.generate_script("aurora", "sdr_qualificacao_carro", "5511999999999")

    assert result["script"]["meta"]["graph_version"] == 40
    assert result["script"]["meta"]["graph_checksum"] == "sha256:real-v40"
    assert result["script"]["expected_knowledge"] == ["graph:40:sha256:real-v40"]
    assert result["script"]["driver"]["mode"] == "semantic_graph_v1"
    assert len(result["script"]["steps"]) == 1


def test_generate_script_falls_back_to_the_v2_store_version_without_a_v3_publication(monkeypatch):
    """No active v3 publication (e.g. a persona still fully on the legacy
    engine) -- behavior must stay exactly as before this fix."""
    monkeypatch.setattr(wv.supabase_client, "get_persona", lambda slug: {"id": "persona-1", "name": "Baita"})
    monkeypatch.setattr(
        wv, "_build_graph_context",
        lambda slug: ("kb context", 14, "sha256:legacy-v14", SimpleNamespace(nodes=[_persona_node("sales")])),
    )
    monkeypatch.setattr(wv.supabase_client, "get_active_graph_publication", lambda persona_id: None)
    monkeypatch.setattr(wv.supabase_client, "get_persona_routing", lambda slug: {})
    monkeypatch.setattr(wv.supabase_client, "get_workflow_bindings", lambda persona_id: [])
    monkeypatch.setattr(wv.supabase_client, "upsert_wa_validator_session", lambda *a, **k: None)
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *a, **k: None)

    result = wv.generate_script("baita-conveniencia", "duvida_frete", "5511999999999")

    assert result["script"]["meta"]["graph_version"] == 14
    assert result["script"]["meta"]["graph_checksum"] == "sha256:legacy-v14"
    assert result["script"]["expected_knowledge"] == ["graph:14:sha256:legacy-v14"]


def _semantic_audit_inputs():
    contract = _appointment_document()["branch_contracts"]["branch:one"]
    turn = {
        "text": "Entendi o seu objetivo. Qual seu nome?",
        "intent": "qualification",
        "route": "AI",
        "handoff": False,
        "evidence_node_ids": [],
    }
    proof_record = {
        "proof_result": {
            "accepted_facts": [{
                "field_key": "objective", "status": "known",
                "value": "proteger a pintura", "owner_node_id": "branch:one",
            }],
            "missing_fields": ["nome_cliente"],
            "next_question_node_id": "q:name",
            "qualification_complete": False,
            "handoff_requested": False,
            "fallback_used": False,
            "model_proposal_errors": [],
        },
        "final_decision": {"intent": "qualification", "evidence_node_ids": []},
    }
    ledger_after = {
        "revision": 2,
        "active_branch_node_id": "branch:one",
        "facts": {
            "servico": {
                "status": "known", "value": "service-one",
                "owner_node_id": "branch:one",
            },
            "objective": {
                "status": "known", "value": "proteger a pintura",
                "owner_node_id": "branch:one",
            },
        },
    }
    return {
        "customer_step": {
            "text": "Quero proteger a pintura.",
            "intended_facts": {"objective": "proteger a pintura"},
            "expected_branch_node_id": "branch:one",
        },
        "turn": turn,
        "proof_record": proof_record,
        "ledger_before": {"revision": 1, "facts": {}},
        "ledger_after": ledger_after,
        "contract": contract,
        "recent_replies": [],
        "previous_question_node_id": None,
        "expected_handoff": True,
    }


def test_semantic_turn_audit_accepts_acknowledgement_and_first_missing_question():
    audit = wv._semantic_turn_audit(**_semantic_audit_inputs())
    assert audit["passed"] is True
    assert audit["asked_field"] == "nome_cliente"


def test_semantic_turn_audit_rejects_a_later_field_before_first_missing():
    """The validator must enforce the same graph-owned order as proof."""
    inputs = _semantic_audit_inputs()
    inputs["customer_step"]["intended_facts"] = {}
    inputs["turn"]["text"] = "Perfeito! Qual seu objetivo com o carro?"
    inputs["proof_record"]["proof_result"]["missing_fields"] = ["nome_cliente", "objective"]
    inputs["proof_record"]["proof_result"]["next_question_node_id"] = "q:objective"
    inputs["proof_record"]["proof_result"]["accepted_facts"] = []
    inputs["ledger_after"]["facts"] = {
        "servico": {"status": "known", "value": "service-one", "owner_node_id": "branch:one"},
    }

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["passed"] is False
    assert audit["asked_field"] == "objective"
    assert "first_missing_field_only" in audit["failures"]


def test_semantic_turn_audit_rejects_a_question_for_a_field_that_is_not_missing():
    inputs = _semantic_audit_inputs()
    inputs["turn"]["text"] = "Perfeito! Qual seu objetivo com o carro?"
    inputs["proof_record"]["proof_result"]["next_question_node_id"] = "q:objective"
    # "objective" is not in missing_fields (still just ["nome_cliente"]) --
    # the question does not target a genuinely pending field.

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["passed"] is False
    assert "first_missing_field_only" in audit["failures"]


def test_semantic_turn_audit_rejects_repeated_reply_and_fallback():
    inputs = _semantic_audit_inputs()
    inputs["recent_replies"] = [inputs["turn"]["text"]]
    inputs["proof_record"]["proof_result"]["fallback_used"] = True
    audit = wv._semantic_turn_audit(**inputs)
    assert audit["passed"] is False
    assert "reply_not_repeated" in audit["failures"]
    assert "model_reconciled_without_fallback" in audit["failures"]


def test_semantic_turn_audit_allows_repeated_question_while_field_is_pending():
    inputs = _semantic_audit_inputs()
    inputs["recent_replies"] = [inputs["turn"]["text"]]
    inputs["previous_question_node_id"] = "q:name"

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["passed"] is True
    assert audit["criteria"]["reply_not_repeated"] is True


def test_semantic_turn_audit_accepts_published_completion_fallback():
    inputs = _semantic_audit_inputs()
    inputs["proof_record"]["proof_result"].update({
        "valid": True,
        "accepted_facts": [{
            "field_key": "nome_cliente", "status": "known",
            "value": "Beatriz", "owner_node_id": "persona:one",
        }],
        "missing_fields": [],
        "next_question_node_id": None,
        "qualification_complete": True,
        "fallback_used": True,
        "model_proposal_errors": ["question_after_completion"],
    })
    inputs["customer_step"] = {
        "text": "Beatriz",
        "intended_facts": {"nome_cliente": "Beatriz"},
        "expected_branch_node_id": "branch:one",
    }
    inputs["ledger_after"]["facts"]["nome_cliente"] = {
        "status": "known", "value": "Beatriz", "owner_node_id": "persona:one",
    }
    inputs["turn"]["text"] = "Perfeito, anotei tudo por aqui."
    inputs["expected_handoff"] = False

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["passed"] is True
    assert audit["qualification_complete"] is True
    assert audit["handoff_observed"] is False


def test_active_validator_contract_includes_pending_field_from_non_focus_branch():
    document = {
        "branch_contracts": {
            "branch:paint": {
                "fields": [{
                    "key": "vehicle_color",
                    "owner_node_id": "branch:paint",
                    "question_node_id": "q:color",
                }],
                "questions": {
                    "q:color": {
                        "field_key": "vehicle_color",
                        "text": "Qual e a cor do veiculo?",
                    },
                },
            },
            "branch:ppf": {
                "fields": [{
                    "key": "servico",
                    "owner_node_id": "branch:ppf",
                    "question_node_id": "q:service",
                }],
                "questions": {
                    "q:service": {
                        "field_key": "servico",
                        "text": "Qual servico?",
                    },
                },
            },
        },
    }

    contract = wv._active_validator_contract(
        document, ["branch:ppf", "branch:paint"],
    )

    assert {field["key"] for field in contract["fields"]} == {
        "servico", "vehicle_color",
    }
    assert contract["questions"]["q:color"]["field_key"] == "vehicle_color"


def test_semantic_turn_audit_rejects_question_for_a_persisted_fact():
    inputs = _semantic_audit_inputs()
    inputs["ledger_after"]["facts"]["nome_cliente"] = {
        "status": "known", "value": "Beatriz", "owner_node_id": "persona:one",
    }
    audit = wv._semantic_turn_audit(**inputs)
    assert audit["passed"] is False
    assert "known_fact_not_reasked" in audit["failures"]


def test_semantic_turn_audit_requires_doubt_answer_before_next_question():
    inputs = _semantic_audit_inputs()
    inputs["customer_step"] = {
        "text": "Vocês abrem no sábado?",
        "intended_facts": {},
        "expected_evidence_node_ids": ["faq:hours"],
        "expected_branch_node_id": "branch:one",
    }
    inputs["turn"]["evidence_node_ids"] = ["faq:hours"]
    inputs["turn"]["text"] = "Qual seu nome? Abrimos aos sábados."
    audit = wv._semantic_turn_audit(**inputs)
    assert audit["passed"] is False
    assert "doubt_answered_first" in audit["failures"]


def test_semantic_turn_audit_allows_pending_shared_question_after_service_switch():
    inputs = _semantic_audit_inputs()
    inputs["customer_step"] = {
        "text": "Na verdade, prefiro Service Two.",
        "kind": "branch_switch",
        "intended_facts": {"servico": "service-two"},
        "expected_branch_node_id": "branch:two",
        "expected_active_branch_node_ids": ["branch:two"],
    }
    inputs["previous_question_node_id"] = "q:name"
    inputs["turn"]["text"] = "Certo, Service Two. Qual seu nome?"
    inputs["proof_record"]["proof_result"]["accepted_facts"] = [{
        "field_key": "servico", "status": "known", "value": "service-two",
        "owner_node_id": "branch:two",
    }]
    inputs["ledger_after"].update({
        "active_branch_node_id": "branch:two",
        "active_branch_node_ids": ["branch:two"],
        "facts": {
            "servico": {
                "status": "known", "value": "service-two",
                "owner_node_id": "branch:two",
            },
        },
        "facts_by_key": {
            "servico": [{
                "status": "known", "value": "service-two",
                "owner_node_id": "branch:two",
            }],
        },
    })
    inputs["contract"]["fields"][0] = {
        **inputs["contract"]["fields"][0],
        "owner_node_id": "branch:two",
    }

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["criteria"]["question_advanced"] is True


def test_semantic_turn_audit_still_rejects_same_question_after_answering_its_field():
    inputs = _semantic_audit_inputs()
    inputs["previous_question_node_id"] = "q:name"
    inputs["customer_step"] = {
        "text": "Beatriz",
        "kind": "field_answer",
        "intended_facts": {"nome_cliente": "Beatriz"},
        "expected_branch_node_id": "branch:one",
    }
    inputs["turn"]["text"] = "Obrigada, Beatriz. Qual seu nome?"
    inputs["proof_record"]["proof_result"]["accepted_facts"] = [{
        "field_key": "nome_cliente", "status": "known", "value": "Beatriz",
        "owner_node_id": "persona:one",
    }]
    inputs["ledger_after"]["facts"]["nome_cliente"] = {
        "status": "known", "value": "Beatriz", "owner_node_id": "persona:one",
    }

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["criteria"]["question_advanced"] is False


def test_semantic_turn_audit_accepts_graph_proved_string_normalization():
    inputs = _semantic_audit_inputs()
    inputs["customer_step"] = {
        "text": "Os bancos estão manchados e a pintura perdeu o brilho",
        "kind": "field_answer",
        "intended_facts": {
            "objective": "Os bancos estão manchados e a pintura perdeu o brilho",
        },
        "expected_branch_node_id": "branch:one",
    }
    accepted = inputs["proof_record"]["proof_result"]["accepted_facts"][0]
    accepted.update({
        "value": "bancos manchados e pintura sem brilho",
        "evidence_span": "Os bancos estão manchados e a pintura perdeu o brilho",
    })
    inputs["ledger_after"]["facts"]["objective"].update({
        "value": "bancos manchados e pintura sem brilho",
    })

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["criteria"]["all_intended_facts_extracted"] is True


def test_validator_matches_canonical_boolean_strings_without_inverting_intent():
    assert wv._fact_matches_expected(
        {"status": "known", "value": "sim"}, True,
    ) is True
    assert wv._fact_matches_expected(
        {"status": "known", "value": "não"}, False,
    ) is True
    assert wv._fact_matches_expected(
        {"status": "known", "value": "sim"}, False,
    ) is False
    assert wv._fact_matches_expected(
        {"status": "known", "value": "talvez"}, True,
    ) is False


def test_semantic_turn_audit_allows_focus_change_inside_preserved_active_set():
    inputs = _semantic_audit_inputs()
    inputs["customer_step"]["expected_branch_node_id"] = "branch:two"
    inputs["customer_step"]["expected_active_branch_node_ids"] = [
        "branch:one", "branch:two",
    ]
    inputs["ledger_after"]["active_branch_node_id"] = "branch:one"
    inputs["ledger_after"]["active_branch_node_ids"] = ["branch:one", "branch:two"]

    audit = wv._semantic_turn_audit(**inputs)

    assert audit["criteria"]["expected_branch_persisted"] is True
    assert audit["criteria"]["expected_active_branches_persisted"] is True


def test_analyze_gaps_never_promotes_legacy_sequence_to_quality_evidence(monkeypatch):
    session = {
        "id": "legacy-session",
        "persona_slug": "generic",
        "script": {"expected_knowledge": ["graph:1:sha256:x"], "steps": [{"text": "one"}]},
        "output": {
            "conversation": [{
                "role": "bot", "text": "Visible reply",
                "graph_version": 1, "graph_checksum": "sha256:x",
            }],
        },
    }
    monkeypatch.setattr(wv, "get_session", lambda _session_id: session)
    monkeypatch.setattr(wv, "_session_update", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *_args, **_kwargs: None)

    result = wv.analyze_gaps("legacy-session")

    assert result["technical_score"] == 100
    assert result["overall_score"] == 0
    assert result["quality_pass"] is False
    assert result["quality_scope"] == "technical_only"


def test_analyze_gaps_scores_semantic_turn_criteria(monkeypatch):
    criteria = {
        "intent_identified": True,
        "doubt_answered_first": True,
        "all_intended_facts_extracted": True,
    }
    session = {
        "id": "semantic-session",
        "persona_slug": "generic",
        "script": {
            "driver": {"mode": "semantic_graph_v1"},
            "expected_knowledge": ["graph:1:sha256:x"],
        },
        "output": {
            "technical_pass": True,
            "quality_pass": True,
            "conversation": [{
                "role": "bot", "text": "Acknowledged.",
                "graph_version": 1, "graph_checksum": "sha256:x",
                "semantic_audit": {"criteria": criteria, "failures": [], "passed": True},
            }],
        },
    }
    monkeypatch.setattr(wv, "get_session", lambda _session_id: session)
    monkeypatch.setattr(wv, "_session_update", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *_args, **_kwargs: None)

    result = wv.analyze_gaps("semantic-session")

    assert result["quality_pass"] is True
    assert result["overall_score"] == 100
    assert result["analyzer"] == "semantic_graph_v1"


def test_analyze_gaps_never_scores_incomplete_semantic_run_as_accepted(monkeypatch):
    session = {
        "id": "failed-semantic-session",
        "persona_slug": "generic",
        "script": {
            "driver": {"mode": "semantic_graph_v1"},
            "expected_knowledge": [],
        },
        "output": {
            "technical_pass": False,
            "quality_pass": False,
            "conversation": [
                {
                    "role": "bot",
                    "text": "Pergunta válida",
                    "semantic_audit": {
                        "criteria": {"first_missing_only": True},
                        "failures": [],
                    },
                },
                {"role": "bot", "text": "(erro: proof inválido)", "error": True},
            ],
        },
    }
    monkeypatch.setattr(wv, "get_session", lambda _session_id: session)
    monkeypatch.setattr(wv, "_session_update", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *_args, **_kwargs: None)

    result = wv.analyze_gaps("failed-semantic-session")

    assert result["quality_pass"] is False
    assert result["technical_pass"] is False
    assert result["overall_score"] == 0
    assert result["conversational_quality_score"] < 100
    assert result["analyzer"] == "semantic_graph_v1"

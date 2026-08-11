from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import wa_validator_service as wv
from services import supabase_client


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


def test_semantic_script_requires_graph_owned_doubt_coverage():
    publication = _semantic_publication()
    publication["document_json"]["branch_contracts"]["branch:one"]["closure_node_ids"] = [
        "branch:one", "q:service", "q:name", "q:objective",
    ]

    try:
        wv._semantic_appointment_script(
            publication=publication,
            flow_id="sdr_qualificacao_carro",
            initial_state="cold",
        )
    except ValueError as exc:
        assert "FAQ publicada" in str(exc)
    else:
        raise AssertionError("semantic script accepted a branch without doubt coverage")


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


def test_semantic_turn_audit_rejects_repeated_reply_and_fallback():
    inputs = _semantic_audit_inputs()
    inputs["recent_replies"] = [inputs["turn"]["text"]]
    inputs["proof_record"]["proof_result"]["fallback_used"] = True
    audit = wv._semantic_turn_audit(**inputs)
    assert audit["passed"] is False
    assert "reply_not_repeated" in audit["failures"]
    assert "model_reconciled_without_fallback" in audit["failures"]


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

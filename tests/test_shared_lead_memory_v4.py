from __future__ import annotations

import json
from pathlib import Path

from schemas.conversation import (
    AgentResponse,
    BranchAction,
    ConversationContext,
    ConversationDecision,
    ConversationProposal,
    ConversationRoute,
    SharedLeadMemory,
    SharedMemoryFact,
)
from services import graph_agent_runtime_v3, shared_lead_memory


ROOT = Path(__file__).resolve().parents[1]


def test_shared_memory_keeps_complete_history_but_reuses_only_contract_profile() -> None:
    document = {
        "common_contract": {"fields": [
            {"key": "customer_name", "carry_over": True},
            {"key": "offering", "carry_over": True, "branch_selection_field": True},
        ]},
        "branch_contracts": {},
    }
    batch = {
        "journey": {"id": "journey-2", "sequence": 2, "state": "collecting"},
        "memory_facts": [
            {"field_key": "customer_name", "owner_node_id": "persona", "status": "known",
             "value_json": "Ana Lima", "journey_id": "journey-1", "is_current": True},
            {"field_key": "offering", "owner_node_id": "branch:old", "status": "known",
             "value_json": "old-service", "journey_id": "journey-1", "is_current": True},
            {"field_key": "visit_date", "owner_node_id": "branch:old", "status": "known",
             "value_json": "2026-08-01", "journey_id": "journey-1", "is_current": True},
        ],
        "journey_outcomes": [{"journey_id": "journey-1", "status": "completed"}],
    }
    memory = shared_lead_memory.project_shared_lead_memory(
        batch=batch,
        document=document,
        messages=[{"role": "user", "content": str(index)} for index in range(12)],
    )

    assert [fact.key for fact in memory.profile_facts] == ["customer_name"]
    policies = {fact.key: fact.reuse_policy for fact in memory.historical_facts}
    assert policies == {"offering": "branch_history_only", "visit_date": "historical_only"}
    assert memory.journey_outcomes[0]["status"] == "completed"
    assert len(memory.recent_messages) == 8


def test_terminal_interactions_do_not_open_a_journey_without_literal_new_demand() -> None:
    context = ConversationContext(
        persona_slug="p", agent_slug="sdr", graph_version=1,
        graph_checksum="sha256:x", messages=[{"role": "user", "content": "Obrigado"}],
        cart={}, rag_nodes=[], rag_paths=[], journey_id=None,
        post_completion_state={"has_terminal_journey": True},
    )
    courtesy = {"proposal": {"interaction_observation": {
        "kind": "courtesy_close", "evidence_span": "Obrigado", "confidence": 0.99,
    }}}
    new_demand = {"proposal": {"interaction_observation": {
        "kind": "new_demand", "evidence_span": "Obrigado", "confidence": 0.99,
    }}}

    assert graph_agent_runtime_v3._resolve_journey_action(
        context, graph_agent_runtime_v3._interaction_observation(context, courtesy)[0]
    ).value == "none"
    assert graph_agent_runtime_v3._resolve_journey_action(
        context, graph_agent_runtime_v3._interaction_observation(context, new_demand)[0]
    ).value == "open"


def test_terminal_candidate_opens_before_booking_but_routes_human_after_conversion() -> None:
    base = dict(
        persona_slug="p", agent_slug="sdr", graph_version=1,
        graph_checksum="sha256:x",
        messages=[{"role": "user", "content": "[audio do cliente]: chapiação"}],
        cart={}, rag_nodes=[], rag_paths=[], journey_id="journey-1",
        retrieval_trace={"service_resolution": {
            "status": "needs_confirmation",
            "candidate": {"branch_anchor_node_id": "branch:bodywork"},
        }},
    )
    before_booking = ConversationContext(
        **base,
        post_completion_state={
            "has_terminal_journey": True, "has_confirmed_conversion": False,
        },
    )
    after_booking = before_booking.model_copy(update={
        "post_completion_state": {
            "has_terminal_journey": True, "has_confirmed_conversion": True,
        },
    })

    assert graph_agent_runtime_v3._resolve_journey_action(
        before_booking, graph_agent_runtime_v3.InteractionKind.UNCLEAR,
    ).value == "open"
    assert graph_agent_runtime_v3._resolve_journey_action(
        after_booking, graph_agent_runtime_v3.InteractionKind.NEW_DEMAND,
    ).value == "none"
    assert graph_agent_runtime_v3._no_journey_route(
        after_booking, graph_agent_runtime_v3.InteractionKind.NEW_DEMAND,
    ) is ConversationRoute.HUMAN


def test_contract_probe_survives_terminal_journey_until_model_gate() -> None:
    context = ConversationContext(
        persona_slug="p", agent_slug="sdr", graph_version=1,
        graph_checksum="sha256:x", messages=[{"role": "user", "content": "novo pedido"}],
        cart={}, rag_nodes=[], rag_paths=[], journey_id="journey-1",
        post_completion_state={"has_terminal_journey": True},
    )
    decision = ConversationDecision(
        classifier="graph_contract_probe_v3", intent="await_model_proposal",
        route=ConversationRoute.SDR, confidence=1, lead_stage="engajado",
    )
    response = AgentResponse(
        reply_text=None, role=ConversationRoute.SDR, cart_state={},
        proof={"valid": True, "mode": "contract_probe"},
    )

    preserved_decision, preserved_response = graph_agent_runtime_v3._apply_journey_policy(
        context, decision, response, model_observation={"contract_probe": True},
    )

    assert preserved_decision.intent == "await_model_proposal"
    assert preserved_response.proof["mode"] == "contract_probe"
    assert "journey_action" not in preserved_response.proof


def test_confirmed_conversion_is_scoped_to_latest_journey() -> None:
    assert graph_agent_runtime_v3._journey_has_confirmed_conversion(
        {"id": "j2", "converted_at": None},
        [{"journey_id": "j1", "conversion_type": "appointment_booked", "status": "completed"}],
    ) is False
    assert graph_agent_runtime_v3._journey_has_confirmed_conversion(
        {"id": "j2", "converted_at": "2026-08-20T12:00:00Z"}, [],
    ) is True


def test_conversation_proposal_supports_explicit_absence_of_branch() -> None:
    proposal = ConversationProposal.model_validate({"branch_action": "none"})
    assert proposal.branch_action is BranchAction.NONE
    assert proposal.branch_anchor_node_id is None
    assert proposal.branch_path_checksum is None


def test_open_journey_seeds_every_profile_fact_with_origin() -> None:
    context = ConversationContext(
        persona_slug="p", agent_slug="sdr", graph_version=1,
        graph_checksum="sha256:x", messages=[{"role": "user", "content": "novo pedido", "message_id": "m"}],
        cart={}, rag_nodes=[], rag_paths=[], journey_id="old-journey",
        post_completion_state={"has_terminal_journey": True},
        shared_memory=SharedLeadMemory(profile_facts=[
            SharedMemoryFact(
                key="vehicle_model", value="Ka", owner_node_id="persona",
                status="known", journey_id="old-journey",
            ),
            SharedMemoryFact(
                key="vehicle_year", value="2018", owner_node_id="persona",
                status="known", journey_id="old-journey",
            ),
        ]),
    )
    decision = ConversationDecision(
        intent="new_demand", route=ConversationRoute.SDR, confidence=1,
        lead_stage="engajado",
    )
    response = AgentResponse(
        reply_text="Vamos começar.", role=ConversationRoute.SDR,
        cart_state={}, proof={"valid": True, "accepted_facts": []},
    )
    observation = {"proposal": {"interaction_observation": {
        "kind": "new_demand", "evidence_span": "novo pedido", "confidence": 1,
    }}}

    _decision, reconciled = graph_agent_runtime_v3._apply_journey_policy(
        context, decision, response, model_observation=observation,
    )

    assert reconciled.proof["journey_action"] == "open"
    facts = {fact["field_key"]: fact for fact in reconciled.proof["accepted_facts"]}
    assert set(facts) == {"vehicle_model", "vehicle_year"}
    assert facts["vehicle_model"]["metadata"]["origin_journey_id"] == "old-journey"


def test_generic_pending_fact_confirmation_has_no_field_name_handler(monkeypatch) -> None:
    document = {
        "branch_anchors": [], "node_by_id": {}, "coordinates": {},
        "branch_contracts": {},
        "common_contract": {
            "fields": [{
                "key": "fictional_field", "owner_node_id": "persona", "required": True,
                "accepted_statuses": ["known", "needs_confirmation", "invalid"],
                "question_node_id": "q:fictional",
            }],
            "questions": {"q:fictional": {"text": "Qual é o valor?", "field_key": "fictional_field"}},
        },
        "confirmation_templates": {"fact": "Entendi {candidate}. Está correto?"},
    }
    publication = {
        "id": "pub", "checksum": "sha256:x", "status": "active",
        "document_json": document,
    }
    monkeypatch.setattr(graph_agent_runtime_v3.supabase_client, "get_persona", lambda _slug: {"id": "p"})
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: publication,
    )
    pending = {
        "field_key": "fictional_field", "owner_node_id": "persona",
        "status": "needs_confirmation", "value": None,
        "metadata": {"confirmation": {
            "capability": "common_fact", "template_key": "fact",
            "candidate": "valor inventado", "field_key": "fictional_field",
            "owner_node_id": "persona",
        }},
    }
    context = ConversationContext(
        persona_slug="p", agent_slug="sdr", graph_version=1,
        graph_checksum="sha256:x", publication_id="pub",
        messages=[{"role": "user", "content": "sim", "message_id": "m2"}],
        cart={"facts": {"fictional_field": pending}, "facts_by_key": {"fictional_field": [pending]}},
        rag_nodes=[], rag_paths=[], journey_id="journey", graph_contract=document["common_contract"],
    )

    _decision, response = graph_agent_runtime_v3.decide(context, model_observation=None)

    fact = response.proof["accepted_facts"][0]
    assert fact["field_key"] == "fictional_field"
    assert fact["status"] == "known"
    assert fact["value"] == "valor inventado"
    assert response.proof["journey_action"] == "continue"


def test_v4_sql_and_template_keep_no_journey_exactly_once_contract() -> None:
    migration = (ROOT / "supabase" / "migrations" / "130_shared_lead_memory_and_journey_commit_v4.sql").read_text(encoding="utf-8")
    template = json.loads((ROOT / "api" / "n8n-workflows" / "persona-conversation-template.json").read_text(encoding="utf-8"))
    template_text = json.dumps(template, ensure_ascii=False)

    assert "graph_turn_context_batch_v4" in migration
    assert "commit_graph_turn_and_outbox_v4" in migration
    assert "journey_action=none" in migration
    assert "INSERT INTO public.conversation_turn_proofs" in migration
    assert "conversation_facts" not in migration.split("journey_action=none", 1)[1]
    assert "interaction_observation" in template_text
    assert "shared_memory" in template_text
    assert "slice(-8)" in template_text

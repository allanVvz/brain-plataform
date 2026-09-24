from __future__ import annotations

from schemas.conversation import ConversationContext
from services import agentic_turn, graph_agent_runtime_v3, shared_lead_memory


def _context() -> ConversationContext:
    return ConversationContext(
        persona_slug="fixture", agent_slug="agent", graph_version=1,
        graph_checksum="sha256:fixture", messages=[], cart={}, rag_nodes=[],
        rag_paths=[], graph_contract={"fields": [{
            "key": "profile", "owner_node_id": "audience:retail",
        }]},
    )


def test_completed_journey_product_interest_is_history_until_customer_resumes_it():
    document = {"common_contract": {"fields": []}, "branch_contracts": {}}
    old_interest = {
        "field_key": "commercial_interests", "owner_node_id": "persona:fixture",
        "journey_id": "finished", "status": "known", "is_current": True,
        "value_json": {"products": [{"product_node_id": "product:old", "intent": "select"}]},
    }
    new_journey = {"id": "new", "is_current": True}
    memory = shared_lead_memory.project_shared_lead_memory(
        batch={"journey": new_journey, "memory_facts": [old_interest]},
        document=document, messages=[],
    )
    assert memory.commercial_interests == []
    assert any(fact.key == "commercial_interests" for fact in memory.historical_facts)
    assert shared_lead_memory.historical_product_interests(memory) == [{
        "product_node_id": "product:old", "title": "", "journey_id": "finished",
        "memory_status": "historical_only",
    }]

    current_interest = {
        **old_interest, "journey_id": "new", "created_at": "2026-09-24T12:00:00Z",
        "value_json": {"products": [{"product_node_id": "product:current", "intent": "resume"}]},
    }
    memory = shared_lead_memory.project_shared_lead_memory(
        batch={"journey": new_journey, "memory_facts": [old_interest, current_interest]},
        document=document, messages=[],
    )
    assert memory.commercial_interests == [
        {"product_node_id": "product:current", "intent": "resume"}
    ]
    assert {fact.journey_id for fact in memory.historical_facts} == {"finished", "new"}
    assert [item["product_node_id"] for item in
            shared_lead_memory.historical_product_interests(memory)] == ["product:old"]


def test_latest_graph_reusable_profile_fact_wins_across_journeys():
    document = {"common_contract": {"fields": [{"key": "name", "carry_over": True}]}}
    rows = [
        {
            "field_key": "name", "owner_node_id": "persona:fixture",
            "journey_id": journey, "status": "known", "is_current": True,
            "value_json": name, "created_at": created,
        }
        for journey, name, created in (
            ("first", "Ana", "2026-01-01T00:00:00Z"),
            ("second", "Ana Souza", "2026-09-24T00:00:00Z"),
        )
    ]
    memory = shared_lead_memory.project_shared_lead_memory(
        batch={"journey": {"id": "third", "is_current": True}, "memory_facts": rows},
        document=document, messages=[],
    )
    assert [(fact.key, fact.value) for fact in memory.profile_facts] == [
        ("name", "Ana Souza")
    ]


def test_current_journey_fact_is_known_without_reconfirmation():
    facts = {
        "vehicle": [{"status": "known", "value": "Ford Ka", "source_message_id": "m1"}],
        "name": [{
            "status": "known", "value": "Ana Souza", "source_message_id": "m0",
            "metadata": {"reuse_policy": "carry_over"},
        }],
    }
    payload = graph_agent_runtime_v3._known_facts_payload(facts, "m2")
    by_key = {item["chave"]: item for item in payload}
    assert by_key["vehicle"]["origem"] == "esta_conversa"
    assert by_key["vehicle"]["carregado_do_pedido_anterior"] is False
    assert by_key["name"]["origem"] == "pedido_anterior"
    assert by_key["name"]["carregado_do_pedido_anterior"] is True


def test_invalid_optional_understanding_metadata_preserves_valid_fact():
    context = _context()
    raw = {
        "facts": [{
            "key": "profile", "value": "personal", "status": "known",
            "evidence_span": "uso proprio", "confidence": 1,
        }],
        "branch_selections": [{
            "action": "select", "branch_anchor_node_id": "branch:unknown",
            "evidence_span": "not in message",
        }],
        "customer_questions": [{
            "kind": "price", "topic": "price", "entity_node_ids": [],
            "evidence_span": "not in message",
        }],
        "audience_signals": [{
            "audience_node_id": "audience:unknown", "evidence_span": "not in message",
            "confidence": 1,
        }],
        "commercial_product_references": [{
            "product_node_id": "product:unpublished", "intent": "select",
            "quantity": 1, "evidence_span": "uso proprio",
        }],
    }
    understanding = agentic_turn._read_understanding(
        raw, context=context, message="uso proprio", message_id="m1",
    )
    assert [fact.field_key for fact in understanding.facts] == ["profile"]
    assert not understanding.branch_selections
    assert not understanding.customer_questions
    assert not understanding.commercial_product_references
    assert set(understanding.validation_observations) == {
        "understanding_metadata_discarded:branch_selection",
        "understanding_metadata_discarded:customer_question",
        "understanding_metadata_discarded:audience_signal",
        "understanding_metadata_discarded:commercial_product_reference",
    }

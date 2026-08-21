from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from schemas.graph_json_v2 import GraphJson
from services.graph_json_v2_validator import validate_graph_json
from scripts.publish_aurora_graph import build_graph as build_aurora_graph


def _valid_graph() -> GraphJson:
    return GraphJson.model_validate(
        {
            "schema_version": "2.0",
            "graph_id": "g1",
            "tenant": "qa",
            "persona_slug": "allanvvz",
            "brand_slug": "vz-lupas",
            "status": "draft",
            "nodes": [
                {"id": "n1", "node_type": "persona", "slug": "allanvvz", "label": "Allan"},
                {"id": "n2", "node_type": "brand", "slug": "vz-lupas", "label": "VZ", "parent_id": "n1"},
                {"id": "n3", "node_type": "briefing", "slug": "brief", "label": "Brief", "parent_id": "n2"},
                {"id": "n4", "node_type": "campaign", "slug": "camp", "label": "Camp", "parent_id": "n3"},
                {"id": "n5", "node_type": "audience", "slug": "aud", "label": "Aud", "parent_id": "n4"},
                {"id": "n6", "node_type": "product_group", "slug": "grp", "label": "Group", "parent_id": "n5"},
                {"id": "n7", "node_type": "product", "slug": "prod", "label": "Prod", "parent_id": "n6"},
                {"id": "n8", "node_type": "copy", "slug": "copy", "label": "Copy", "parent_id": "n7"},
                {
                    "id": "n9",
                    "node_type": "faq",
                    "slug": "faq",
                    "label": "FAQ",
                    "parent_id": "n8",
                    "data": {
                        "markdown_document": True,
                        "markdown": "### 1. Pergunta?\nResposta: Sim.",
                        "question_count": 1,
                        "validation_status": "pending_validation",
                        "branch_path": ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8", "n9"],
                        "source_node_id": "n8",
                        "source_node_type": "copy",
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "relation": "main"},
                {"id": "e2", "source": "n2", "target": "n3", "relation": "main"},
                {"id": "e3", "source": "n3", "target": "n4", "relation": "main"},
                {"id": "e4", "source": "n4", "target": "n5", "relation": "main"},
                {"id": "e5", "source": "n5", "target": "n6", "relation": "main"},
                {"id": "e6", "source": "n6", "target": "n7", "relation": "main"},
                {"id": "e7", "source": "n7", "target": "n8", "relation": "main"},
                {"id": "e8", "source": "n8", "target": "n9", "relation": "main"},
            ],
        }
    )


def test_validate_graph_json_accepts_valid_graph():
    graph = _valid_graph()
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is True
    assert errors == []


def test_validate_graph_json_rejects_incomplete_graph_owned_conversation_policy():
    payload = _valid_graph().model_dump()
    payload["nodes"][0]["data"] = {
        "business_model": "appointment",
        "appointment_policy": {
            "required_fields": ["name"],
            "field_questions": {"name": "What is your name?"},
            "field_labels": {},
        },
        "conversation_policy": {
            "intents": {"greeting": {"responses": ["Hello"], "always_acknowledge": True}},
            "qualification": {
                "summary_template": "Summary: {informed_fields}",
                "confirmation_question": "Is this correct?",
                "correction_prompt": "What should be corrected?",
                "completion_message": "Thank you.",
                "incomplete_handoff_template": "",
            },
            "direct_booking": {
                "intent_aliases": [],
                "no_data_instruction": "",
                "known_data_confirmation": "Known: {informed_fields}",
                "confirmed_acknowledgement": "Thank you.",
                "silent_handoff": False,
            },
            "question_repetition": {"max_attempts": 2},
        },
    }
    graph = GraphJson.model_validate(payload)

    valid, errors = validate_graph_json(graph)

    assert valid is False
    assert "appointment_policy.field_labels missing non-empty label for required field name" in errors
    assert "conversation_policy.qualification.incomplete_handoff_template must be non-empty" in errors
    assert "conversation_policy.direct_booking.intent_aliases must be non-empty" in errors
    assert "conversation_policy.direct_booking.silent_handoff must be true" in errors
    assert "conversation_policy.question_repetition.max_attempts must be 0 or 1" in errors
    assert "appointment persona requires conversation_policy.doubt_handling" in errors


def test_question_repetition_accepts_zero_contextual_retries():
    graph = build_aurora_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    persona.data["conversation_policy"]["question_repetition"]["max_attempts"] = 0

    valid, errors = validate_graph_json(graph)

    assert valid is True, errors


def test_service_clarification_policy_requires_every_runtime_text():
    graph = build_aurora_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    persona.data["conversation_policy"]["service_clarification"]["retry_question"] = ""

    valid, errors = validate_graph_json(graph)

    assert valid is False
    assert (
        "conversation_policy.service_clarification.retry_question must be non-empty"
        in errors
    )


def test_appointment_identity_field_must_be_first_required_field():
    graph = build_aurora_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = persona.data["appointment_policy"]
    policy["required_fields"] = [
        "servico",
        "nome_cliente",
        *policy["required_fields"][2:],
    ]

    valid, errors = validate_graph_json(graph)

    assert valid is False
    assert "appointment_policy.identity_field must equal required_fields[0]" in errors


def test_appointment_publication_requires_self_authorized_factual_faq_claim():
    graph = build_aurora_graph()
    faq = next(node for node in graph.nodes if node.id == "aurora-faq-wash-includes")
    faq.data = {**faq.data, "claims": []}

    valid, errors = validate_graph_json(graph)

    assert valid is False
    assert "approved factual FAQ aurora-faq-wash-includes must declare claims" in errors


def test_appointment_publication_rejects_faq_evidence_from_another_branch():
    graph = build_aurora_graph()
    faq = next(node for node in graph.nodes if node.id == "aurora-faq-wash-includes")
    faq.data = {**faq.data, "claims": [{
        "claim_type": "service_detail",
        "policy": {"mode": "informational"},
        "evidence_node_ids": ["aurora-faq-polish-includes"],
    }]}

    valid, errors = validate_graph_json(graph)

    assert valid is False
    assert (
        "approved factual FAQ aurora-faq-wash-includes claim service_detail must cite only itself"
        in errors
    )


def test_qualification_faq_does_not_require_an_answer_claim():
    graph = build_aurora_graph()
    qualification_ids = next(
        node for node in graph.nodes if node.node_type == "persona"
    ).data["appointment_policy"]["field_question_node_ids"]
    qualification_faq = next(
        node for node in graph.nodes if node.id == qualification_ids["nome_cliente"]
    )
    assert not (qualification_faq.data or {}).get("claims")

    valid, errors = validate_graph_json(graph)

    assert valid is True, errors


def test_validate_graph_json_accepts_product_group_faq_when_product_absent():
    payload = _valid_graph().model_dump()
    payload["nodes"] = [node for node in payload["nodes"] if node["id"] not in {"n7", "n8"}]
    for node in payload["nodes"]:
        if node["id"] == "n9":
            node["parent_id"] = "n6"
            node["data"]["branch_path"] = ["n1", "n2", "n3", "n4", "n5", "n6", "n9"]
            node["data"]["source_node_id"] = "n6"
            node["data"]["source_node_type"] = "product_group"
            break
    payload["edges"] = [
        {"id": "e1", "source": "n1", "target": "n2", "relation": "main"},
        {"id": "e2", "source": "n2", "target": "n3", "relation": "main"},
        {"id": "e3", "source": "n3", "target": "n4", "relation": "main"},
        {"id": "e4", "source": "n4", "target": "n5", "relation": "main"},
        {"id": "e5", "source": "n5", "target": "n6", "relation": "main"},
        {"id": "e6", "source": "n6", "target": "n9", "relation": "main"},
    ]
    graph = GraphJson.model_validate(payload)
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is True
    assert errors == []


def test_validate_graph_json_accepts_campaign_briefing_before_audience():
    graph = _valid_graph()
    # Current business rule allows Campaign -> Briefing -> Audience.
    for node in graph.nodes:
        if node.id == "n3":
            node.parent_id = "n4"
        if node.id == "n4":
            node.parent_id = "n2"
        if node.id == "n5":
            node.parent_id = "n3"
    graph.edges[1].source = "n2"
    graph.edges[1].target = "n4"
    graph.edges[2].source = "n4"
    graph.edges[2].target = "n3"
    graph.edges[3].source = "n3"
    graph.edges[3].target = "n5"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is True
    assert errors == []


def test_validate_graph_json_rejects_schema_version_mismatch():
    graph = _valid_graph()
    graph.schema_version = "1.0"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("schema_version must be 2.0" in err for err in errors)


def test_validate_graph_json_rejects_persona_ownership_mismatch():
    graph = _valid_graph()
    graph.persona_slug = "other-persona"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("persona ownership mismatch" in err for err in errors)


def test_validate_graph_json_accepts_product_directly_under_audience():
    graph = _valid_graph()
    # Product Group is optional; product may hang directly from audience.
    for node in graph.nodes:
        if node.id == "n7":
            node.parent_id = "n5"
            break
    graph.edges[5].source = "n5"
    graph.edges[5].target = "n7"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is True
    assert errors == []


def test_validate_graph_json_rejects_product_directly_under_campaign():
    graph = _valid_graph()
    for node in graph.nodes:
        if node.id == "n7":
            node.parent_id = "n4"
            break
    graph.edges[5].source = "n4"
    graph.edges[5].target = "n7"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("expected one of" in err for err in errors)


def test_validate_graph_json_rejects_orphan_node():
    graph = _valid_graph()
    for node in graph.nodes:
        if node.id == "n7":
            node.parent_id = None
            break
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("orphan node" in err for err in errors)


def test_validate_graph_json_rejects_missing_edge_integrity():
    graph = _valid_graph()
    graph.edges[0].target = "missing-node"
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("target missing-node missing" in err for err in errors)


def test_validate_graph_json_rejects_faq_before_embed_violation():
    graph = _valid_graph()
    graph.nodes.append(
        type(graph.nodes[0]).model_validate(
            {"id": "n10", "node_type": "embedded", "slug": "emb", "label": "Emb", "parent_id": "n7"}
        )
    )
    graph.edges.append(type(graph.edges[0]).model_validate({"id": "e9", "source": "n7", "target": "n10", "relation": "main"}))
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("expected one of" in err for err in errors)


def test_validate_graph_json_rejects_pending_faq_to_embedded():
    graph = _valid_graph()
    graph.nodes.append(
        type(graph.nodes[0]).model_validate(
            {"id": "n10", "node_type": "embedded", "slug": "emb", "label": "Emb", "parent_id": "n9"}
        )
    )
    graph.edges.append(type(graph.edges[0]).model_validate({"id": "e9", "source": "n9", "target": "n10", "relation": "main"}))
    is_valid, errors = validate_graph_json(graph)
    assert is_valid is False
    assert any("pending FAQ cannot connect to embedded" in err for err in errors)

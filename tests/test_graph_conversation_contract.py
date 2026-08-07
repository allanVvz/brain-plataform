from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.publish_aurora_graph import build_graph
from schemas.conversation import ConversationContext, ConversationRoute
from services import context_cards, conversation_runtime
from services import graph_conversation_contract as contract_service


def _graph():
    graph = build_graph()
    graph.graph_version = 7
    return graph


def _context(graph, *, branch_id: str, message: str, cart: dict | None = None, card_ids=None):
    contract = contract_service.compile_branch_contract(graph, branch_id)
    closure = contract_service.branch_closure(graph, branch_id)
    selected_ids = list(card_ids if card_ids is not None else closure)
    cards = context_cards.cards_for_ids(
        graph=graph,
        graph_version=7,
        graph_checksum="aurora-proof-checksum",
        ids=selected_ids,
    )
    return ConversationContext(
        persona_slug="aurora",
        agent_slug="aurora",
        graph_version=7,
        graph_checksum="aurora-proof-checksum",
        messages=[{"role": "user", "sender_type": "lead", "texto": message, "message_id": "712"}],
        cart={"_lead_stage": "novo", **(cart or {})},
        rag_nodes=[{
            "id": node.id,
            "node_type": node.node_type,
            "slug": node.slug,
            "title": node.label,
            "status": (node.data or {}).get("status"),
            "source": (node.data or {}).get("source"),
            "data": node.data or {},
        } for node in graph.nodes if node.id in closure],
        rag_paths=[contract_service.coordinate_for_node(graph, node_id)["path_node_ids"] for node_id in selected_ids],
        context_cards=cards,
        active_branch_node_id=branch_id,
        active_path_checksum=contract["branch_path_checksum"],
        branch_node_ids=sorted(closure),
        graph_contract=contract,
    )


def test_publication_materializes_graph_owned_qualification_faqs():
    graph = _graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = persona.data["appointment_policy"]

    assert set(policy["field_question_node_ids"]) == set(policy["field_questions"])
    for field, node_id in policy["field_question_node_ids"].items():
        node = next(item for item in graph.nodes if item.id == node_id)
        assert node.node_type == "faq"
        assert node.data["metadata"]["role"] == "qualification_question"
        assert node.data["metadata"]["field_key"] == field
        assert node.data["question"] == policy["field_questions"][field]


def test_coordinate_is_derived_from_real_hierarchy_edges():
    graph = _graph()
    coordinate = contract_service.coordinate_for_node(
        graph, "aurora-faq-interior-includes", graph_version=7
    )

    assert coordinate["path_node_ids"][0] == "aurora-persona"
    assert coordinate["path_node_ids"][-1] == "aurora-faq-interior-includes"
    assert coordinate["branch_anchor_node_id"] == "aurora-product-interior"
    assert len(coordinate["path_edge_ids"]) == len(coordinate["path_node_ids"]) - 1
    assert coordinate["graph_version"] == 7
    assert coordinate["path_checksum"].startswith("sha256:")


def test_short_answers_keep_branch_and_explicit_intent_switches_it():
    graph = _graph()
    first = contract_service.resolve_branch_anchor(
        graph, "Quero fazer higienização interna"
    )
    short = contract_service.resolve_branch_anchor(
        graph, "2020", previous_anchor_node_id=first["branch_anchor_node_id"]
    )
    switched = contract_service.resolve_branch_anchor(
        graph,
        "Agora quero polimento técnico",
        previous_anchor_node_id=first["branch_anchor_node_id"],
    )

    assert first["branch_anchor_node_id"] == "aurora-product-interior"
    assert short["branch_anchor_node_id"] == "aurora-product-interior"
    assert short["explicit_intent"] is False
    assert switched["branch_anchor_node_id"] == "aurora-product-polish"
    assert switched["branch_changed"] is True


def test_branch_closure_excludes_historical_sibling_products():
    graph = _graph()
    closure = contract_service.branch_closure(graph, "aurora-product-interior")

    assert "aurora-product-interior" in closure
    assert "aurora-faq-interior-includes" in closure
    assert "aurora-product-polish" not in closure
    assert "aurora-faq-polish-includes" not in closure


def test_proof_checker_keeps_unknown_unresolved_when_graph_disallows_it():
    graph = _graph()
    branch_id = "aurora-product-interior"
    contract = contract_service.compile_branch_contract(graph, branch_id)
    ledger = contract_service.ledger_from_state({}, contract)
    year = next(field for field in contract["fields"] if field["key"] == "vehicle_year")
    proposal = {
        "branch_anchor_node_id": branch_id,
        "branch_path_checksum": contract["branch_path_checksum"],
        "extracted_facts": [{
            "field_key": "vehicle_year",
            "value": None,
            "status": "unknown",
            "source_message_id": "712",
            "owner_node_id": year["owner_node_id"],
        }],
        "next_question_node_id": contract["fields"][0]["question_node_id"],
        "cited_node_ids": [branch_id, contract["fields"][0]["question_node_id"]],
        "reply": contract["fields"][0]["question"],
        "qualification_complete": False,
        "handoff_requested": False,
    }
    package = contract_service.branch_closure(graph, branch_id)
    proof = contract_service.check_proposal(
        graph=graph,
        contract=contract,
        ledger=ledger,
        proposal=proposal,
        package_node_ids=package,
    )

    assert proof["valid"] is True
    assert proof["ledger"]["facts"]["vehicle_year"]["status"] == "unknown"
    assert "vehicle_year" in proof["missing_fields"]


def test_out_of_package_branch_evidence_requests_repair_not_handoff():
    graph = _graph()
    branch_id = "aurora-product-interior"
    contract = contract_service.compile_branch_contract(graph, branch_id)
    ledger = contract_service.ledger_from_state({}, contract)
    first = contract["fields"][0]
    proposal = {
        "branch_anchor_node_id": branch_id,
        "branch_path_checksum": contract["branch_path_checksum"],
        "extracted_facts": [],
        "next_question_node_id": first["question_node_id"],
        "cited_node_ids": [branch_id, first["question_node_id"]],
        "reply": first["question"],
        "qualification_complete": False,
        "handoff_requested": False,
    }
    proof = contract_service.check_proposal(
        graph=graph,
        contract=contract,
        ledger=ledger,
        proposal=proposal,
        package_node_ids={branch_id},
    )

    assert proof["valid"] is False
    assert proof["repair_required"] is True
    assert proof["repair_node_ids"] == [first["question_node_id"]]


def test_runtime_commits_semantic_fact_status_without_treating_unknown_as_value(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(
        conversation_runtime,
        "_current_graph",
        lambda _slug: (7, "aurora-proof-checksum", graph),
    )
    branch_id = "aurora-product-interior"
    context = _context(graph, branch_id=branch_id, message="Não sei informar o ano agora")
    contract = context.graph_contract
    year = next(field for field in contract["fields"] if field["key"] == "vehicle_year")
    first = contract["fields"][0]
    proposal = {
        "branch_anchor_node_id": branch_id,
        "branch_path_checksum": contract["branch_path_checksum"],
        "extracted_facts": [{
            "field_key": "vehicle_year",
            "value": None,
            "status": "unknown",
            "source_message_id": "712",
            "owner_node_id": year["owner_node_id"],
        }],
        "next_question_node_id": first["question_node_id"],
        "cited_node_ids": [branch_id, first["question_node_id"]],
        "reply": first["question"],
        "qualification_complete": False,
        "handoff_requested": False,
    }

    decision, response = conversation_runtime.decide(
        context,
        model_observation={"proposal": proposal},
    )

    assert decision.classifier == "graph_proof_checker_v1"
    assert decision.route == ConversationRoute.SDR
    assert response.proof["valid"] is True
    assert response.cart_state["facts"]["vehicle_year"]["status"] == "unknown"
    assert response.cart_state["facts"]["vehicle_year"]["value"] is None
    assert "vehicle_year" not in response.cart_state["appointment_request"]
    assert "vehicle_year" in response.cart_state["missing_fields"]


def test_n8n_initial_policy_compiles_contract_without_running_commercial_state_machine(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(
        conversation_runtime,
        "_current_graph",
        lambda _slug: (7, "aurora-proof-checksum", graph),
    )
    monkeypatch.setattr(
        conversation_runtime.DeterministicAppointment,
        "handle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("contract probe must not run the legacy state machine")
        ),
    )
    context = _context(
        graph,
        branch_id="aurora-product-interior",
        message="Quero fazer higienização interna",
    )

    decision, response = conversation_runtime.decide(
        context,
        model_observation={"contract_probe": True},
    )

    assert decision.intent == "await_model_proposal"
    assert decision.classifier == "graph_contract_probe_v1"
    assert response.reply_text is None
    assert response.proof["mode"] == "contract_probe"
    assert response.cart_state["missing_fields"] == context.graph_contract["required_fields"]


def test_runtime_repairs_grounding_once_then_uses_published_question(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(
        conversation_runtime,
        "_current_graph",
        lambda _slug: (7, "aurora-proof-checksum", graph),
    )
    branch_id = "aurora-product-interior"
    full_contract = contract_service.compile_branch_contract(graph, branch_id)
    first = full_contract["fields"][0]
    context = _context(
        graph,
        branch_id=branch_id,
        message="Oi",
        card_ids=[branch_id],
    )
    proposal = {
        "branch_anchor_node_id": branch_id,
        "branch_path_checksum": full_contract["branch_path_checksum"],
        "extracted_facts": [],
        "next_question_node_id": first["question_node_id"],
        "cited_node_ids": [branch_id, first["question_node_id"]],
        "reply": first["question"],
        "qualification_complete": False,
        "handoff_requested": False,
    }

    first_decision, first_response = conversation_runtime.decide(
        context,
        model_observation={"proposal": proposal, "repair_attempt": 0},
    )
    assert first_decision.intent == "repair_retrieval"
    assert first_response.handoff_required is False
    assert first_response.proof["repair_required"] is True
    assert [card["id"] for card in first_response.repair_context_cards] == [first["question_node_id"]]

    broken = {**proposal, "reply": "Uma pergunta inventada"}
    second_decision, second_response = conversation_runtime.decide(
        context,
        model_observation={
            "proposal": broken,
            "repair_attempt": 1,
            "repair_context_node_ids": [first["question_node_id"]],
        },
    )
    assert second_decision.intent == "technical_proof_fallback"
    assert second_response.handoff_required is False
    assert second_response.reply_text == first["question"]
    assert second_response.proof["fallback_used"] is True


def test_explicit_branch_switch_drops_incompatible_historical_facts(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(
        conversation_runtime,
        "_current_graph",
        lambda _slug: (7, "aurora-proof-checksum", graph),
    )
    old_contract = contract_service.compile_branch_contract(graph, "aurora-product-polish")
    old_color = next(field for field in old_contract["fields"] if field["key"] == "vehicle_color")
    state = {
        "active_branch_node_id": "aurora-product-polish",
        "active_path_checksum": old_contract["branch_path_checksum"],
        "facts": {
            "vehicle_color": {
                "status": "known",
                "value": "preto",
                "source_message_id": "old",
                "owner_node_id": old_color["owner_node_id"],
            }
        },
    }
    branch_id = "aurora-product-interior"
    context = _context(
        graph,
        branch_id=branch_id,
        message="Agora quero higienização interna",
        cart=state,
    )
    contract = context.graph_contract
    first = contract["fields"][0]
    proposal = {
        "branch_anchor_node_id": branch_id,
        "branch_path_checksum": contract["branch_path_checksum"],
        "extracted_facts": [],
        "next_question_node_id": first["question_node_id"],
        "cited_node_ids": [branch_id, first["question_node_id"]],
        "reply": first["question"],
        "qualification_complete": False,
        "handoff_requested": False,
    }
    _, response = conversation_runtime.decide(
        context,
        model_observation={"proposal": proposal},
    )

    assert response.proof["valid"] is True
    assert response.cart_state["active_branch_node_id"] == branch_id
    assert "vehicle_color" not in response.cart_state["facts"]


def _price_proposal(graph, branch_id: str, reply: str, *, cited=None):
    contract = contract_service.compile_branch_contract(graph, branch_id)
    ledger = contract_service.ledger_from_state({}, contract)
    first = contract["fields"][0]
    proposal = {
        "branch_anchor_node_id": branch_id,
        "branch_path_checksum": contract["branch_path_checksum"],
        "extracted_facts": [],
        "next_question_node_id": first["question_node_id"],
        "cited_node_ids": [branch_id, first["question_node_id"], *(cited or [])],
        "reply": f"{reply} {first['question']}",
        "qualification_complete": False,
        "handoff_requested": False,
    }
    package = contract_service.branch_closure(graph, branch_id)
    return contract_service.check_proposal(
        graph=graph,
        contract=contract,
        ledger=ledger,
        proposal=proposal,
        package_node_ids=package,
    )


def test_check_proposal_rejects_any_price_shape_when_disclosure_is_human_only():
    graph = _graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    assert persona.data["appointment_policy"]["price_disclosure"] == "human_only"
    for reply in (
        "Fica em R$ 650.",
        "Custa 897.",
        "Fica em torno de 1.197.",
        "A partir de 350.",
        "São 650 reais.",
    ):
        proof = _price_proposal(graph, "aurora-product-polish", reply)
        assert proof["valid"] is False, reply
        assert "price_disclosure_requires_human" in proof["errors"], reply


def test_check_proposal_allows_the_published_payment_policy_figures():
    graph = _graph()
    payment_rule = next(
        node for node in graph.nodes
        if any(
            str((claim or {}).get("claim_type")) == "payment_policy"
            for claim in (node.data or {}).get("claims") or []
        )
    )
    reply = (
        "Aceitamos Pix, dinheiro e cartão — até 4x sem juros ou até 10x com "
        "acréscimo. Para serviços acima de R$ 2.000,00 é necessário um sinal "
        "de 10% do valor para reservar a agenda."
    )
    with_claim = _price_proposal(
        graph, "aurora-product-polish", reply, cited=[payment_rule.id]
    )
    assert "price_disclosure_requires_human" not in with_claim["errors"]
    assert with_claim["valid"] is True

    # Same sentence, no cited node authorizing payment terms: rejected.
    without_claim = _price_proposal(graph, "aurora-product-polish", reply)
    assert "price_disclosure_requires_human" in without_claim["errors"]


def test_check_proposal_does_not_flag_durations_or_notice_periods():
    graph = _graph()
    for reply in (
        "Reagendamentos precisam de 48 horas de antecedência.",
        "A higienização leva cerca de 3 horas.",
        "Atendemos até 5 clientes por dia.",
        "Seu carro é de 2020, certo?",
    ):
        proof = _price_proposal(graph, "aurora-product-polish", reply)
        assert "price_disclosure_requires_human" not in proof["errors"], reply


def test_check_proposal_keeps_the_legacy_rule_for_price_quoting_personas():
    graph = _graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    persona.data = {
        **persona.data,
        "appointment_policy": {
            **persona.data["appointment_policy"],
            "price_disclosure": "agent",
        },
    }
    proof = _price_proposal(graph, "aurora-product-polish", "Fica em R$ 650.")
    assert "price_disclosure_requires_human" not in proof["errors"]
    assert "price_without_graph_evidence" in proof["errors"]
    # A range with no "R$" is not policed at all for these personas.
    ranged = _price_proposal(graph, "aurora-product-polish", "A partir de 350.")
    assert ranged["valid"] is True

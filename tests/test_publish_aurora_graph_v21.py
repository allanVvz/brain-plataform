from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.publish_aurora_graph import build_graph
from routes.conversations import ContextRequest
from services import (
    graph_agent_runtime_v3,
    graph_compiler_v3,
    graph_json_v2_validator,
    graph_markdown,
)


def _compile(graph) -> dict:
    """Convert a built+canonicalized GraphJson into compile_graph()'s DB-row
    shape and compile it, mirroring how graph_compiler_v3.compile_graph is
    actually fed in production (knowledge_nodes/knowledge_edges rows, not
    GraphJson objects directly)."""
    knowledge_ids = {node.id for node in graph.nodes}
    node_rows = [{
        "id": node.id,
        "node_type": node.node_type,
        "slug": node.slug,
        "title": node.title,
        "summary": (node.data or {}).get("summary") or "",
        "tags": [],
        "status": node.lifecycle.status,
        "metadata": {"graph_json_node_id": node.id, **(node.data or {})},
    } for node in graph.nodes]
    edge_rows = [{
        "id": edge.id,
        "source_node_id": edge.source,
        "target_node_id": edge.target,
        "relation_type": edge.relation_type,
        "metadata": {"active": True, "graph_json_edge_id": edge.id},
    } for edge in graph.edges if edge.lifecycle.status == "active" and edge.target in knowledge_ids]
    persona_node = next(node for node in graph.nodes if node.node_type == "persona")
    persona = {"id": persona_node.id, "slug": graph.persona_slug}
    return graph_compiler_v3.compile_graph(persona=persona, node_rows=node_rows, edge_rows=edge_rows)


def test_aurora_rollout_builds_isolated_complete_agent_dataset() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)

    assert valid, errors
    assert graph.schema_version == "2.1"
    # Revisao 2026-08-21: 53 FAQs novas ficam pending_validation, lavagem de
    # motor/cofre entra no catalogo e 13 nodes sem fonte ficam arquivados.
    assert len(graph.nodes) == 153
    assert len(graph.edges) == 234

    embedded = next(node for node in graph.nodes if node.node_type == "embedded")
    assert embedded.action is not None
    assert embedded.action.destination_id == "dataset:sdr-aurora"
    assert embedded.action.consumer.ref == "sdr:aurora"

    grants = [
        edge for edge in graph.edges
        if edge.target == embedded.id
        and edge.relation_type == "publishes_to"
        and edge.lifecycle.status == "active"
    ]
    assert len(grants) == 84
    assert {edge.source for edge in grants} == {
        node.id
        for node in graph.nodes
        if node.node_class == "knowledge"
        and node.node_type != "persona"
        and node.lifecycle.status == "approved"
    }
    assert len({edge.id for edge in graph.edges}) == len(graph.edges)


def test_real_audio_transcription_typos_become_one_confirmable_service_candidate() -> None:
    document = _compile(graph_markdown.canonicalize_graph(build_graph()))
    cases = {
        "[audio do cliente]: Eu quero laçar meu carro.": "aurora-product-wash",
        "[audio do cliente]: Chapiação. Quero Chapiação.": "aurora-product-bodywork",
    }
    for message, expected_anchor in cases.items():
        resolution = graph_agent_runtime_v3._resolve_service_operations(
            document, message,
            active_branch_node_id=None, active_branch_node_ids=[],
        )
        assert resolution["status"] == "needs_confirmation"
        assert resolution["operations"] == []
        assert resolution["candidate"]["branch_anchor_node_id"] == expected_anchor
        assert resolution["confirmation"]["kind"] == "service"


def test_compiled_aurora_keeps_graph_owned_service_clarification_copy() -> None:
    document = _compile(graph_markdown.canonicalize_graph(build_graph()))
    policy = graph_agent_runtime_v3._service_clarification_policy(document)
    assert policy["add_or_switch_question"] == (
        "Você quer trocar o serviço atual ou adicionar {candidate} ao pedido?"
    )
    assert policy["retry_question"].startswith(
        "Acho que não estou conseguindo entender direitinho"
    )
    assert graph_agent_runtime_v3._service_request_summary(
        document, ["aurora-product-wash", "aurora-product-bodywork"],
    ) == "Até agora seu pedido tem: Lavagem detalhada, Chapeação."


def test_full_qualification_walk_never_asks_the_same_published_question_twice() -> None:
    """Offline equivalent of a WA Validator "sdr_qualificacao_carro" run:
    walks every published branch's full field list (the same order
    build_context()/decide() ask them in) and asserts no two fields resolve
    to the same question_node_id -- the one thing that would make the agent
    ask an identical published question twice in a row across a complete
    qualification, independent of what the model itself does. Runs against
    every branch produced by the real fixture (all 13 polimento variants
    included), not a synthetic one.
    """
    document = _compile(graph_markdown.canonicalize_graph(build_graph()))
    branch_anchors = document["branch_anchors"]
    assert len(branch_anchors) >= 13  # sanity: the polimento family is really there

    for anchor in branch_anchors:
        contract = document["branch_contracts"][anchor]
        fields = contract.get("fields") or []
        assert fields, f"branch {anchor} published with no qualification fields"
        seen: dict[str, str] = {}
        for field in fields:
            qid = str(field.get("question_node_id") or "")
            key = str(field.get("key") or "")
            assert qid, f"branch {anchor} field {key} has no question_node_id"
            if qid in seen:
                assert seen[qid] == key, (
                    f"branch {anchor}: fields '{seen[qid]}' and '{key}' both "
                    f"resolve to question_node_id={qid} -- the agent would "
                    "ask the same published question twice"
                )
            seen[qid] = key


def test_all_aurora_factual_faqs_receive_v34_projection_membership() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    document = _compile(graph)

    assert document["compiler_version"] == "graph-compiler-v3.6.2"
    assert document["faq_projection_contract"] == "v1"
    assert len(document["eligible_faq_node_ids"]) == 30
    # Thirteen portfolio/global FAQs are available in every branch; a branch
    # may additionally own service-specific FAQs.
    assert all(
        len(contract["eligible_faq_node_ids"]) >= 13
        for contract in document["branch_contracts"].values()
    )


def test_aurora_review_keeps_new_faqs_pending_and_unsupported_nodes_archived() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    embedded = next(node for node in graph.nodes if node.node_type == "embedded")

    pending_faqs = [
        node for node in graph.nodes
        if node.node_type == "faq" and node.lifecycle.status == "pending_validation"
    ]
    assert len(pending_faqs) == 53
    assert all(len((node.data or {}).get("question_aliases") or []) == 5 for node in pending_faqs)
    assert not any(
        edge.source in {node.id for node in pending_faqs}
        and edge.target == embedded.id
        and edge.relation_type == "publishes_to"
        and edge.lifecycle.status == "active"
        for edge in graph.edges
    )

    archived = {node.id for node in graph.nodes if node.lifecycle.status == "archived"}
    assert archived == {
        "aurora-product-polish-one-step", "aurora-copy-polish-one-step",
        "aurora-faq-polish-one-step", "aurora-product-polish-multi-step",
        "aurora-copy-polish-multi-step", "aurora-faq-polish-multi-step",
        "aurora-product-polish-localized", "aurora-copy-polish-localized",
        "aurora-faq-polish-localized", "aurora-product-polish-finish",
        "aurora-copy-polish-finish", "aurora-faq-polish-finish",
        "aurora-faq-polimento-tipos",
    }


def test_every_aurora_review_booking_field_has_a_graph_owned_question() -> None:
    graph = build_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = (persona.data or {})["appointment_policy"]
    assert policy["required_fields"] == ["nome_cliente", "servico"]

    required = set(policy["required_fields"])
    for product in (node for node in graph.nodes if node.node_type == "product"):
        if product.lifecycle.status != "approved":
            continue
        required.update((product.data or {}).get("booking", {}).get("required_fields") or [])
    assert required
    assert all(str(policy["field_questions"].get(key) or "").strip() for key in required)

    by_slug = {node.slug: node for node in graph.nodes}
    assert by_slug["lavagem-motor-cofre"].lifecycle.status == "approved"
    assert by_slug["lavagem-motor-cofre"].data["booking"]["required_fields"] == [
        "nome_cliente", "servico", "vazamento_oleo", "estrada_de_chao",
        "modelo_veiculo", "vehicle_year", "condicao",
    ]


def test_shared_qualification_fields_share_one_owner_across_products() -> None:
    """Regression test for the Aurora repeated-question bug (2026-08-08).

    Confirmed live: every product node declared the same qualification
    fields (nome_cliente, objective, can_visit_in_person, modelo_veiculo,
    vehicle_year, condicao, vehicle_color) with owner_node_id == that
    product's own id. graph_proof_checker_v3 requires a fact's
    owner_node_id to match the field's declared owner before counting it
    resolved, so any branch switch reopened all of them even though the
    question and expected answer never change across products. Only
    "servico" legitimately varies per product (it's derived from
    active_branch_node_id server-side regardless of what's declared here).
    A prior direct database fix for this got silently reverted by this
    exact script re-publishing from the fixture on the next deploy, so the
    fix has to live here, in build_graph(), not in the database.
    """
    graph = build_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    products = [node for node in graph.nodes if node.node_type == "product"]
    assert len(products) >= 2

    owners_by_key: dict[str, set[str]] = {}
    for product in products:
        for field in (product.data or {}).get("qualification", {}).get("fields", []):
            owners_by_key.setdefault(field["key"], set()).add(field["owner_node_id"])

    assert "modelo_veiculo" in owners_by_key  # sanity: fixture still declares it
    # "servico" legitimately stays branch-owned -- every product declares it
    # with its own id, so more than one distinct owner is expected here.
    assert len(owners_by_key["servico"]) > 1
    for key, owners in owners_by_key.items():
        if key == "servico":
            continue
        assert owners == {persona.id}, f"{key} has per-branch owners: {owners}"


def test_carry_over_generalizes_beyond_the_single_identity_field() -> None:
    """Regression (live 2026-08-18): a lead reopening a new journey/
    appointment after a previous one closed only had nome_cliente carried
    over -- the literal single field appointment_policy.identity_field
    named -- even though modelo_veiculo/vehicle_color/vehicle_year/condicao
    are all scope="persona" (customer-owned, not tied to one pedido) and
    had to be repeated from scratch. carry_over now defaults to every
    persona-scoped field except objective/can_visit_in_person (per-visit
    intent, not stable identity), so a future persona-scoped field carries
    over automatically without another code change."""
    graph = build_graph()
    products = [node for node in graph.nodes if node.node_type == "product"]
    assert len(products) >= 2
    # Not every product declares every field (e.g. one product's contract is
    # missing vehicle_color entirely -- a separate, real catalog-authoring
    # gap, unrelated to this fix), so union carry_over across every product
    # instead of reading just one.
    carry_over_by_key: dict[str, bool] = {}
    for product in products:
        for field in (product.data or {}).get("qualification", {}).get("fields", []):
            carry_over_by_key.setdefault(field["key"], field["carry_over"])

    assert carry_over_by_key["nome_cliente"] is True
    for key in ("modelo_veiculo", "vehicle_color", "vehicle_year", "condicao"):
        assert key in carry_over_by_key  # sanity: fixture still declares it
        assert carry_over_by_key[key] is True, f"{key} should carry over across journeys"

    assert carry_over_by_key["servico"] is False
    assert carry_over_by_key["objective"] is False
    assert carry_over_by_key["can_visit_in_person"] is False


def test_color_is_required_for_paint_bodywork_and_published_polish_branches() -> None:
    graph = build_graph()
    by_slug = {node.slug: node for node in graph.nodes}
    assert "polimento" in (by_slug["polimento-tecnico"].data or {}).get("aliases", [])

    compiled = _compile(graph)
    fields = {
        (compiled["node_by_id"][anchor]["slug"], field["key"]): field
        for anchor, contract in compiled["branch_contracts"].items()
        for field in contract.get("fields") or []
    }
    assert ("pintura", "vehicle_color") in fields
    assert ("chapeacao", "vehicle_color") in fields
    assert ("polimento-tecnico", "vehicle_color") in fields
    assert ("polimento-comercial", "vehicle_color") in fields
    assert ("vitrificacao", "vehicle_color") not in fields
    assert "correspondência" in fields[("pintura", "vehicle_color")]["context_guidance"]
    assert "correspondência" in fields[("chapeacao", "vehicle_color")]["context_guidance"]


def test_explanatory_polish_faqs_authorize_service_detail_claims() -> None:
    """Regression (live 2026-08-18): Aurora already knew the approved
    answer to "como funciona o polimento de vidros?" (a graph-computed
    doubt resolution, zero model calls) but the turn still got rejected
    with claim_evidence_not_authorized:service_detail -- the FAQ's own
    answer explains mechanism ("reduz manchas minerais...") but the graph
    only declared an "availability" claim for it, not "service_detail".
    Same gap confirmed on 6 sibling polish FAQs. Fixed by adding a
    service_detail claim alongside the existing availability one (both are
    true: the answer confirms availability AND explains how it works) --
    this pins that every one of those 7 FAQs authorizes both claim types
    without dropping the original availability authorization."""
    graph = build_graph()
    faq_ids = {
        "aurora-faq-glass-polish", "aurora-faq-polish-commercial",
        "aurora-faq-polish-one-step", "aurora-faq-polish-multi-step",
        "aurora-faq-polish-localized", "aurora-faq-polish-finish",
        "aurora-faq-polish-headlight",
    }
    faqs = {node.id: node for node in graph.nodes if node.id in faq_ids}
    assert set(faqs) == faq_ids
    for faq_id, node in faqs.items():
        claim_types = {claim["claim_type"] for claim in (node.data or {}).get("claims", [])}
        assert "availability" in claim_types, f"{faq_id} lost its availability claim"
        assert "service_detail" in claim_types, f"{faq_id} still missing service_detail"


def test_aurora_conversation_contract_rejects_blank_message_cleanly() -> None:
    from pydantic import ValidationError

    try:
        ContextRequest(persona_slug="aurora", lead_ref=1, message="   ")
    except ValidationError as exc:
        assert "message must not be blank" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("blank Aurora messages must be rejected before runtime")


def test_aurora_publishes_two_attempts_and_closed_objective_values() -> None:
    graph = build_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = (persona.data or {}).get("conversation_policy") or {}
    assert policy["question_repetition"]["max_attempts"] == 1
    assert policy["qualification"]["incomplete_handoff_template"]

    objective_fields = [
        field
        for node in graph.nodes
        for field in ((node.data or {}).get("qualification") or {}).get("fields") or []
        if field.get("key") == "objective"
    ]
    assert objective_fields
    assert all(field["validation"]["mode"] == "enum" for field in objective_fields)
    assert {
        item["value"] for item in objective_fields[0]["validation"]["values"]
    } == {"vender_em_breve", "continuar_cuidar_proteger"}


def test_non_sales_service_branches_are_reachable_with_authorized_handoff() -> None:
    """Regression test for the atendente_humano/reclamacao gap (2026-08-08).

    Confirmed live: leads asking to talk to a human or filing a complaint on
    their first message always failed with keep_without_active_branch and
    handoff_not_authorized, because no branch anchor existed for either
    intent -- only sellable "product" nodes were branch anchors, and the
    only published handoff rule required qualification_complete (a sales
    concept). Both intents now publish as "service" branch anchors with
    their own branch-scoped handoff rule, gated on qualification_complete
    just like the sales rule -- but each branch's own qualification is tiny
    (name only, or name + a free-text complaint). An earlier version of this
    rule used condition: null (always-authorized), which live-tested as a
    real bug: it forced handoff_requested=True before the model had even
    asked for the customer's name, which the model correctly didn't do yet
    on turn one, and the proof checker rejected the turn
    (handoff_required_by_rule).
    """
    graph = graph_markdown.canonicalize_graph(build_graph())
    document = _compile(graph)

    assert "aurora-service-atendimento-humano" in document["branch_anchors"]
    assert "aurora-service-reclamacao" in document["branch_anchors"]

    handoff_contract = document["branch_contracts"]["aurora-service-atendimento-humano"]
    assert [field["key"] for field in handoff_contract["fields"]] == ["nome_cliente"]
    assert all(field["question_node_id"] for field in handoff_contract["fields"])
    handoff_rules_by_id = {rule["node_id"]: rule for rule in handoff_contract["handoff_rules"]}
    assert handoff_rules_by_id["aurora-rule-handoff-humano"]["condition"] == "qualification_complete"

    complaint_contract = document["branch_contracts"]["aurora-service-reclamacao"]
    assert {field["key"] for field in complaint_contract["fields"]} == {
        "nome_cliente", "reclamacao_relato",
    }
    assert all(field["question_node_id"] for field in complaint_contract["fields"])
    reclamacao_field = next(
        field for field in complaint_contract["fields"] if field["key"] == "reclamacao_relato"
    )
    assert reclamacao_field["owner_node_id"] == "aurora-service-reclamacao"
    complaint_rules_by_id = {rule["node_id"]: rule for rule in complaint_contract["handoff_rules"]}
    assert complaint_rules_by_id["aurora-rule-reclamacao"]["condition"] == "qualification_complete"


def test_branch_scoped_handoff_rules_do_not_leak_into_unrelated_branches() -> None:
    """The two new handoff rules are branch-scoped (not global_context), so
    leaking into another branch's contract would wrongly let the model
    declare handoff_requested there once ITS OWN qualification completes --
    a car-wash sale finishing would falsely satisfy the complaint rule too.
    aurora-rule-operation must keep reaching every branch (it's the one
    genuinely global handoff rule, gating on qualification_complete)."""
    graph = graph_markdown.canonicalize_graph(build_graph())
    document = _compile(graph)

    for anchor in document["branch_anchors"]:
        rule_ids = {rule["node_id"] for rule in document["branch_contracts"][anchor]["handoff_rules"]}
        assert "aurora-rule-operation" in rule_ids, f"aurora-rule-operation missing from {anchor}"
        if anchor not in ("aurora-service-atendimento-humano", "aurora-service-reclamacao"):
            assert "aurora-rule-handoff-humano" not in rule_ids, f"leaked into {anchor}"
            assert "aurora-rule-reclamacao" not in rule_ids, f"leaked into {anchor}"

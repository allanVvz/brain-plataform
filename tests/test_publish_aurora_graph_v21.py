from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.publish_aurora_graph import build_graph
from routes.conversations import ContextRequest
from services import graph_compiler_v3, graph_json_v2_validator, graph_markdown


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
    assert len(graph.nodes) == 87
    assert len(graph.edges) == 168

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

    assert document["compiler_version"] == "graph-compiler-v3.5.0"
    assert document["faq_projection_contract"] == "v1"
    assert len(document["eligible_faq_node_ids"]) == 30
    # Thirteen portfolio/global FAQs are available in every branch; a branch
    # may additionally own service-specific FAQs.
    assert all(
        len(contract["eligible_faq_node_ids"]) >= 13
        for contract in document["branch_contracts"].values()
    )


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

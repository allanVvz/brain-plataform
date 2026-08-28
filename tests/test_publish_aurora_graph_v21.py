from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.publish_aurora_graph import build_graph, build_v3_source_rows
from routes.conversations import ContextRequest
from services import (
    graph_action_policy,
    graph_agent_runtime_v3,
    graph_compiler_v3,
    graph_json_v2_validator,
    graph_markdown,
)


def test_aurora_candidate_is_a_markdown_fixed_point_for_immutable_publish() -> None:
    graph = build_graph(expected_version=14)

    graph, _changes = graph_action_policy.apply(graph)

    before = {node.id: (node.markdown.content if node.markdown else "") for node in graph.nodes}
    canonical = graph_markdown.canonicalize_graph(graph, reject_markdown_drift=False)
    changed = [
        node.id for node in canonical.nodes
        if before.get(node.id) != (node.markdown.content if node.markdown else "")
    ]
    assert changed == [], changed


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


def test_aurora_v3_source_isolated_from_runtime_assets_and_duplicate_projection_rows() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    projection_nodes = [{
        "id": f"db:{node.id}",
        "node_type": "embed" if node.node_type == "embedded" else node.node_type,
        "slug": node.slug,
        "status": "approved",
        "metadata": {
            "graph_json_import": True,
            "graph_json_node_id": node.id,
            "active": True,
        },
    } for node in graph.nodes]
    duplicate_ids = {
        "aurora-faq-evaluation": "faq-avaliacao-inicial",
        "aurora-faq-vitrification": "faq-vitrificacao",
        "aurora-faq-ppf": "faq-ppf",
    }
    projection_nodes.extend({
        "id": f"duplicate:{stable_id}",
        "node_type": "faq",
        "slug": slug,
        "status": "pending_regeneration",
        "metadata": {
            "graph_json_import": True,
            "graph_json_node_id": stable_id,
            "active": True,
        },
    } for stable_id, slug in duplicate_ids.items())
    projection_nodes.append({
        "id": "external-asset",
        "node_type": "asset",
        "slug": "customer-media",
        "status": "active",
        "metadata": {"active": True},
    })
    projection_edges = [{
        "id": f"db:{edge.id}",
        "source_node_id": f"db:{edge.source}",
        "target_node_id": f"db:{edge.target}",
        "relation_type": edge.relation_type,
        "metadata": {"graph_json_edge_id": edge.id, "active": True},
    } for edge in graph.edges if edge.lifecycle.status == "active"]

    rows, edges, duplicates = build_v3_source_rows(
        graph,
        projection_nodes=list(reversed(projection_nodes)),
        projection_edges=list(reversed(projection_edges)),
    )

    assert len(rows) == len(graph.nodes) == 153
    assert len(edges) == len(graph.edges) == 287
    assert {row["id"] for row in duplicates} == {
        f"duplicate:{stable_id}" for stable_id in duplicate_ids
    }
    assert "external-asset" not in {row["id"] for row in rows}
    selected = {
        (row["metadata"] or {}).get("graph_json_node_id"): row
        for row in rows
    }
    assert all(
        selected[stable_id]["id"] == f"db:{stable_id}"
        for stable_id in duplicate_ids
    )

    compiled = graph_compiler_v3.compile_graph(
        persona={"id": "00000000-0000-4000-8000-000000000001", "slug": "aurora"},
        node_rows=rows,
        edge_rows=edges,
    )
    assert len(compiled["node_by_id"]) == 140
    assert len(compiled["edges"]) == 274
    assert len(compiled["branch_contracts"]) == 14
    assert len(compiled["eligible_faq_node_ids"]) == 83
    common_question_ids = [
        node_id for node_id in compiled["common_contract"]["closure_node_ids"]
        if node_id.startswith("faq:qualification:")
    ]
    assert common_question_ids == sorted(common_question_ids)


def test_aurora_rollout_builds_isolated_complete_agent_dataset() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)

    assert valid, errors
    assert graph.schema_version == "2.1"
    # Revisao 2026-08-23: as 53 FAQs autorizadas ficam aprovadas e publicadas;
    # lavagem de motor/cofre entra no catalogo e 13 nodes sem fonte seguem
    # arquivados.
    assert len(graph.nodes) == 153
    assert len(graph.edges) == 287

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
    assert len(grants) == 137
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

    assert document["compiler_version"] == "graph-compiler-v3.6.4"
    assert document["faq_projection_contract"] == "v1"
    assert len(document["eligible_faq_node_ids"]) == 83
    # Thirteen portfolio/global FAQs are available in every branch; a branch
    # may additionally own service-specific FAQs.
    assert all(
        len(contract["eligible_faq_node_ids"]) >= 13
        for contract in document["branch_contracts"].values()
    )


def test_aurora_review_publishes_authorized_faqs_and_keeps_unsupported_nodes_archived() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    embedded = next(node for node in graph.nodes if node.node_type == "embedded")

    approved_review_faqs = [
        node for node in graph.nodes
        if node.node_type == "faq"
        and node.lifecycle.status == "approved"
        and (node.data or {}).get("source") == "aurora_review_plan_2026_08_21"
    ]
    assert len(approved_review_faqs) == 53
    assert all(
        len((node.data or {}).get("question_aliases") or []) == 5
        for node in approved_review_faqs
    )
    assert all(any(
        edge.source == node.id
        and edge.target == embedded.id
        and edge.relation_type == "publishes_to"
        and edge.lifecycle.status == "active"
        for edge in graph.edges
    ) for node in approved_review_faqs)

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


def test_aurora_preferred_name_accepts_one_token_and_surname_is_optional() -> None:
    graph = build_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = (persona.data or {})["appointment_policy"]
    question = policy["field_questions"]["nome_cliente"]
    paraphrases = policy["field_question_paraphrases"]["nome_cliente"]
    name_fields = [
        field
        for node in graph.nodes
        for field in ((node.data or {}).get("qualification") or {}).get("fields") or []
        if field.get("key") == "nome_cliente"
    ]

    assert "sobrenome é opcional" in question.lower()
    assert question.count("?") == 1
    assert all(value.count("?") <= 1 for value in paraphrases)
    generated_name_fields = [field for field in name_fields if "carry_over" in field]
    assert generated_name_fields
    assert all(
        field["validation"]["semantic_type"] == "human_name"
        and field["validation"]["min_tokens"] == 1
        and field["carry_over"] is True
        and field["overwrite_policy"] == "explicit_correction"
        for field in generated_name_fields
    )


def test_specific_engine_wash_phrase_beats_generic_vehicle_wash() -> None:
    document = _compile(graph_markdown.canonicalize_graph(build_graph()))

    engine = graph_agent_runtime_v3._resolve_service_operations(
        document,
        "to pensando em lavar o motor como funciona",
        active_branch_node_id=None,
        active_branch_node_ids=[],
    )
    vehicle = graph_agent_runtime_v3._resolve_service_operations(
        document,
        "quero lavar o carro",
        active_branch_node_id=None,
        active_branch_node_ids=[],
    )

    assert engine["status"] == "needs_confirmation"
    assert engine["candidate"]["branch_anchor_node_id"] == "aurora-product-engine-wash"
    assert engine["candidate"]["evidence_span"] == "lavar o motor"
    assert vehicle["status"] == "resolved"
    assert vehicle["operations"][0]["branch_anchor_node_id"] == "aurora-product-wash"


def test_aurora_remote_faq_does_not_embed_qualification_questions() -> None:
    graph = build_graph()
    faq = next(node for node in graph.nodes if node.id == "aurora-faq-remote")
    answer = faq.data["answer"]

    assert "?" not in answer
    assert "me diz" not in answer.lower()
    assert "me manda" not in answer.lower()


def test_new_aurora_fields_publish_specific_validation_examples() -> None:
    graph = build_graph()
    fields = {
        field["key"]: field
        for node in graph.nodes
        for field in ((node.data or {}).get("qualification") or {}).get("fields") or []
    }

    previous = fields["procedimento_anterior"]["validation"]
    assert previous["mode"] == "enum"
    assert any(value["value"] == "nenhum" for value in previous["values"])
    assert fields["foco_brilho_riscos"]["validation"]["mode"] == "enum"
    assert fields["revestimento_bancos"]["validation"]["mode"] == "enum"
    assert fields["vazamento_oleo"]["validation"]["mode"] == "enum"
    assert fields["estrada_de_chao"]["validation"]["mode"] == "enum"
    assert fields["evaluation_route"]["validation"]["mode"] == "enum"
    remote = next(
        value for value in fields["evaluation_route"]["validation"]["values"]
        if value["value"] == "remota"
    )
    assert "prefiro começar a avaliação por fotos e vídeos" in remote["aliases"]


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


def test_aurora_does_not_publish_question_retry_authority_and_closes_objective_values() -> None:
    graph = build_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    policy = (persona.data or {}).get("conversation_policy") or {}
    assert "question_repetition" not in policy
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

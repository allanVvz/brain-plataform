"""Publish only Aurora's canonical graph fixture; never creates accounts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.graph_json_v2 import Edge, EdgeLifecycle, GraphJson, PublicationGrant
from services import (
    graph_compiler_v3,
    graph_conversation_contract,
    graph_document_publisher,
    graph_json_v21_adapter,
    graph_json_v2_store,
    supabase_client,
)


FIXTURE = ROOT / "scripts" / "fixtures" / "aurora_graph_v2.json"


def build_graph() -> GraphJson:
    """Build Aurora's v2.1 graph and preserve the 44-node agent dataset.

    The historical fixture published every approved factual node into the
    persona-wide RAG.  During the v2.1 cutover we make that authorization
    explicit against Aurora's isolated Embedded action so the dialogue loses
    neither rules, tone, products nor FAQs.
    """
    legacy = GraphJson.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    graph = graph_json_v21_adapter.upgrade_to_v21(legacy)
    graph = graph_conversation_contract.materialize_qualification_questions(graph)
    persona_node = next(node for node in graph.nodes if node.node_type == "persona")
    conversation_policy = dict((persona_node.data or {}).get("conversation_policy") or {})
    conversation_policy["question_repetition"] = {
        **dict(conversation_policy.get("question_repetition") or {}),
        "max_attempts": 1,
    }
    persona_node.data = {**dict(persona_node.data or {}), "conversation_policy": conversation_policy}
    appointment_policy = (persona_node.data or {}).get("appointment_policy") or {}
    question_ids = appointment_policy.get("field_question_node_ids") or {}
    conditional_fields = appointment_policy.get("conditional_fields") or {}
    node_by_id = {node.id: node for node in graph.nodes}
    primary_parent_id = {
        edge.target: edge.source
        for edge in graph.edges
        if edge.relation_type == "contains" and edge.lifecycle.status == "active"
    }

    def value_schema(field_key: str) -> dict:
        # Schema belongs to the published Aurora graph; the runtime never knows
        # these field names or their vertical in advance.
        if field_key == "vehicle_year":
            return {"anyOf": [
                {"type": "string", "pattern": "^[0-9]{4}$"},
                {"type": "integer", "minimum": 1886, "maximum": 2200},
            ]}
        if field_key in {"can_visit_in_person", "estrada_de_chao", "vazamento_oleo", "media_requested"}:
            return {"type": ["string", "boolean"]}
        return {"type": "string", "minLength": 1}

    service_values = [
        {
            "value": node.slug,
            "aliases": list(dict.fromkeys([
                str(node.title or node.label or node.slug),
                *[str(value) for value in ((node.data or {}).get("aliases") or [])],
            ])),
        }
        for node in graph.nodes if node.node_type in {"product", "service"}
    ]

    def field_validation(field_key: str) -> dict:
        invalid_response = "Não consegui entender essa informação com segurança."
        if field_key == "servico":
            return {
                "mode": "enum", "values": service_values,
                "invalid_response": "Não entendi exatamente qual serviço você quis dizer.",
            }
        if field_key == "objective":
            return {
                "mode": "enum",
                "values": [
                    {
                        "value": "vender_em_breve",
                        "aliases": ["vender o carro", "pretendo vender", "vender em breve"],
                    },
                    {
                        "value": "continuar_cuidar_proteger",
                        "aliases": [
                            "continuar com o veículo e cuidar bem dele",
                            "continuar com o carro",
                            "cuidado e proteção",
                        ],
                    },
                ],
                "invalid_response": "Não consegui identificar se o objetivo é vender ou continuar cuidando do veículo.",
            }
        if field_key == "can_visit_in_person":
            return {
                "mode": "enum",
                "values": [
                    {"value": True, "aliases": ["sim", "consigo levar", "posso levar"]},
                    {"value": False, "aliases": ["não", "prefiro seguir por aqui", "não consigo levar"]},
                ],
                "invalid_response": invalid_response,
            }
        if field_key == "procedimento_anterior":
            return {
                "mode": "semantic",
                "description": "Histórico declarado de procedimento anterior na pintura, inclusive resposta negativa.",
                "examples": [
                    "Nunca foi feito procedimento nessa pintura",
                    "Já fizeram polimento antes",
                    "Não sei se houve procedimento anterior",
                ],
                "invalid_response": invalid_response,
            }
        if field_key == "foco_brilho_riscos":
            return {
                "mode": "enum",
                "values": [
                    {"value": "brilho", "aliases": ["melhorar o brilho", "só brilho"]},
                    {"value": "riscos", "aliases": ["reduzir riscos", "tirar riscos"]},
                    {
                        "value": "brilho_e_riscos",
                        "aliases": ["brilho e riscos", "os dois", "melhorar o brilho e reduzir os riscos"],
                    },
                ],
                "invalid_response": invalid_response,
            }
        if field_key == "revestimento_bancos":
            return {
                "mode": "enum",
                "values": [
                    {"value": "couro", "aliases": ["couro", "bancos de couro"]},
                    {"value": "tecido", "aliases": ["tecido", "bancos de tecido"]},
                ],
                "invalid_response": invalid_response,
            }
        if field_key in {"estrada_de_chao", "vazamento_oleo", "media_requested"}:
            return {
                "mode": "enum",
                "values": [
                    {"value": True, "aliases": ["sim", "há", "tem", "posso enviar"]},
                    {"value": False, "aliases": ["não", "não há", "não tem"]},
                ],
                "invalid_response": invalid_response,
            }
        if field_key == "evaluation_route":
            return {
                "mode": "enum",
                "values": [
                    {"value": "presencial", "aliases": ["presencial", "levar o carro"]},
                    {
                        "value": "remota",
                        "aliases": ["remota", "por fotos e vídeos", "começar por fotos e vídeos"],
                    },
                ],
                "invalid_response": invalid_response,
            }
        if field_key == "vehicle_year":
            return {"mode": "schema", "invalid_response": invalid_response}
        semantic = {
            "nome_cliente": {
                "semantic_type": "human_full_name",
                "description": "Nome e sobrenome completos informados pelo cliente.",
                "examples": ["Beatriz Souza", "José da Silva", "Ana Paula Lima"],
                # The model reads a name far better than any string
                # comparison can. Above this confidence its reading stands on
                # its own (evidence and shape are still proved by the
                # backend), and confirming becomes the last resort instead of
                # the default -- which is what deadlocked the live flow on
                # 2026-08-19, when "allan rodrigues" could not match the
                # model's own "Allan Rodrigues".
                "model_confidence_min": 0.90,
                "min_tokens": 2,
                "max_tokens": 6,
                "confirmation_policy": "last_resort",
            },
            "modelo_veiculo": {
                "description": "Modelo ou identificação comercial do veículo.",
                "examples": ["Onix", "Civic", "Corolla Cross"],
            },
            "condicao": {
                "description": "Relato literal do estado atual ou incômodo percebido no veículo.",
                "examples": ["riscos na porta", "bancos manchados"],
            },
            "vehicle_color": {
                "description": "Cor informada para o veículo.",
                "examples": ["prata", "preto", "azul"],
            },
            "reclamacao_relato": {
                "description": "Relato literal do cliente sobre a ocorrência reclamada.",
                "examples": ["o problema voltou depois do atendimento"],
            },
        }.get(field_key) or {
            "description": "Informação comercial livre declarada por este node.",
            "examples": ["informação fornecida pelo cliente"],
        }
        return {"mode": "semantic", **semantic, "invalid_response": invalid_response}

    for node in graph.nodes:
        data = dict(node.data or {})
        capabilities = dict(data.get("capabilities") or {})
        parent_node = node_by_id.get(primary_parent_id.get(node.id))
        if node.node_type == "product":
            capabilities["branch_anchor"] = True
            booking = data.get("booking") if isinstance(data.get("booking"), dict) else {}
            field_guidance = (
                booking.get("field_guidance")
                if isinstance(booking.get("field_guidance"), dict) else {}
            )
            required = [str(field) for field in booking.get("required_fields") or [] if field]
            for field_key, branch_slugs in conditional_fields.items():
                if node.slug in (branch_slugs or []) and field_key not in required:
                    required.append(str(field_key))
            # Fields authored in the fixture (optional ones such as the remote-track
            # questions) survive; a generated field always wins on key conflict so the
            # required set stays derived from the published booking contract.
            authored_fields = {
                str(field.get("key")): field
                for field in ((data.get("qualification") or {}).get("fields") or [])
                if isinstance(field, dict) and field.get("key")
            }
            data["qualification"] = {"fields": [{
                "key": field_key,
                # Confirmed live 2026-08-08: every product/service node lists
                # the same qualification fields (nome_cliente, objective,
                # can_visit_in_person, modelo_veiculo, vehicle_year,
                # condicao, vehicle_color) with a *different* owner_node_id
                # per branch, even though they mean the same thing and share
                # the same question node regardless of which service the
                # customer is asking about. graph_proof_checker_v3 requires
                # fact.owner_node_id == field.owner_node_id before counting a
                # field resolved (commit 6538461), so any branch switch --
                # including one caused only by the classifier's own
                # imprecision, not a real change of mind -- reopened every
                # one of these as unanswered. "servico" is the one field
                # that legitimately differs per branch (it's who the branch
                # even is) and is auto-derived from active_branch_node_id
                # server-side regardless of what's declared here, so it
                # keeps its own branch as owner; every other field shares
                # the persona node as owner across all branches.
                "owner_node_id": node.id if field_key == "servico" else persona_node.id,
                "scope": "branch" if field_key == "servico" else "persona",
                "question_node_id": question_ids.get(field_key),
                "required": True,
                "accepted_statuses": (
                    ["known", "unknown"] if field_key == "vehicle_color" else ["known"]
                ),
                "value_schema": value_schema(field_key),
                "validation": field_validation(field_key),
                "normalization": (
                    "Retorne quatro dígitos." if field_key == "vehicle_year" else None
                ),
                "depends_on": [],
                "condition": None,
                "priority": 1.0 if field_key in {"servico", "modelo_veiculo"} else 0.7,
                "overwrite_policy": "explicit_correction",
                "context_guidance": str(field_guidance.get(field_key) or ""),
                # Confirmed live 2026-08-18: only nome_cliente (the literal
                # appointment_policy.identity_field) survived into a new
                # journey/appointment cycle -- every other persona-scoped
                # fact (vehicle model/color/year/condition) was silently
                # dropped even though scope="persona" already marks them as
                # customer-owned, not tied to one specific pedido. A
                # returning customer had to restate the whole vehicle from
                # scratch, only the service should ever need reconfirming.
                # docs/architecture/SDR_JOURNEY_STATE_MACHINE.md's own
                # documented default is "persona.data.qualification.fields
                # -> carry_over: true"; this now matches it, generalizing
                # to any future persona-scoped field automatically instead
                # of requiring a one-off code change. objective and
                # can_visit_in_person are the deliberate exceptions -- they
                # describe intent for THIS visit (why the customer is here,
                # whether they can come in person), not stable customer/
                # vehicle identity, so they still get reconfirmed each cycle.
                "carry_over": (
                    field_key != "servico"
                    and field_key not in {"objective", "can_visit_in_person"}
                ),
            } for field_key in required]}
            data["qualification"]["fields"].extend(
                field for key, field in authored_fields.items() if key not in required
            )
            claims = list(data.get("claims") or [])
            if data.get("price"):
                claims.append({
                    "claim_type": "price", "policy": {
                        "mode": "informational",
                        "qualifier": data.get("price_qualifier") or "published",
                    }, "evidence_node_ids": [node.id],
                })
            if booking.get("duration_minutes"):
                claims.append({
                    "claim_type": "duration", "policy": {"mode": "informational"},
                    "evidence_node_ids": [node.id],
                })
            data["claims"] = claims
            data["completion"] = {"required_fields": required}
            # The fixture authors which rule answers a price or scheduling question;
            # only the completion target is imposed here.
            data["handoff"] = {
                "on_completion": "aurora-rule-operation",
                **(data.get("handoff") or {}),
            }
        elif node.node_type == "service":
            # A "service" branch anchor (BRANCH_TYPES in
            # graph_conversation_contract.py already reserves this type)
            # covers non-sales intents -- talking to a human, filing a
            # complaint -- that don't need the product loop's vehicle
            # qualification. The fixture authors qualification.fields
            # directly (owner_node_id, value_schema and all); Python only
            # backfills question_node_id, since that id is only known once
            # materialize_qualification_questions() has run.
            capabilities["branch_anchor"] = True
            data["qualification"] = {"fields": [
                {
                    **field,
                    "question_node_id": question_ids.get(str(field.get("key"))),
                    "validation": field.get("validation")
                    or field_validation(str(field.get("key"))),
                }
                for field in ((data.get("qualification") or {}).get("fields") or [])
                if isinstance(field, dict) and field.get("key")
            ]}
        elif node.id == "aurora-rule-operation":
            capabilities.update({"global_context": True, "handoff_rule": True})
            data["handoff_rule"] = {
                "id": "aurora-human-confirmation",
                "condition": "qualification_complete",
                "text": appointment_policy.get("texts", {}).get("complemento_confirmacao"),
            }
            # Claims authored in the fixture (payment policy) are preserved.
            claims = list(data.get("claims") or [])
            claims.extend([
                {"claim_type": "availability", "policy": {"mode": "informational"},
                 "evidence_node_ids": [node.id],
                 "intent_aliases": ["disponibilidade", "vaga", "tem horário"]},
                {"claim_type": "schedule", "policy": {"mode": "human_confirmation_required"},
                 "evidence_node_ids": [node.id],
                 "intent_aliases": ["agenda", "agendamento", "confirmar horário"]},
            ])
            data["claims"] = claims
        elif node.node_type == "rule" and (
            data.get("handoff_rule") or capabilities.get("handoff_rule")
        ):
            handoff_rule = dict(data.get("handoff_rule") or {})
            # A rule authored with scope "branch" only needs to reach its own
            # branch's closure -- normal parent/child reachability already
            # gets it there, since these rules are authored as children of
            # their own service/product node. Forcing global_context on them
            # would leak an always-authorized handoff (condition: null) into
            # every unrelated branch. Every other rule the fixture publishes
            # as a handoff rule must still reach every branch closure,
            # otherwise graph_compiler_v3 rejects the references to it.
            branch_scoped = handoff_rule.pop("scope", None) == "branch"
            capabilities["handoff_rule"] = True
            if not branch_scoped:
                capabilities["global_context"] = True
            # The fixture names which published text answers this rule; the copy itself
            # stays in appointment_policy.texts so it is authored in exactly one place.
            text_key = handoff_rule.pop("text_key", None) or "atendimento_humano"
            handoff_rule.setdefault(
                "text", appointment_policy.get("texts", {}).get(text_key)
            )
            data["handoff_rule"] = handoff_rule
        elif (
            node.node_type == "faq"
            and parent_node is not None
            and parent_node.node_type == "product_group"
            and data.get("role") != "qualification_question"
        ):
            # FAQs authored directly under the catalog/service group describe
            # the portfolio as a whole, not one product branch.
            capabilities["global_context"] = True
        elif node.node_type in {"tone"}:
            capabilities["global_context"] = True
        if capabilities:
            data["capabilities"] = capabilities
        node.data = data
    embedded = next(node for node in graph.nodes if node.node_type == "embedded")
    if embedded.action is None:
        raise RuntimeError("Aurora Embedded action is missing")
    embedded.slug = "sdr-aurora"
    embedded.title = "Golden Dataset SDR Aurora"
    embedded.label = embedded.title
    embedded.action.destination_id = "dataset:sdr-aurora"
    embedded.action.consumer.kind = "agent"
    embedded.action.consumer.ref = "sdr:aurora"

    active_sources = {
        edge.source
        for edge in graph.edges
        if edge.target == embedded.id
        and edge.relation_type == "publishes_to"
        and edge.lifecycle.status == "active"
    }
    for node in graph.nodes:
        if (
            node.node_class != "knowledge"
            or node.node_type == "persona"
            or node.lifecycle.status != "approved"
            or node.id in active_sources
        ):
            continue
        graph.edges.append(
            Edge(
                id=f"edge:publish:{node.id}:sdr-aurora",
                source=node.id,
                target=embedded.id,
                relation_type="publishes_to",
                relation_class="publication",
                primary_tree=False,
                lifecycle=EdgeLifecycle(status="active"),
                grant=PublicationGrant(
                    mode="manual",
                    actor="production-release",
                    reason="Preserve Aurora's approved agent dataset during Graph v2.1 cutover",
                ),
                metadata={"migration": "aurora-v20-to-v21"},
            )
        )
    return graph


def publish(*, expected_version: int | None = None) -> dict:
    graph = build_graph()
    current = graph_json_v2_store.load_current("aurora", graph.brand_slug)
    base_version = int(expected_version) if expected_version is not None else (int(current[0]) if current else 0)
    checksum = graph_json_v2_store.checksum_graph(graph)
    return graph_document_publisher.commit(
        graph=graph,
        persona_slug="aurora",
        brand_slug=graph.brand_slug,
        source="aurora_markdown_release",
        reason="Aurora Graph JSON v2.1 canonical rollout",
        published_by="production-release",
        expected_version=base_version,
        idempotency_key=f"aurora-graph-v21:{checksum}",
    )


def _projection_node_types(node_type: str) -> set[str]:
    return {"embed", "embedded"} if node_type == "embedded" else {node_type}


def build_v3_source_rows(
    graph: GraphJson,
    *,
    projection_nodes: list[dict],
    projection_edges: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Build the Aurora v3 input from Graph v9, never from unrelated KB rows.

    UUIDs remain the materialized projection identities required by runtime and
    RAG foreign keys. All semantic fields come from the approved Graph JSON,
    so assets/conversations and importer bookkeeping cannot change the SHA.
    """
    nodes_by_stable: dict[str, list[dict]] = {}
    for row in projection_nodes:
        metadata = row.get("metadata") or {}
        if metadata.get("active", True) is False:
            continue
        stable_id = str(metadata.get("graph_json_node_id") or "")
        if stable_id:
            nodes_by_stable.setdefault(stable_id, []).append(row)

    selected_by_stable: dict[str, dict] = {}
    duplicate_rows: list[dict] = []
    for node in graph.nodes:
        candidates = nodes_by_stable.get(node.id) or []
        expected_types = _projection_node_types(node.node_type)
        exact = [
            row for row in candidates
            if str(row.get("node_type") or "") in expected_types
            and (
                node.node_type in {"persona", "embedded", "gallery"}
                or str(row.get("slug") or "") == node.slug
            )
        ]
        if len(exact) != 1:
            candidate_shapes = sorted(
                f"{row.get('node_type')}:{row.get('slug')}" for row in candidates
            )
            raise RuntimeError(
                f"aurora_projection_node_not_unique:{node.id}:exact={len(exact)}:"
                f"active={len(candidates)}:candidates={candidate_shapes}"
            )
        selected = exact[0]
        selected_by_stable[node.id] = selected
        duplicate_rows.extend(
            {**row, "canonical_projection_id": selected.get("id")}
            for row in candidates if row.get("id") != selected.get("id")
        )

    graph_edge_ids = {
        edge.id for edge in graph.edges if edge.lifecycle.status == "active"
    }
    projected_edges_by_stable: dict[str, list[dict]] = {}
    for row in projection_edges:
        metadata = row.get("metadata") or {}
        if metadata.get("active", True) is False:
            continue
        stable_id = str(metadata.get("graph_json_edge_id") or "")
        if stable_id in graph_edge_ids:
            projected_edges_by_stable.setdefault(stable_id, []).append(row)

    node_rows = []
    for node in graph.nodes:
        selected = selected_by_stable[node.id]
        node_rows.append({
            "id": selected["id"],
            "node_type": selected.get("node_type") or node.node_type,
            "slug": node.slug,
            "title": node.label,
            "summary": str((node.data or {}).get("summary") or ""),
            "tags": [],
            "status": node.lifecycle.status,
            "metadata": {"graph_json_node_id": node.id, **(node.data or {})},
        })

    edge_rows = []
    for edge in graph.edges:
        if edge.lifecycle.status != "active":
            continue
        projected = projected_edges_by_stable.get(edge.id) or []
        if len(projected) != 1:
            raise RuntimeError(
                f"aurora_projection_edge_not_unique:{edge.id}:active={len(projected)}"
            )
        edge_rows.append({
            "id": projected[0]["id"],
            "source_node_id": selected_by_stable[edge.source]["id"],
            "target_node_id": selected_by_stable[edge.target]["id"],
            "relation_type": edge.relation_type,
            "metadata": {"active": True, "graph_json_edge_id": edge.id},
        })
    return node_rows, edge_rows, duplicate_rows


def prepare_v3_candidate() -> dict:
    current = graph_json_v2_store.load_current(
        "aurora", "aurora-estetica-automotiva"
    )
    if not current:
        raise RuntimeError("aurora_current_graph_missing")
    version, graph = current
    persona = supabase_client.get_persona("aurora")
    if not persona:
        raise RuntimeError("aurora_persona_missing")
    all_nodes, all_edges = supabase_client.list_all_knowledge_graph(
        persona_id=str(persona["id"]), limit_nodes=10000
    )
    projection_nodes = [
        row for row in all_nodes
        if (row.get("metadata") or {}).get("graph_json_import") is True
    ]
    projection_edges = [
        row for row in all_edges
        if (row.get("metadata") or {}).get("graph_json_edge_id")
    ]
    node_rows, edge_rows, duplicate_rows = build_v3_source_rows(
        graph,
        projection_nodes=projection_nodes,
        projection_edges=projection_edges,
    )
    document = graph_compiler_v3.compile_graph(
        persona=persona, node_rows=node_rows, edge_rows=edge_rows
    )
    return {
        "legacy_version": version,
        "legacy_checksum": graph_json_v2_store.checksum_graph(graph),
        "graph": graph,
        "persona": persona,
        "node_rows": node_rows,
        "edge_rows": edge_rows,
        "duplicate_rows": duplicate_rows,
        "document": document,
    }


def _require_candidate(candidate: dict, *, expected_legacy_checksum: str | None,
                       expected_runtime_checksum: str | None) -> None:
    if expected_legacy_checksum and candidate["legacy_checksum"] != expected_legacy_checksum:
        raise RuntimeError(
            f"aurora_legacy_checksum_mismatch:{candidate['legacy_checksum']}:"
            f"{expected_legacy_checksum}"
        )
    actual_runtime = candidate["document"]["checksum"]
    if expected_runtime_checksum and actual_runtime != expected_runtime_checksum:
        raise RuntimeError(
            f"aurora_runtime_checksum_mismatch:{actual_runtime}:"
            f"{expected_runtime_checksum}"
        )


def v3_action(*, action: str, expected_legacy_checksum: str | None,
              expected_runtime_checksum: str | None,
              publication_id: str | None) -> dict:
    candidate = prepare_v3_candidate()
    _require_candidate(
        candidate,
        expected_legacy_checksum=expected_legacy_checksum,
        expected_runtime_checksum=expected_runtime_checksum,
    )
    document = candidate["document"]
    base = {
        "action": action,
        "legacy_version": candidate["legacy_version"],
        "legacy_checksum": candidate["legacy_checksum"],
        "runtime_checksum": document["checksum"],
        "compiler_version": document["compiler_version"],
        "source_node_count": len(candidate["node_rows"]),
        "source_edge_count": len(candidate["edge_rows"]),
        "compiled_node_count": len(document["node_by_id"]),
        "compiled_edge_count": len(document["edges"]),
        "branch_count": len(document["branch_contracts"]),
        "eligible_faq_count": len(document["eligible_faq_node_ids"]),
        "duplicate_projection_ids": [row.get("id") for row in candidate["duplicate_rows"]],
    }
    if action == "dry-run":
        return base
    if action == "repair-duplicates":
        repaired = []
        for row in candidate["duplicate_rows"]:
            metadata = {
                **(row.get("metadata") or {}),
                "active": False,
                "projection_duplicate_of": row.get("canonical_projection_id"),
                "projection_removed_in_version": candidate["legacy_version"],
                "projection_removed_from": "aurora_v3_final_publication",
            }
            supabase_client.update_knowledge_node(
                str(row["id"]), {"metadata": metadata}, mark_related_faqs=False
            )
            repaired.append(str(row["id"]))
        return {**base, "repaired_duplicate_ids": repaired}
    if action == "stage":
        staged = graph_compiler_v3.compile_persona_publication(
            "aurora",
            activate=False,
            source_rows=(candidate["node_rows"], candidate["edge_rows"]),
        )
        publication = staged.get("publication") or {}
        if publication.get("checksum") != document["checksum"]:
            raise RuntimeError("aurora_staged_checksum_mismatch")
        return {
            **base,
            "publication_id": publication.get("id"),
            "publication_version": publication.get("version"),
            "publication_status": publication.get("status"),
            "cached": staged.get("cached"),
        }
    if action == "activate":
        if not publication_id:
            raise RuntimeError("aurora_publication_id_required")
        client = supabase_client.get_client()
        publication = (
            client.table("graph_publications").select("*")
            .eq("id", publication_id).eq("persona_id", candidate["persona"]["id"])
            .maybe_single().execute().data
        )
        if not publication:
            raise RuntimeError("aurora_staged_publication_missing")
        if publication.get("status") not in {"compiled", "active"}:
            raise RuntimeError(
                f"aurora_staged_publication_not_activatable:{publication.get('status')}"
            )
        if publication.get("checksum") != document["checksum"]:
            raise RuntimeError("aurora_publication_checksum_changed_before_activation")
        activation = client.rpc(
            "activate_graph_publication_v3", {"p_publication_id": publication_id}
        ).execute().data
        return {
            **base,
            "publication_id": publication_id,
            "publication_version": publication.get("version"),
            "publication_status": "active",
            "activation": activation,
        }
    raise RuntimeError(f"unsupported_v3_action:{action}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--skip-v3", action="store_true")
    parser.add_argument(
        "--v3-action",
        choices=["dry-run", "repair-duplicates", "stage", "activate"],
    )
    parser.add_argument("--expected-legacy-checksum")
    parser.add_argument("--expected-runtime-checksum")
    parser.add_argument("--publication-id")
    args = parser.parse_args()
    if args.v3_action:
        print(json.dumps(v3_action(
            action=args.v3_action,
            expected_legacy_checksum=args.expected_legacy_checksum,
            expected_runtime_checksum=args.expected_runtime_checksum,
            publication_id=args.publication_id,
        ), ensure_ascii=False, default=str))
        raise SystemExit(0)
    result = publish(expected_version=args.expected_version)
    v3_result = None
    if result.get("ok") and not args.skip_v3:
        v3_result = graph_compiler_v3.compile_persona_publication("aurora", activate=True)
    print(json.dumps({
        "ok": result.get("ok"),
        "version": result.get("version"),
        "checksum": result.get("checksum"),
        "idempotent_replay": result.get("idempotent_replay"),
        "graph_agent_runtime_v3": ({
            "publication_id": (v3_result or {}).get("publication", {}).get("id"),
            "version": (v3_result or {}).get("publication", {}).get("version"),
            "checksum": (v3_result or {}).get("publication", {}).get("checksum"),
        } if v3_result else None),
    }))

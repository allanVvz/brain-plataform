"""Two-phase, branch-scoped GraphRAG context and proposal reconciliation."""
from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from schemas.conversation import (
    AgentResponse,
    ContextCard,
    ConversationContext,
    ConversationDecision,
    ConversationProposal,
    ConversationRoute,
)
from services import graph_compiler_v3, graph_proof_checker_v3, supabase_client


RUNTIME_VERSION = "graph_agent_runtime_v3"


def _invalid_proposal_fallback(
    context: ConversationContext, raw: Any, errors: list[str]
) -> tuple[ConversationDecision, AgentResponse]:
    contract = context.graph_contract or {}
    facts = context.cart.get("facts") or {}
    pending = graph_proof_checker_v3.pending_fields(contract, facts)
    question_id = next(
        (field.get("question_node_id") for field in pending if field.get("question_node_id")),
        None,
    )
    reply = graph_proof_checker_v3.compose_published_question(
        reply="", next_question_node_id=question_id, contract=contract
    )
    proof = {
        "valid": False,
        "errors": list(dict.fromkeys(errors)),
        "repair_required": False,
        "fallback_used": True,
        "model_proposal": raw if isinstance(raw, dict) else {"raw_type": type(raw).__name__},
        "missing_fields": [field["key"] for field in pending],
    }
    return (
        ConversationDecision(
            classifier="graph_proof_checker_v3", intent="published_fallback",
            route=ConversationRoute.SDR, confidence=0,
            lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            evidence_node_ids=[question_id] if question_id else [],
        ),
        AgentResponse(
            reply_text=reply or None, role=ConversationRoute.SDR,
            evidence_node_ids=[question_id] if question_id else [],
            cart_state=context.cart, handoff_required=False, proof=proof,
        ),
    )


def binding_uses_v3(binding: dict[str, Any] | None) -> bool:
    metadata = (binding or {}).get("metadata") or {}
    return str(metadata.get("runtime_version") or metadata.get("agent_runtime") or "") == RUNTIME_VERSION


def _source_message_id(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") == "user" or str(message.get("sender_type") or "") == "lead":
            return str(message.get("message_id") or message.get("external_message_id") or "")
    return ""


def _mmr(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Diversity reranking over the bounded result returned by Postgres."""
    selected: list[dict[str, Any]] = []
    remaining = list(candidates)

    def terms(row: dict[str, Any]) -> set[str]:
        return {token for token in str(row.get("chunk_text") or "").casefold().split() if len(token) > 2}

    while remaining and len(selected) < limit:
        best: tuple[float, str, dict[str, Any]] | None = None
        for row in remaining:
            relevance = float(row.get("hybrid_score") or 0)
            redundancy = 0.0
            row_terms = terms(row)
            for prior in selected:
                prior_terms = terms(prior)
                overlap = len(row_terms & prior_terms) / max(1, len(row_terms | prior_terms))
                same_source = row.get("source_node_id") == prior.get("source_node_id")
                redundancy = max(redundancy, overlap, 0.8 if same_source else 0.0)
            score = 0.78 * relevance - 0.22 * redundancy
            candidate = (score, str(row.get("chunk_id") or row.get("id") or ""), row)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None:
            break
        selected.append(best[2])
        remaining.remove(best[2])
    return selected


def _required_structural_chunks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one executable chunk per required node outside probabilistic MMR."""
    kind_priority = {
        "question": 6, "claims": 5, "rule": 5, "rules": 5,
        "validators": 4, "structured_facts": 3, "content": 2,
    }
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("source_node_id") or row.get("source_graph_node_id") or "")
        if not source:
            continue
        current = selected.get(source)
        score = kind_priority.get(str(row.get("chunk_kind") or ""), 1)
        current_score = kind_priority.get(str((current or {}).get("chunk_kind") or ""), 1)
        if current is None or score > current_score:
            selected[source] = row
    return list(selected.values())


def _card(publication: dict[str, Any], node: dict[str, Any], chunks: list[dict[str, Any]], position: int) -> ContextCard:
    text = "\n\n".join(str(chunk.get("chunk_text") or "") for chunk in chunks if chunk.get("chunk_text"))
    coordinate = ((publication.get("document_json") or {}).get("coordinates") or {}).get(node["id"]) or {}
    return ContextCard(
        id=node["id"], projection_node_id=node.get("projection_node_id"),
        node_type=node["node_type"], slug=node["slug"], title=node["title"],
        rendered_content=text or node.get("summary") or node["title"],
        editable_content=text, content_checksum=graph_compiler_v3.canonical_checksum(text),
        revision=1, graph_version=int(publication["version"]),
        graph_checksum=publication["checksum"], context_role="branch_retrieval",
        position=position, selection_reason={"runtime": RUNTIME_VERSION},
        path=coordinate.get("path_node_ids") or [],
        chunk_refs=[str(chunk.get("chunk_id") or chunk.get("id")) for chunk in chunks],
        source=str((node.get("data") or {}).get("source") or "pending_source"),
        status=node.get("status") or "validated", relations=[],
        technical_metadata={**coordinate, "publication_id": publication["id"]},
    )


def _candidate_branches(
    *, persona_id: str, publication: dict[str, Any], message: str,
    embedding: list[float], active_path: list[str], missing: list[str],
) -> list[dict[str, Any]]:
    document = publication.get("document_json") or {}
    candidates: list[dict[str, Any]] = []
    for anchor in document.get("branch_anchors") or []:
        rows = supabase_client.search_graph_rag_v3(
            persona_id=persona_id, publication_id=publication["id"],
            branch_node_id=anchor, query=message, query_embedding=embedding,
            active_path_node_ids=active_path, missing_fields=missing, limit=3,
        )
        score = max([float(row.get("hybrid_score") or 0) for row in rows] or [0.0])
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        candidates.append({
            "branch_anchor_node_id": anchor,
            "branch_path_checksum": ((document.get("coordinates") or {}).get(anchor) or {}).get("path_checksum"),
            "title": node.get("title"), "aliases": (node.get("data") or {}).get("aliases") or [],
            "score": round(score, 6),
            "evidence_chunks": rows,
        })
    return sorted(candidates, key=lambda item: (-item["score"], item["branch_anchor_node_id"]))


def build_context(
    *, persona_slug: str, lead_ref: int, message: str, message_id: str | None,
) -> ConversationContext:
    started = time.perf_counter()
    persona = supabase_client.get_persona(persona_slug) or {}
    lead = supabase_client.get_lead_by_ref(lead_ref) or {}
    if not persona or not lead:
        raise LookupError("persona or lead not found")
    if str(lead.get("persona_id")) != str(persona.get("id")):
        raise PermissionError("lead does not belong to requested persona")
    publication = supabase_client.get_active_graph_publication(str(persona["id"]))
    if not publication:
        raise RuntimeError("active GraphRAG v3 publication not found")
    document = publication.get("document_json") or {}
    messages = supabase_client.get_messages(str(lead_ref), limit=20) or []
    if message and not any(str(row.get("message_id") or row.get("external_message_id") or "") == str(message_id or "") for row in messages):
        messages.append({"message_id": message_id, "sender_type": "lead", "role": "user", "texto": message})
    ledger = supabase_client.get_conversation_ledger(str(persona["id"]), lead_ref) or {
        "active_branch_node_id": None, "publication_id": publication["id"],
        "graph_checksum": publication["checksum"], "revision": 0,
        "asked_question_node_ids": [], "facts": {},
    }
    publication_changed = str(ledger.get("publication_id")) != str(publication["id"])
    active_branch = str(ledger.get("active_branch_node_id") or "") or None
    if active_branch not in set(document.get("branch_anchors") or []):
        active_branch = None
    active_contract = (document.get("branch_contracts") or {}).get(active_branch) or {}
    declared = {field["key"]: field for field in active_contract.get("fields") or []}
    invalidated_fact_keys: list[str] = []
    if publication_changed:
        previous_facts = ledger.get("facts") or {}
        ledger["facts"] = {
            key: value for key, value in previous_facts.items()
            if key in declared
            and graph_proof_checker_v3.fact_compatible(declared[key], value)
        }
        invalidated_fact_keys = sorted(set(previous_facts) - set(ledger["facts"]))
        ledger["asked_question_node_ids"] = []
        ledger["publication_id"] = publication["id"]
        ledger["graph_checksum"] = publication["checksum"]
    missing = [field["key"] for field in graph_proof_checker_v3.pending_fields(active_contract, ledger.get("facts") or {})]
    active_path = ((document.get("coordinates") or {}).get(active_branch) or {}).get("path_node_ids") or []
    embedding = graph_compiler_v3.query_embeddings([message])[0]
    # A short answer while a field is expected never reopens global selection.
    short_expected_answer = bool(active_branch and missing and len(message.split()) <= 8)
    candidates = [] if short_expected_answer else _candidate_branches(
        persona_id=str(persona["id"]), publication=publication, message=message,
        embedding=embedding, active_path=active_path, missing=missing,
    )
    retrieval_branch = active_branch or (candidates[0]["branch_anchor_node_id"] if candidates else None)
    if not retrieval_branch:
        raise RuntimeError("GraphRAG publication has no resolvable branch")
    contract = (document.get("branch_contracts") or {}).get(retrieval_branch) or {}
    missing = [field["key"] for field in graph_proof_checker_v3.pending_fields(contract, ledger.get("facts") or {})]
    rows = supabase_client.search_graph_rag_v3(
        persona_id=str(persona["id"]), publication_id=publication["id"],
        branch_node_id=retrieval_branch, query=message, query_embedding=embedding,
        active_path_node_ids=((document.get("coordinates") or {}).get(retrieval_branch) or {}).get("path_node_ids") or [],
        missing_fields=missing, limit=48,
    )
    required_nodes = list(dict.fromkeys([
        *(((document.get("coordinates") or {}).get(retrieval_branch) or {}).get("path_node_ids") or []),
        *(field.get("question_node_id") for field in contract.get("fields") or [] if field["key"] in missing),
        *(contract.get("handoff_rule_node_ids") or []),
    ]))
    structural = supabase_client.get_graph_rag_repair_chunks(
        publication_id=publication["id"], branch_node_id=retrieval_branch,
        requirements=[{"kind": "node", "id": node_id} for node_id in required_nodes if node_id],
    )
    merged = {str(row.get("chunk_id") or row.get("id")): row for row in [*rows, *structural]}
    selected = _mmr(list(merged.values()), 16)
    required_structural = _required_structural_chunks(structural)
    # Phase-A evidence is isolated from the Phase-B branch package and is
    # available only for a proposed select/switch proof.
    candidate_chunks = {
        str(row.get("chunk_id") or row.get("id")): row
        for candidate in candidates[:5] for row in candidate.get("evidence_chunks") or []
    }
    package = list({
        **candidate_chunks,
        **{str(row.get("chunk_id") or row.get("id")): row for row in selected},
        **{str(row.get("chunk_id") or row.get("id")): row for row in required_structural},
    }.values())
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in package:
        by_source.setdefault(str(row.get("source_node_id") or row.get("source_graph_node_id") or ""), []).append(row)
    cards = [
        _card(publication, document["node_by_id"][node_id], chunks, index)
        for index, (node_id, chunks) in enumerate(by_source.items())
        if node_id in (document.get("node_by_id") or {})
    ]
    possible_switches = [
        item["branch_anchor_node_id"] for item in candidates
        if item["branch_anchor_node_id"] != active_branch and item["score"] >= 0.18
    ]
    trace = {
        "runtime_version": RUNTIME_VERSION, "publication_id": publication["id"],
        "publication_version": publication["version"], "graph_checksum": publication["checksum"],
        "ledger_revision": int(ledger.get("revision") or 0),
        "publication_changed": publication_changed,
        "invalidated_fact_keys": invalidated_fact_keys,
        "short_expected_answer": short_expected_answer,
        "global_branch_search_executed": not short_expected_answer,
        "retrieval_branch_node_id": retrieval_branch,
        "branch_candidates": candidates[:8], "possible_switches": possible_switches,
        "required_structural_chunk_ids": [
            str(row.get("chunk_id") or row.get("id")) for row in required_structural
        ],
        "chunk_ids": [str(row.get("chunk_id") or row.get("id")) for row in package],
        "source_node_ids": sorted(by_source),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    prompt = (
        "Você propõe a conversa; o backend apenas prova o GraphRAG publicado. "
        "Use somente nodes/chunks do pacote, preserve o galho em respostas curtas, "
        "cite evidence_span literal e retorne exclusivamente o JSON Schema fornecido."
    )
    return ConversationContext(
        persona_slug=persona_slug, agent_slug=str((persona.get("config") or {}).get("agent_slug") or "agent"),
        graph_version=int(publication["version"]), graph_checksum=publication["checksum"],
        messages=messages[-20:], cart={**((lead.get("metadata") or {}).get("conversation_state") or {}),
                                      "facts": ledger.get("facts") or {},
                                      "active_branch_node_id": active_branch,
                                      "asked_question_node_ids": ledger.get("asked_question_node_ids") or [],
                                      "_ledger_revision": ledger.get("revision") or 0},
        rag_nodes=[document["node_by_id"][node_id] for node_id in by_source if node_id in document["node_by_id"]],
        rag_paths=[card.path for card in cards], rag_chunks=package, context_cards=cards,
        system_prompt=prompt, available_services=[{
            "slug": document["node_by_id"][anchor]["slug"], "label": document["node_by_id"][anchor]["title"]
        } for anchor in document.get("branch_anchors") or []],
        active_branch_node_id=active_branch,
        active_path_checksum=((document.get("coordinates") or {}).get(active_branch) or {}).get("path_checksum"),
        branch_node_ids=contract.get("closure_node_ids") or [], graph_contract=contract,
        publication_id=publication["id"], runtime_version=RUNTIME_VERSION, retrieval_trace=trace,
    )


def decide(
    context: ConversationContext, *, model_observation: dict[str, Any] | None
) -> tuple[ConversationDecision, AgentResponse]:
    observation = model_observation or {}
    if observation.get("contract_probe") is True:
        return (
            ConversationDecision(classifier="graph_contract_probe_v3", intent="await_model_proposal",
                                 route=ConversationRoute.SDR, confidence=1, lead_stage=str(context.cart.get("_lead_stage") or "novo")),
            AgentResponse(reply_text=None, role=ConversationRoute.SDR, cart_state=context.cart,
                          proof={"valid": True, "mode": "contract_probe", "runtime_version": RUNTIME_VERSION}),
        )
    raw = observation.get("proposal") if isinstance(observation.get("proposal"), dict) else observation
    parse_errors = [str(value) for value in observation.get("proposal_parse_errors") or []]
    try:
        proposal = ConversationProposal.model_validate(raw)
    except ValidationError as exc:
        return _invalid_proposal_fallback(
            context, raw, [*parse_errors, f"proposal_schema_invalid:{exc.errors(include_url=False)}"]
        )
    if parse_errors:
        return _invalid_proposal_fallback(context, raw, parse_errors)
    persona = supabase_client.get_persona(context.persona_slug) or {}
    publication = supabase_client.get_active_graph_publication(str(persona.get("id") or "")) or {}
    if str(publication.get("id")) != str(context.publication_id) or publication.get("checksum") != context.graph_checksum:
        raise RuntimeError("GraphRAG publication changed during turn")
    document = publication.get("document_json") or {}
    contract = (document.get("branch_contracts") or {}).get(proposal.branch_anchor_node_id) or {}
    ledger = {
        "active_branch_node_id": context.active_branch_node_id,
        "publication_id": context.publication_id, "graph_checksum": context.graph_checksum,
        "revision": context.retrieval_trace.get("ledger_revision", 0),
        "facts": context.cart.get("facts") or {},
        "asked_question_node_ids": context.cart.get("asked_question_node_ids") or [],
    }
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract, ledger=ledger,
        proposal=proposal.model_dump(mode="json"), message=next(
            (str(row.get("texto") or row.get("message") or "") for row in reversed(context.messages)
             if str(row.get("role") or "") == "user" or str(row.get("sender_type") or "") == "lead"), ""
        ), source_message_id=_source_message_id(context.messages),
        package_node_ids={card.id for card in context.context_cards} | {
            str(value) for value in observation.get("repair_context_node_ids") or [] if value
        },
        package_chunk_ids={str(row.get("chunk_id") or row.get("id")) for row in context.rag_chunks} | {
            str(value) for value in observation.get("repair_context_chunk_ids") or [] if value
        },
        active_branch_node_id=context.active_branch_node_id,
        branch_selection_allowed=context.active_branch_node_id is None and proposal.branch_anchor_node_id in {
            item.get("branch_anchor_node_id") for item in context.retrieval_trace.get("branch_candidates") or []
        },
        branch_switch_allowed=proposal.branch_anchor_node_id in set(context.retrieval_trace.get("possible_switches") or []),
        package_chunk_sources={
            str(row.get("chunk_id") or row.get("id")): str(
                row.get("source_node_id") or row.get("source_graph_node_id") or ""
            )
            for row in context.rag_chunks
        } | {
            str(chunk_id): str(source_id)
            for chunk_id, source_id in (
                observation.get("repair_context_chunk_sources") or {}
            ).items()
        },
    )
    # An explicit switch is only a Phase-A decision on the first pass. Force
    # one directed Phase-B retrieval for the selected branch before any reply
    # or fact can be committed, even if an anchor snippet happened to suffice.
    if (
        int(observation.get("repair_attempt") or 0) == 0
        and proposal.branch_action.value in {"select", "switch"}
        and proposal.branch_anchor_node_id
        != context.retrieval_trace.get("retrieval_branch_node_id")
        and not [error for error in proof["errors"] if "outside_package" not in error]
    ):
        requirement_ids = list(dict.fromkeys([
            proposal.branch_anchor_node_id,
            *(((document.get("coordinates") or {}).get(proposal.branch_anchor_node_id) or {}).get("path_node_ids") or []),
            *proposal.cited_node_ids,
            *([proposal.next_question_node_id] if proposal.next_question_node_id else []),
            *(contract.get("handoff_rule_node_ids") or []),
        ]))
        proof.update({
            "valid": False,
            "errors": [*proof["errors"], "selected_branch_requires_phase_b"],
            "repair_required": True,
            "repair_requirements": [
                {"kind": "node", "id": node_id} for node_id in requirement_ids if node_id
            ],
        })
    repair_cards: list[dict[str, Any]] = []
    if proof["repair_required"] and int(observation.get("repair_attempt") or 0) < 1:
        proof["repair_contract"] = contract
        rows = supabase_client.get_graph_rag_repair_chunks(
            publication_id=publication["id"], branch_node_id=proposal.branch_anchor_node_id,
            requirements=proof["repair_requirements"],
        )
        sources: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            sources.setdefault(str(row.get("source_graph_node_id") or ""), []).append(row)
        repair_cards = [
            _card(publication, document["node_by_id"][node_id], chunks, index).model_dump(mode="json")
            for index, (node_id, chunks) in enumerate(sources.items()) if node_id in document.get("node_by_id", {})
        ]
        response = AgentResponse(reply_text=None, role=ConversationRoute.SDR, cart_state=context.cart,
                                 proposal=proposal, proof=proof, repair_context_cards=repair_cards)
        return ConversationDecision(classifier="graph_proof_checker_v3", intent="repair_retrieval",
                                    route=ConversationRoute.SDR, confidence=0, lead_stage=str(context.cart.get("_lead_stage") or "novo")), response
    if proof["valid"]:
        reply = graph_proof_checker_v3.compose_published_question(
            reply=proposal.reply, next_question_node_id=proposal.next_question_node_id, contract=contract
        )
        facts = dict(proof["ledger"]["facts"])
        accepted_facts = list(proof.get("accepted_facts") or [])
        servico_field = next(
            (field for field in contract.get("fields") or [] if field.get("key") == "servico"), None
        )
        branch_node = (document.get("node_by_id") or {}).get(proposal.branch_anchor_node_id) or {}
        if servico_field and branch_node and (
            facts.get("servico", {}).get("owner_node_id") != proposal.branch_anchor_node_id
        ):
            # The branch anchor is already the structural source of truth
            # for "which service" (proposal.branch_anchor_node_id).
            # Deriving the servico fact from it here — instead of trusting
            # a separately model-extracted fact — means the two can never
            # disagree, and it's re-derived every turn the branch stays
            # active, so it can never go stale the way a one-time
            # extracted fact could. Only runs when the branch's own
            # contract declares a "servico" field, so personas that don't
            # use this convention are unaffected.
            servico_fact = {
                "field_key": "servico",
                "status": "known",
                "value": str(branch_node.get("slug") or branch_node.get("title") or proposal.branch_anchor_node_id),
                "owner_node_id": proposal.branch_anchor_node_id,
                "confidence": 1.0,
                "evidence_span": None,
                "source_message_id": _source_message_id(context.messages),
            }
            facts["servico"] = servico_fact
            accepted_facts.append(servico_fact)
        state = {**context.cart, "facts": facts,
                 "active_branch_node_id": proposal.branch_anchor_node_id,
                 "asked_question_node_ids": list(dict.fromkeys([
                     *(context.cart.get("asked_question_node_ids") or []),
                     *([proposal.next_question_node_id] if proposal.next_question_node_id else []),
                 ]))}
        route = ConversationRoute.HUMAN if proposal.handoff_requested else ConversationRoute.SDR
        return (
            ConversationDecision(classifier="graph_proof_checker_v3",
                                 intent="qualification_complete" if proposal.qualification_complete else "collect_graph_fields",
                                 route=route, confidence=1, lead_stage="qualificado" if proposal.qualification_complete else "engajado",
                                 handoff_reason="graph_handoff_rule" if proposal.handoff_requested else None,
                                 evidence_node_ids=proposal.cited_node_ids),
            AgentResponse(reply_text=reply, role=route, evidence_node_ids=proposal.cited_node_ids,
                          cart_state=state, handoff_required=proposal.handoff_requested,
                          proposal=proposal, proof={**proof, "accepted_facts": accepted_facts}),
        )
    # A technical failure emits only the next published question.  It never
    # fabricates commercial copy and never requests handoff by itself.
    fallback_id = next((field.get("question_node_id") for field in contract.get("fields") or []
                        if field["key"] in proof.get("missing_fields") or []), None)
    fallback = graph_proof_checker_v3.compose_published_question(
        reply="", next_question_node_id=fallback_id, contract=contract
    )
    fallback_proof = {**proof, "repair_required": False, "fallback_used": True}
    return (
        ConversationDecision(classifier="graph_proof_checker_v3", intent="published_fallback",
                             route=ConversationRoute.SDR, confidence=0,
                             lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                             evidence_node_ids=[fallback_id] if fallback_id else []),
        AgentResponse(reply_text=fallback or None, role=ConversationRoute.SDR,
                      evidence_node_ids=[fallback_id] if fallback_id else [], cart_state=context.cart,
                      handoff_required=False, proposal=proposal, proof=fallback_proof),
    )

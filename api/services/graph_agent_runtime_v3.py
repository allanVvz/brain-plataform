"""Two-phase, branch-scoped GraphRAG context and proposal reconciliation."""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
import difflib
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from schemas.conversation import (
    AgentResponse,
    BranchAction,
    ContextCard,
    ConversationContext,
    ConversationDecision,
    ConversationProposal,
    ConversationRoute,
    ExtractedFact,
)
from services import graph_compiler_v3, graph_proof_checker_v3, supabase_client


logger = logging.getLogger("graph_agent_runtime_v3")

RUNTIME_VERSION = "graph_agent_runtime_v3"


def _normalize_servico_owner(
    proposal: ConversationProposal, contract: dict[str, Any]
) -> ConversationProposal:
    """Repoint a mismatched "servico" fact to the branch the model just picked.

    Confirmed live 2026-08-08: the model sometimes copies a Phase-A candidate
    branch's owner_node_id into the "servico" extracted fact instead of its
    own proposal.branch_anchor_node_id -- plausibly picked up from that other
    candidate's evidence chunks in the same prompt. check_proposal() then
    rejects the *entire* proposal on the owner-match guard added in commit
    6538461, even though the value is discarded anyway: the block below
    always re-derives "servico" from branch_anchor_node_id once the proposal
    is valid, so a model-declared owner_node_id for it is pure noise. Fixing
    it before validation, instead of only after, lets an otherwise-correct
    branch selection go through. Only runs when the branch's own contract
    declares a "servico" field, matching the same convention as the
    auto-derivation block below, so personas that don't use it are
    unaffected.
    """
    if not any(field.get("key") == "servico" for field in contract.get("fields") or []):
        return proposal
    normalized_facts = [
        fact.model_copy(update={"owner_node_id": proposal.branch_anchor_node_id})
        if fact.field_key == "servico" and fact.owner_node_id != proposal.branch_anchor_node_id
        else fact
        for fact in proposal.extracted_facts
    ]
    if normalized_facts == proposal.extracted_facts:
        return proposal
    return proposal.model_copy(update={"extracted_facts": normalized_facts})


def _normalize_premature_servico_requestion(
    proposal: ConversationProposal, contract: dict[str, Any], ledger_facts: dict[str, Any],
) -> ConversationProposal:
    """Repoint a next_question_node_id that re-asks an already-known "servico".

    Confirmed live 2026-08-08, re-validating the report's other fixes in
    production: right after a branch gets selected (turn N), the model's
    very next turn (N+1) often proposes next_question_node_id pointing back
    at the "servico" question, even though servico was already resolved by
    the branch selection itself. check_proposal() correctly rejects that
    (servico isn't a pending field anymore) with
    next_question_not_for_pending_field, but the rejection discards the
    *entire* otherwise-correct proposal -- including whatever fact the
    model did extract that same turn (a customer's name, in the confirmed
    case), reintroducing the exact repeated-question symptom this session's
    other fixes closed. Since "servico" is always auto-derived and never
    actually pending once a branch is active, repoint the question to
    whatever field genuinely is still pending, before validation -- the
    same normalize-before-validating principle as the owner_node_id fix
    above. Only runs when the branch's own contract declares a "servico"
    field and it is already known, matching that same fix's convention.
    """
    servico_field = next((f for f in contract.get("fields") or [] if f.get("key") == "servico"), None)
    if not servico_field or not servico_field.get("question_node_id"):
        return proposal
    if proposal.next_question_node_id != servico_field["question_node_id"]:
        return proposal
    if (ledger_facts.get("servico") or {}).get("status") != "known":
        return proposal
    pending = graph_proof_checker_v3.pending_fields(contract, ledger_facts)
    substitute = next((field.get("question_node_id") for field in pending if field.get("question_node_id")), None)
    if not substitute or substitute == proposal.next_question_node_id:
        return proposal
    return proposal.model_copy(update={"next_question_node_id": substitute})


def _normalize_stale_next_question_after_branch_change(
    proposal: ConversationProposal, contract: dict[str, Any], ledger_facts: dict[str, Any],
) -> ConversationProposal:
    """Repoint a next_question_node_id that doesn't fit the branch just selected.

    Confirmed live 2026-08-09 (lead_ref 117, "prefiro fazer lavagem técnica
    detalhada em vez de pintura"): right when the model proposes
    branch_action "select"/"switch", it can still propose a
    next_question_node_id that isn't one of the *new* branch's genuinely
    pending fields (it can misjudge field order, or hang onto a question
    from the branch it's leaving). check_proposal() correctly rejects that
    as next_question_not_for_pending_field, but the rejection discards the
    *entire* otherwise-correct proposal -- the branch change itself and
    every fact extracted alongside it -- so the customer's request to
    change service goes silently unfulfilled, the same failure mode
    _drop_stale_branch_citations already fixed for citations and
    _normalize_premature_servico_requestion already fixed for the
    servico-specific case. This generalizes that fix to any field: repoint
    to whatever field is genuinely still pending for the branch about to be
    selected, using the same servico auto-derivation the runtime performs
    after validity so the substitute reflects the branch change about to be
    committed, not the branch being left.
    """
    if proposal.branch_action.value not in {"select", "switch"}:
        return proposal
    effective_facts = dict(ledger_facts)
    servico_field = next((f for f in contract.get("fields") or [] if f.get("key") == "servico"), None)
    if servico_field:
        effective_facts["servico"] = {
            "status": "known", "value": proposal.branch_anchor_node_id,
            "owner_node_id": proposal.branch_anchor_node_id,
        }
    for fact in proposal.extracted_facts:
        effective_facts[fact.field_key] = {
            "status": fact.status.value if hasattr(fact.status, "value") else fact.status,
            "value": fact.value, "owner_node_id": fact.owner_node_id,
        }
    pending = graph_proof_checker_v3.pending_fields(contract, effective_facts)
    pending_question_ids = {field.get("question_node_id") for field in pending if field.get("question_node_id")}
    if proposal.next_question_node_id in pending_question_ids:
        return proposal
    substitute = pending[0].get("question_node_id") if pending else None
    if substitute == proposal.next_question_node_id:
        return proposal
    return proposal.model_copy(update={"next_question_node_id": substitute})


def _drop_stale_branch_citations(
    proposal: ConversationProposal,
    *,
    previous_branch_closure: set[str],
    chunk_sources: dict[str, str],
) -> ConversationProposal:
    """Drop citations left over from the branch a switch is leaving behind.

    Confirmed live 2026-08-08: when the model proposes branch_action=switch,
    it sometimes still cites a node/chunk from the branch it is leaving --
    plausibly because that content was still in view while it was composing
    the reply explaining the switch. check_proposal() correctly rejects any
    citation outside the *new* branch's closure (cited_node_outside_branch /
    cited_chunk_outside_branch), and unlike a citation that's merely outside
    the retrieved *package* (cited_node_outside_package), there is no repair
    that can fix this -- the old branch's content will never belong to the
    new branch's closure, so check_proposal() has no choice but to reject
    the *entire* otherwise-correct proposal, including the switch itself and
    every fact extracted alongside it. The customer's request to change
    service then goes silently unfulfilled for the rest of the conversation.
    Dropping only the citations pointing at the branch being left (before
    validation ever sees them) preserves grounding for every other citation
    while letting the switch itself go through.
    """
    if not previous_branch_closure:
        return proposal
    cited_node_ids = [n for n in proposal.cited_node_ids if n not in previous_branch_closure]
    cited_chunk_ids = [
        c for c in proposal.cited_chunk_ids if chunk_sources.get(c) not in previous_branch_closure
    ]
    if cited_node_ids == proposal.cited_node_ids and cited_chunk_ids == proposal.cited_chunk_ids:
        return proposal
    return proposal.model_copy(update={
        "cited_node_ids": cited_node_ids, "cited_chunk_ids": cited_chunk_ids,
    })


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


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _format_time_gap(delta_seconds: float) -> str:
    if delta_seconds < 60:
        return "poucos instantes atrás"
    if delta_seconds < 3600:
        minutes = int(delta_seconds // 60)
        return f"{minutes} minuto{'s' if minutes != 1 else ''} atrás"
    if delta_seconds < 86400:
        hours = int(delta_seconds // 3600)
        return f"{hours} hora{'s' if hours != 1 else ''} atrás"
    days = int(delta_seconds // 86400)
    return f"há {days} dia{'s' if days != 1 else ''}"


def _time_since_last_client_message(
    messages: list[dict[str, Any]], current_message_id: str | None
) -> str | None:
    """Human-readable gap since the client's previous message, computed in
    Python (never left for the model to work out from raw ISO timestamps --
    models are unreliable at date arithmetic).
    """
    for message in reversed(messages):
        is_client = (
            str(message.get("role") or "") == "user"
            or str(message.get("sender_type") or "") == "lead"
        )
        message_id = str(message.get("message_id") or message.get("external_message_id") or "")
        if not is_client or (current_message_id and message_id == str(current_message_id)):
            continue
        sent_at = _parse_timestamp(message.get("created_at"))
        if not sent_at:
            return None
        delta = (datetime.now(timezone.utc) - sent_at).total_seconds()
        return _format_time_gap(max(0.0, delta))
    return None


def _known_facts_payload(
    facts: dict[str, Any], current_message_id: str | None
) -> list[dict[str, Any]]:
    """Every resolved fact (not just the active branch's own fields),
    tagged with whether it was confirmed in this exact turn ("esta_conversa")
    or is being carried over from an earlier one ("anterior") -- so the
    model can reference known context from other branches/sessions (e.g. a
    previously known service when the current branch is a complaint) while
    knowing which facts it should confirm rather than silently assume.
    """
    payload = []
    for key, fact in (facts or {}).items():
        if not isinstance(fact, dict) or fact.get("status") != "known":
            continue
        source_id = str(fact.get("source_message_id") or "")
        origem = (
            "esta_conversa"
            if current_message_id and source_id == str(current_message_id)
            else "anterior"
        )
        payload.append({"chave": key, "valor": fact.get("value"), "origem": origem})
    return payload


def _estimated_tokens(text: str) -> int:
    """Same rough chars/4 estimate context_cards.resolve_cards() already
    uses for its own max_tokens budget -- good enough for a guardrail, not
    meant to match a real tokenizer exactly."""
    return max(1, len(text or "") // 4)


# Confirmed live 2026-08-08 (WA Validator gap report): the v3 runtime's own
# card/chunk assembly had no token-count budget at all, only a card-count
# cap (_mmr(..., 16)) -- unlike the legacy context_cards.resolve_cards(),
# which already enforces max_tokens=8000. Any future addition to what's
# retrieved per turn (e.g. tone/flow-management skill content) could grow
# per-turn input size unboundedly with nothing to stop it. This is a real,
# enforced ceiling on the RAG chunk package specifically (context_cards are
# capped separately downstream); it does not by itself guarantee the exact
# total prompt size, but it makes "we didn't grow this" a checkable claim
# instead of an assumption.
RAG_CHUNK_TOKEN_BUDGET = 6000
RAG_CHUNK_LIMIT = 12


def _mmr(candidates: list[dict[str, Any]], limit: int, *, max_tokens: int = RAG_CHUNK_TOKEN_BUDGET) -> list[dict[str, Any]]:
    """Diversity reranking over the bounded result returned by Postgres."""
    selected: list[dict[str, Any]] = []
    remaining = list(candidates)
    token_count = 0

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
        estimated = _estimated_tokens(str(best[2].get("chunk_text") or ""))
        if selected and token_count + estimated > max_tokens:
            break
        token_count += estimated
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


def _required_retrieval_node_ids(
    document: dict[str, Any],
    branch_node_id: str,
    contract: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    """Return the executable structural package for one turn.

    The published branch contract already carries every question and handoff
    rule verbatim.  The chunk package therefore needs the full active path,
    the *next* graph-owned question (missing_fields[0]), and the handoff rule
    nodes.  Loading a chunk for every later question duplicated the contract
    and made every real appointment branch exceed the 12-chunk hard limit.
    """
    path = (
        ((document.get("coordinates") or {}).get(branch_node_id) or {})
        .get("path_node_ids") or []
    )
    next_field = missing_fields[0] if missing_fields else None
    next_question = next(
        (
            field.get("question_node_id")
            for field in contract.get("fields") or []
            if field.get("key") == next_field
        ),
        None,
    )
    return list(dict.fromkeys([
        *path,
        *([next_question] if next_question else []),
        *(contract.get("handoff_rule_node_ids") or []),
    ]))


def _repair_chunks(
    rows: list[dict[str, Any]], requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep exact requested chunks plus one structural chunk per node."""
    requested_chunk_ids = {
        str(item.get("id"))
        for item in requirements
        if item.get("kind") == "chunk" and item.get("id")
    }
    exact = {
        str(row.get("chunk_id") or row.get("id")): row
        for row in rows
        if str(row.get("chunk_id") or row.get("id")) in requested_chunk_ids
    }
    structural = {
        str(row.get("chunk_id") or row.get("id")): row
        for row in _required_structural_chunks(rows)
    }
    return list({**structural, **exact}.values())


def _card(publication: dict[str, Any], node: dict[str, Any], chunks: list[dict[str, Any]], position: int) -> ContextCard:
    text = "\n\n".join(str(chunk.get("chunk_text") or "") for chunk in chunks if chunk.get("chunk_text"))
    coordinate = ((publication.get("document_json") or {}).get("coordinates") or {}).get(node["id"]) or {}
    return ContextCard(
        id=node["id"], projection_node_id=node.get("projection_node_id"),
        node_type=node["node_type"], slug=node["slug"], title=node["title"],
        rendered_content=text or node.get("summary") or node["title"],
        editable_content=text, content_checksum=graph_compiler_v3.canonical_content_checksum(
            text or node.get("summary") or node["title"]
        ),
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
    ranked = supabase_client.rank_graph_branches_v3(
        persona_id=persona_id,
        publication_id=publication["id"],
        query=message,
        query_embedding=embedding,
        limit=8,
    )
    by_anchor = {str(row.get("branch_anchor_node_id")): row for row in ranked}
    candidates: list[dict[str, Any]] = []
    for anchor in document.get("branch_anchors") or []:
        rank = by_anchor.get(str(anchor)) or {}
        score = float(rank.get("score") or 0)
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        candidates.append({
            "branch_anchor_node_id": anchor,
            "branch_path_checksum": ((document.get("coordinates") or {}).get(anchor) or {}).get("path_checksum"),
            "title": node.get("title"), "aliases": (node.get("data") or {}).get("aliases") or [],
            "score": round(score, 6),
            "snippet": str(rank.get("snippet") or "")[:240],
            "evidence_chunk_ids": [str(rank["chunk_id"])] if rank.get("chunk_id") else [],
        })
    return sorted(candidates, key=lambda item: (-item["score"], item["branch_anchor_node_id"]))


def _normalized_phrase(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


_ADDITIVE_SERVICE_MARKER = re.compile(
    r"\b(?:tamb[eé]m|al[eé]m(?:\s+de)?|junto(?:s|\s+com)?|adiciona(?:r|ndo)?|"
    r"incluir|inclui(?:r|ndo)?|mais\s+um|also|too)\b",
    re.IGNORECASE,
)


def _latest_user_message(context: ConversationContext) -> str:
    return next(
        (
            str(row.get("content") or row.get("texto") or row.get("message") or "")
            for row in reversed(context.messages)
            if str(row.get("role") or "") == "user"
            or str(row.get("sender_type") or "") == "lead"
        ),
        "",
    )


def _message_requests_additional_service(message: str) -> bool:
    return bool(_ADDITIVE_SERVICE_MARKER.search(message or ""))


def _facts_by_key(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        normalized = {
            **row,
            "value": row.get("value", row.get("value_json")),
            "fact_id": row.get("fact_id", row.get("id")),
        }
        grouped.setdefault(str(row.get("field_key") or ""), []).append(normalized)
    return grouped


def _facts_for_contract(
    contract: dict[str, Any], grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    scoped: dict[str, dict[str, Any]] = {}
    for field in contract.get("fields") or []:
        key = str(field.get("key") or "")
        owner = str(field.get("owner_node_id") or "")
        match = next(
            (
                fact for fact in grouped.get(key, [])
                if str(fact.get("owner_node_id") or "") == owner
            ),
            None,
        )
        if match is not None:
            scoped[key] = match
    return scoped


def _literal_phrase_span(message: str, phrase: Any) -> str:
    """Return the exact customer substring matching a normalized graph phrase."""
    target = _normalized_phrase(phrase)
    if not target:
        return ""
    target_tokens = target.split()
    tokens = list(re.finditer(r"\w+", str(message or ""), flags=re.UNICODE))
    normalized_tokens = [_normalized_phrase(match.group(0)) for match in tokens]
    width = len(target_tokens)
    for index in range(0, len(tokens) - width + 1):
        if normalized_tokens[index : index + width] != target_tokens:
            continue
        return str(message)[tokens[index].start() : tokens[index + width - 1].end()]
    return ""


def _deterministic_branch_candidates(
    document: dict[str, Any], message: str,
) -> list[dict[str, Any]]:
    """Resolve graph-owned titles/aliases before semantic retrieval.

    This is generic graph data, not commercial copy in backend code. An
    unambiguous phrase opens the branch directly and avoids an LLM repair call.
    """
    normalized_message = f" {_normalized_phrase(message)} "
    matches: list[dict[str, Any]] = []
    for anchor in document.get("branch_anchors") or []:
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        phrases = [node.get("title"), node.get("slug"), *((node.get("data") or {}).get("aliases") or [])]
        matched = max(
            (
                (phrase, span) for raw in phrases
                if (phrase := _normalized_phrase(raw)) and len(phrase) >= 3
                and f" {phrase} " in normalized_message
                and (span := _literal_phrase_span(message, raw))
            ),
            key=lambda item: len(item[0]),
            default=("", ""),
        )
        if matched[0]:
            matches.append({
                "branch_anchor_node_id": anchor,
                "branch_path_checksum": ((document.get("coordinates") or {}).get(anchor) or {}).get("path_checksum"),
                "title": node.get("title"),
                "score": 1.0,
                "snippet": matched[1],
                "branch_evidence_span": matched[1],
                "evidence_chunk_ids": [],
                "deterministic_alias_match": True,
            })
    return matches if len(matches) == 1 else []


def _apply_authoritative_branch_resolution(
    proposal: ConversationProposal,
    context: ConversationContext,
    document: dict[str, Any],
) -> ConversationProposal:
    """Make graph/backend state authoritative over model branch routing."""
    resolved = context.retrieval_trace.get("deterministic_branch_resolution") or {}
    active = str(context.active_branch_node_id or "") or None
    resolved_anchor = str(resolved.get("branch_anchor_node_id") or "") or None
    if resolved_anchor:
        anchor = resolved_anchor
        active_set = set(context.active_branch_node_ids)
        if active:
            active_set.add(active)
        if anchor in active_set:
            action = "keep"
        elif active and _message_requests_additional_service(_latest_user_message(context)):
            action = "add"
        else:
            action = "switch" if active else "select"
        evidence_span = str(resolved.get("branch_evidence_span") or resolved.get("snippet") or "")
    elif active:
        proposed_anchor = str(proposal.branch_anchor_node_id or "")
        if (
            proposal.branch_action.value in {"switch", "add"}
            and proposed_anchor in set(context.retrieval_trace.get("possible_switches") or [])
            and proposal.branch_evidence_span
        ):
            return proposal
        anchor = active
        action = "keep"
        evidence_span = ""
    else:
        return proposal

    coordinate = ((document.get("coordinates") or {}).get(anchor) or {})
    extracted = [fact for fact in proposal.extracted_facts if fact.field_key != "servico"]
    if resolved_anchor:
        branch_node = (document.get("node_by_id") or {}).get(anchor) or {}
        extracted.append(ExtractedFact(
            field_key="servico",
            value=str(branch_node.get("slug") or branch_node.get("title") or anchor),
            status="known",
            source_message_id=_source_message_id(context.messages),
            owner_node_id=anchor,
            evidence_span=evidence_span,
            confidence=1.0,
        ))
    return proposal.model_copy(update={
        "branch_action": BranchAction(action),
        "branch_anchor_node_id": anchor,
        "branch_path_checksum": str(coordinate.get("path_checksum") or ""),
        "branch_evidence_span": evidence_span,
        "extracted_facts": extracted,
    })


def _normalize_next_question_to_first_missing(
    proposal: ConversationProposal,
    contract: dict[str, Any],
    ledger_facts: dict[str, Any],
) -> ConversationProposal:
    """Resolve the next question from the first graph-owned missing field."""
    effective_facts = dict(ledger_facts)
    for fact in proposal.extracted_facts:
        effective_facts[fact.field_key] = {
            "status": fact.status.value if hasattr(fact.status, "value") else fact.status,
            "value": fact.value,
            "owner_node_id": fact.owner_node_id,
        }
    pending = graph_proof_checker_v3.pending_fields(contract, effective_facts)
    expected = pending[0].get("question_node_id") if pending else None
    if proposal.next_question_node_id == expected:
        return proposal
    return proposal.model_copy(update={"next_question_node_id": expected})


def _project_recent_messages(messages: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for row in messages[-limit:]:
        projected.append({
            "message_id": row.get("message_id") or row.get("id") or row.get("external_message_id"),
            "role": row.get("role") or ("user" if row.get("direction") == "inbound" else "assistant"),
            "content": row.get("content") or row.get("texto") or row.get("text") or "",
            "created_at": row.get("created_at"),
        })
    return projected


def _repeats_recent_outbound(reply: str, messages: list[dict[str, Any]]) -> bool:
    folded = _normalized_phrase(reply)
    if not folded:
        return False
    recent = [
        _normalized_phrase(row.get("content") or row.get("texto") or "")
        for row in messages
        if str(row.get("role") or "") == "assistant"
        or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
    ][-3:]
    return any(
        previous and difflib.SequenceMatcher(None, folded, previous, autojunk=False).ratio() >= 0.92
        for previous in recent
    )


def _compact_prompt_chunk(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    provenance = metadata.get("provenance") or {}
    return {
        "chunk_id": row.get("chunk_id") or row.get("id"),
        "source_node_id": row.get("source_node_id") or row.get("source_graph_node_id"),
        "chunk_kind": row.get("chunk_kind"),
        "chunk_text": row.get("chunk_text"),
        "chunk_checksum": row.get("chunk_checksum"),
        "path_checksum": row.get("path_checksum"),
        "metadata": {
            "provenance": {
                key: provenance.get(key)
                for key in ("source", "status", "source_url")
                if provenance.get(key) not in (None, "")
            }
        },
    }


BRANCH_EVIDENCE_MIN_SCORE = 0.18


def _evidenced_branch_candidates(
    candidates: list[dict[str, Any]], *, limit: int = 8,
) -> list[dict[str, Any]]:
    """Candidates with real signal, for gating an unsolicited branch pick.

    `_candidate_branches` always returns one entry per branch anchor, even
    at score 0.0 -- it exists to rank/display candidates, not to gate
    anything. `branch_selection_allowed` (graph_agent_runtime_v3._decide)
    used to be keyed off the raw top-8 candidates with no score floor, so
    the model could "select" any branch -- including one with zero real
    evidence -- as long as it wasn't outside the top 8 of the full anchor
    list. Confirmed live 2026-08-10: a bare name/greeting turn (no product
    or complaint signal at all) got waved into Aurora's reclamação branch
    this way. This applies the same evidence floor already used for
    `possible_switches`, so both gates can never drift apart again.
    """
    return [
        {
            "branch_anchor_node_id": item["branch_anchor_node_id"],
            "title": item.get("title"),
            "score": item["score"],
            "branch_path_checksum": item.get("branch_path_checksum"),
            "snippet": str(item.get("snippet") or "")[:240],
        }
        for item in candidates
        if item["score"] >= BRANCH_EVIDENCE_MIN_SCORE
    ][:limit]


def _fallback_retrieval_branch(
    *, active_branch: str | None, candidates: list[dict[str, Any]], branch_anchors: list[str],
) -> str | None:
    """Pick a branch to retrieve context against when nothing scored.

    Confirmed live 2026-08-08: a message with no service/product signal at
    all (a bare greeting, "Oi") scores every Phase-A candidate near zero,
    so `candidates` comes back empty; with no active branch yet either,
    build_context() used to raise and the whole turn produced no reply at
    all, not even a generic one -- retrieval requires *some* branch to
    query against today. This never selects a branch on the customer's
    behalf (the returned context's active_branch_node_id stays untouched,
    so branch_selection_allowed for the model's own proposal is unaffected)
    -- it only picks a deterministic retrieval target so context still
    loads; persona-level content (tone, brand, global rules) is part of
    every branch's closure regardless of which one is picked here.
    """
    if active_branch:
        return active_branch
    if candidates:
        return candidates[0]["branch_anchor_node_id"]
    if branch_anchors:
        return sorted(branch_anchors)[0]
    return None


def _retrieval_branch_for_turn(
    *,
    active_branch: str | None,
    deterministic_candidates: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    branch_anchors: list[str],
) -> str | None:
    """Choose the package that can prove this turn's deterministic branch.

    An exact, unambiguous graph title/alias is already an authoritative
    select/switch decision.  Its branch package must therefore be retrieved
    before the model call.  Falling back to the previous active branch here
    forces a second repair pass and, when n8n does not execute that pass,
    persists an invalid proof with no reply.  Fuzzy candidates still never
    override the active branch; only the literal graph match receives this
    precedence.
    """
    if len(deterministic_candidates) == 1:
        return str(deterministic_candidates[0].get("branch_anchor_node_id") or "") or None
    return _fallback_retrieval_branch(
        active_branch=active_branch,
        candidates=candidates,
        branch_anchors=branch_anchors,
    )


def _publication_fact_is_compatible(
    document: dict[str, Any], active_contract: dict[str, Any],
    key: str, fact: dict[str, Any],
) -> bool:
    """Preserve persona-owned facts independently of an active branch."""
    candidates = [
        field for field in active_contract.get("fields") or []
        if field.get("key") == key
    ]
    persona_node_id = next(
        (
            str(node.get("id")) for node in document.get("nodes") or []
            if node.get("node_type") == "persona"
        ),
        "",
    )
    for contract in (document.get("branch_contracts") or {}).values():
        candidates.extend(
            field for field in contract.get("fields") or []
            if field.get("key") == key
            and (
                field.get("scope") == "persona"
                or str(field.get("owner_node_id") or "") == persona_node_id
            )
        )
    return any(
        graph_proof_checker_v3.fact_compatible(field, fact)
        for field in candidates
    )


_GREETING_FORMS = {
    "oi", "ola", "oie", "opa", "bom dia", "boa tarde", "boa noite",
    "e ai", "ei", "hello", "hey",
}


def _is_greeting(message: str) -> bool:
    """Recognize only the linguistic intent; response copy remains graph-owned."""
    normalized = _normalized_phrase(message)
    return normalized in _GREETING_FORMS


def _persona_node(document: dict[str, Any]) -> dict[str, Any]:
    return next(
        (node for node in document.get("nodes") or [] if node.get("node_type") == "persona"),
        {},
    )


def _greeting_policy(
    document: dict[str, Any], *, contract: dict[str, Any], facts: dict[str, Any],
) -> dict[str, Any] | None:
    persona = _persona_node(document)
    data = persona.get("data") or {}
    policy = data.get("conversation_policy") or {}
    response = str(
        (((policy.get("intents") or {}).get("greeting") or {}).get("response")) or ""
    ).strip()
    if not response:
        return None
    pending = graph_proof_checker_v3.pending_fields(contract, facts) if contract else []
    question_id = pending[0].get("question_node_id") if pending else None
    question = str(
        (((contract.get("questions") or {}).get(str(question_id or "")) or {}).get("text"))
        or ""
    ).strip()
    field_key = pending[0].get("key") if pending else None
    if not contract:
        appointment = data.get("appointment_policy") or {}
        required = [str(value) for value in appointment.get("required_fields") or [] if value]
        questions = appointment.get("field_questions") or {}
        field_key = next(
            (
                key for key in required
                if not graph_proof_checker_v3.field_resolved({}, facts.get(key))
            ),
            None,
        )
        question = str(questions.get(field_key) or "").strip() if field_key else ""
    return {
        "response": response,
        "question": question,
        "question_node_id": question_id,
        "asked_field_key": field_key,
        "missing_fields": [field.get("key") for field in pending]
        if pending else ([field_key] if field_key else []),
    }


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
    context_batch_started = time.perf_counter()
    try:
        batch = supabase_client.get_graph_turn_context_batch_v3(
            persona_id=str(persona["id"]), lead_ref=lead_ref, message_limit=8,
        )
    except Exception:
        # Rolling-deploy compatibility while migration 114 is being applied.
        batch = {}
    context_batch_ms = round((time.perf_counter() - context_batch_started) * 1000, 3)
    publication = batch.get("publication") or supabase_client.get_active_graph_publication(str(persona["id"]))
    if not publication:
        raise RuntimeError("active GraphRAG v3 publication not found")
    document = publication.get("document_json") or {}
    messages = batch.get("messages") or supabase_client.get_messages(str(lead_ref), limit=8) or []
    if message and not any(str(row.get("message_id") or row.get("external_message_id") or "") == str(message_id or "") for row in messages):
        messages.append({"message_id": message_id, "sender_type": "lead", "role": "user", "texto": message})
    ledger = batch.get("ledger") or None
    if ledger:
        ledger["facts_by_key"] = _facts_by_key(batch.get("facts") or [])
    ledger = ledger or supabase_client.get_conversation_ledger(str(persona["id"]), lead_ref) or {
        "active_branch_node_id": None, "publication_id": publication["id"],
        "graph_checksum": publication["checksum"], "revision": 0,
        "asked_question_node_ids": [], "facts": {}, "facts_by_key": {},
    }
    publication_changed = str(ledger.get("publication_id")) != str(publication["id"])
    active_branch = str(ledger.get("active_branch_node_id") or "") or None
    if active_branch not in set(document.get("branch_anchors") or []):
        active_branch = None
    # Only queried for a ledger that exists (a fresh conversation has no
    # multi-service state yet, so there is nothing to fetch). Filtered to
    # published anchors for the same reason active_branch is above -- a
    # stale row from a since-rolled-back publication must never leak in.
    batch_branches = [
        str(row.get("branch_anchor_node_id") or "")
        for row in batch.get("branches") or [] if row.get("state") == "active"
    ]
    persisted_active_branches = (
        [
            anchor for anchor in (
                batch_branches or supabase_client.get_active_ledger_branches(str(ledger.get("id") or ""))
            )
            if anchor in set(document.get("branch_anchors") or [])
        ]
        if ledger.get("id") else []
    )
    active_branches = list(dict.fromkeys([
        *([active_branch] if active_branch else []),
        *persisted_active_branches,
    ]))
    active_contract = (document.get("branch_contracts") or {}).get(active_branch) or {}
    facts_by_key = ledger.get("facts_by_key") or _facts_by_key(
        list((ledger.get("facts") or {}).values())
    )
    ledger["facts_by_key"] = facts_by_key
    ledger["facts"] = _facts_for_contract(active_contract, facts_by_key)
    invalidated_fact_keys: list[str] = []
    if publication_changed:
        previous_facts = ledger.get("facts") or {}
        ledger["facts"] = {
            key: value for key, value in previous_facts.items()
            if _publication_fact_is_compatible(
                document, active_contract, key, value,
            )
        }
        invalidated_fact_keys = sorted(set(previous_facts) - set(ledger["facts"]))
        ledger["asked_question_node_ids"] = []
        ledger["publication_id"] = publication["id"]
        ledger["graph_checksum"] = publication["checksum"]
    missing = [field["key"] for field in graph_proof_checker_v3.pending_fields(active_contract, ledger.get("facts") or {})]
    active_path = ((document.get("coordinates") or {}).get(active_branch) or {}).get("path_node_ids") or []
    # A short answer while a field is expected must not trigger fuzzy global
    # selection, but an exact published title/alias is authoritative even when
    # it is short (for example, "prefiro <servico>"). Resolve the literal
    # graph match first; only suppress semantic search when no exact match
    # exists.
    deterministic_candidates = _deterministic_branch_candidates(document, message)
    greeting = _greeting_policy(
        document, contract=active_contract, facts=ledger.get("facts") or {},
    ) if _is_greeting(message) and not deterministic_candidates else None
    if greeting:
        persona_node = _persona_node(document)
        reply = "\n\n".join(
            part for part in (greeting["response"], greeting["question"]) if part
        )
        trace = {
            "runtime_version": RUNTIME_VERSION,
            "publication_id": publication["id"],
            "publication_version": publication["version"],
            "graph_checksum": publication["checksum"],
            "ledger_revision": int(ledger.get("revision") or 0),
            "publication_changed": publication_changed,
            "invalidated_fact_keys": invalidated_fact_keys,
            "deterministic_intent": "greeting",
            "deterministic_reply": reply,
            "asked_field_key": greeting.get("asked_field_key"),
            "next_question_node_id": greeting.get("question_node_id"),
            "missing_fields": greeting.get("missing_fields") or [],
            "context_batch_ms": context_batch_ms,
            "embedding_ms": 0, "branch_rank_ms": 0, "branch_package_ms": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        return ConversationContext(
            persona_slug=persona_slug,
            agent_slug=str((persona.get("config") or {}).get("agent_slug") or "agent"),
            graph_version=int(publication["version"]), graph_checksum=publication["checksum"],
            messages=_project_recent_messages(messages),
            cart={**((lead.get("metadata") or {}).get("conversation_state") or {}),
                  "facts": ledger.get("facts") or {},
                  "facts_by_key": ledger.get("facts_by_key") or {},
                  "active_branch_node_id": active_branch,
                  "asked_question_node_ids": ledger.get("asked_question_node_ids") or [],
                  "_ledger_revision": ledger.get("revision") or 0},
            rag_nodes=[persona_node] if persona_node else [], rag_paths=[], rag_chunks=[],
            context_cards=[], system_prompt="", available_services=[],
            active_branch_node_id=active_branch, active_branch_node_ids=active_branches,
            active_path_checksum=((document.get("coordinates") or {}).get(active_branch) or {}).get("path_checksum"),
            branch_node_ids=active_contract.get("closure_node_ids") or [],
            graph_contract=active_contract, publication_id=publication["id"],
            runtime_version=RUNTIME_VERSION, retrieval_trace=trace,
            known_facts=_known_facts_payload(ledger.get("facts") or {}, message_id),
            time_since_last_client_message=_time_since_last_client_message(messages, message_id),
            pending_reconfirmation=bool((lead.get("metadata") or {}).get("pending_reconfirmation")),
        )
    embedding_started = time.perf_counter()
    embedding = None if deterministic_candidates else graph_compiler_v3.query_embeddings([message])[0]
    embedding_ms = round((time.perf_counter() - embedding_started) * 1000, 3)
    short_expected_answer = bool(
        active_branch
        and missing
        and len(message.split()) <= 8
        and not deterministic_candidates
    )
    branch_rank_started = time.perf_counter()
    candidates = deterministic_candidates or ([] if short_expected_answer else _candidate_branches(
        persona_id=str(persona["id"]), publication=publication, message=message,
        embedding=embedding, active_path=active_path, missing=missing,
    ))
    branch_rank_ms = round((time.perf_counter() - branch_rank_started) * 1000, 3)
    retrieval_branch = _retrieval_branch_for_turn(
        active_branch=active_branch,
        deterministic_candidates=deterministic_candidates,
        candidates=candidates,
        branch_anchors=document.get("branch_anchors") or [],
    )
    if not retrieval_branch:
        raise RuntimeError("GraphRAG publication has no resolvable branch")
    contract = (document.get("branch_contracts") or {}).get(retrieval_branch) or {}
    missing = [field["key"] for field in graph_proof_checker_v3.pending_fields(contract, ledger.get("facts") or {})]
    branch_package_started = time.perf_counter()
    rows = supabase_client.search_graph_rag_v3(
        persona_id=str(persona["id"]), publication_id=publication["id"],
        branch_node_id=retrieval_branch, query=message, query_embedding=embedding,
        active_path_node_ids=((document.get("coordinates") or {}).get(retrieval_branch) or {}).get("path_node_ids") or [],
        missing_fields=missing, limit=48,
    )
    required_nodes = _required_retrieval_node_ids(
        document, retrieval_branch, contract, missing,
    )
    branch_package = supabase_client.get_graph_branch_package_v3(
        publication_id=publication["id"], branch_node_id=retrieval_branch,
        chunk_ids=[str(row.get("chunk_id") or row.get("id")) for row in rows if row.get("chunk_id") or row.get("id")],
        node_ids=[str(node_id) for node_id in required_nodes if node_id],
        limit=RAG_CHUNK_LIMIT,
    )
    structural = branch_package.get("chunks") or []
    branch_package_ms = round((time.perf_counter() - branch_package_started) * 1000, 3)
    merged = {str(row.get("chunk_id") or row.get("id")): row for row in [*rows, *structural]}
    required_structural = _required_structural_chunks(structural)
    if len(required_structural) > RAG_CHUNK_LIMIT:
        raise RuntimeError(
            "required structural graph chunks exceed the 12-chunk prompt limit"
        )
    structural_ids = {
        str(row.get("chunk_id") or row.get("id")) for row in required_structural
    }
    selected = _mmr(
        [
            row for key, row in merged.items()
            if key not in structural_ids
        ],
        RAG_CHUNK_LIMIT - len(required_structural),
    )
    # Phase-A candidates are represented only by their compact snippets in the
    # retrieval trace. Full content enters the prompt solely from phase B.
    package = list({
        **{str(row.get("chunk_id") or row.get("id")): row for row in required_structural},
        **{str(row.get("chunk_id") or row.get("id")): row for row in selected},
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
        if item["branch_anchor_node_id"] != active_branch
        and item["score"] >= BRANCH_EVIDENCE_MIN_SCORE
    ]
    trace = {
        "runtime_version": RUNTIME_VERSION, "publication_id": publication["id"],
        "publication_version": publication["version"], "graph_checksum": publication["checksum"],
        "ledger_revision": int(ledger.get("revision") or 0),
        "publication_changed": publication_changed,
        "invalidated_fact_keys": invalidated_fact_keys,
        "short_expected_answer": short_expected_answer,
        "global_branch_search_executed": not short_expected_answer,
        "deterministic_branch_match": bool(deterministic_candidates),
        "deterministic_branch_resolution": (
            deterministic_candidates[0] if len(deterministic_candidates) == 1 else None
        ),
        "retrieval_branch_node_id": retrieval_branch,
        "branch_candidates": _evidenced_branch_candidates(candidates),
        "possible_switches": possible_switches,
        "context_batch_ms": context_batch_ms,
        "embedding_ms": embedding_ms,
        "branch_rank_ms": branch_rank_ms,
        "branch_package_ms": branch_package_ms,
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
        "cite evidence_span literal e retorne exclusivamente o JSON Schema fornecido.\n\n"

        "Leia a mensagem inteira do cliente antes de responder. Capture em "
        "extracted_facts todo campo reconhecível mencionado nela, mesmo que não seja "
        "o campo que você acabou de perguntar -- um cliente frequentemente responde "
        "algo diferente do que foi pedido, ou adianta mais de uma informação na "
        "mesma mensagem.\n\n"

        "Você é um SDR de verdade conversando por WhatsApp, não um formulário. "
        "Sempre que extrair um campo diferente do que você estava perguntando, "
        "reconheça esse dado com suas próprias palavras antes de retomar a "
        "pergunta pendente -- como uma pessoa faria ao perceber que o cliente já "
        "respondeu algo que ela ainda nem tinha perguntado. Nunca ignore "
        "silenciosamente um dado que o cliente acabou de dar. Mas nunca recorra "
        "à mesma palavra ou fórmula de reconhecimento em toda mensagem (nunca "
        "sempre a mesma expressão, tipo sempre começar ou terminar com a mesma "
        "palavrinha) -- isso soa repetitivo e robótico. Reconheça de um jeito "
        "diferente a cada vez, exatamente como uma pessoa varia a forma de dizer "
        "que entendeu numa conversa real -- às vezes só emenda a próxima "
        "pergunta sem nenhuma palavra de reconhecimento isolada, às vezes "
        "comenta algo específico sobre o que foi dito. Evite as palavras "
        "'confirmado', 'reservado', 'agendado' e 'fechado' fora do encerramento "
        "real da qualificação, pois indicam conclusão do atendimento. Só "
        "reconheça um dado que realmente esteja em extracted_facts deste turno "
        "ou já conhecido em factual_ledger -- nunca finja ter entendido algo que "
        "não foi de fato extraído.\n\n"

        "Nunca repita a pergunta ou frase do turno anterior quase palavra por "
        "palavra, e nunca repita a mesma construção de frase turno após turno. "
        "Confira recent_messages (as últimas mensagens da conversa, incluindo "
        "suas próprias respostas) antes de escrever a reply e varie a "
        "formulação a cada turno, mesmo quando a pergunta de fundo "
        "(next_question_node_id) continuar a mesma. Peça no máximo uma "
        "informação pendente por mensagem, salvo duas informações muito "
        "relacionadas.\n\n"

        "handoff_requested só pode ser true quando TODOS os campos "
        "obrigatórios do galho atual já estão em factual_ledger (nenhum "
        "campo pendente restante) -- nunca proponha handoff assim que colher "
        "só o primeiro campo (por exemplo, o nome) se o galho ainda exigir "
        "outros campos depois dele (por exemplo, o relato de uma "
        "reclamação). Depois de colher um campo, a próxima ação é sempre "
        "perguntar o próximo campo pendente do galho -- nunca encerrar o "
        "turno oferecendo encaminhamento antes disso.\n\n"

        "tempo_desde_ultima_mensagem indica quanto tempo se passou desde a "
        "última mensagem do cliente. Se for mais de ~1 hora, trate a nova "
        "mensagem como o início de uma conversa nova, não como continuação "
        "direta -- não assuma que o assunto ou a urgência de antes ainda "
        "valem, especialmente se o assunto mudou (ex.: uma reclamação depois "
        "de um agendamento já concluído).\n\n"

        "fatos_conhecidos lista tudo que já se sabe sobre esse cliente, cada "
        "um com origem 'esta_conversa' (extraído agora) ou 'anterior' "
        "(já registrado de antes). Você pode usar um fato 'anterior' para "
        "personalizar a conversa (ex.: perguntar se uma reclamação tem a ver "
        "com o serviço que ele já fez), mas sempre confirme esse fato com o "
        "cliente antes de seguir em frente com base nele -- nunca assuma "
        "silenciosamente que uma informação antiga ainda vale (o veículo "
        "pode ter mudado, o interesse pode ser outro). Isso vale ainda mais "
        "quando reconfirmacao_pendente for true (a IA acabou de ser "
        "reativada por um humano): a primeira resposta deve confirmar "
        "explicitamente os dados relevantes já conhecidos antes de "
        "prosseguir."
    )
    return ConversationContext(
        persona_slug=persona_slug, agent_slug=str((persona.get("config") or {}).get("agent_slug") or "agent"),
        graph_version=int(publication["version"]), graph_checksum=publication["checksum"],
        messages=_project_recent_messages(messages), cart={**((lead.get("metadata") or {}).get("conversation_state") or {}),
                                      "facts": ledger.get("facts") or {},
                                      "facts_by_key": ledger.get("facts_by_key") or {},
                                      "active_branch_node_id": active_branch,
                                      "asked_question_node_ids": ledger.get("asked_question_node_ids") or [],
                                      "_ledger_revision": ledger.get("revision") or 0},
        rag_nodes=[document["node_by_id"][node_id] for node_id in by_source if node_id in document["node_by_id"]],
        rag_paths=[card.path for card in cards],
        rag_chunks=[_compact_prompt_chunk(row) for row in package],
        context_cards=cards,
        system_prompt=prompt, available_services=[{
            "slug": document["node_by_id"][anchor]["slug"], "label": document["node_by_id"][anchor]["title"]
        } for anchor in document.get("branch_anchors") or []],
        active_branch_node_id=active_branch,
        active_branch_node_ids=active_branches,
        active_path_checksum=((document.get("coordinates") or {}).get(active_branch) or {}).get("path_checksum"),
        branch_node_ids=contract.get("closure_node_ids") or [], graph_contract=contract,
        publication_id=publication["id"], runtime_version=RUNTIME_VERSION, retrieval_trace=trace,
        known_facts=_known_facts_payload(ledger.get("facts") or {}, message_id),
        time_since_last_client_message=_time_since_last_client_message(messages, message_id),
        pending_reconfirmation=bool((lead.get("metadata") or {}).get("pending_reconfirmation")),
    )


def decide(
    context: ConversationContext, *, model_observation: dict[str, Any] | None
) -> tuple[ConversationDecision, AgentResponse]:
    decision, response = _decide(context, model_observation=model_observation)
    token_usage = (model_observation or {}).get("token_usage")
    if token_usage:
        response = response.model_copy(update={"token_usage": token_usage})
    return decision, response


def _decide(
    context: ConversationContext, *, model_observation: dict[str, Any] | None
) -> tuple[ConversationDecision, AgentResponse]:
    observation = model_observation or {}
    if context.retrieval_trace.get("deterministic_intent") == "greeting":
        question_id = context.retrieval_trace.get("next_question_node_id")
        asked = list(context.cart.get("asked_question_node_ids") or [])
        if question_id and question_id not in asked:
            asked.append(question_id)
        state = {
            **context.cart,
            "asked_question_node_ids": asked,
            "active_branch_node_id": context.active_branch_node_id,
            "active_branch_node_ids": list(context.active_branch_node_ids),
        }
        proof = {
            "valid": True,
            "errors": [],
            "mode": "deterministic_greeting",
            "accepted_facts": [],
            "missing_fields": context.retrieval_trace.get("missing_fields") or [],
            "asked_field_key": context.retrieval_trace.get("asked_field_key"),
            "model_calls": 0,
        }
        return (
            ConversationDecision(
                classifier="graph_intent_v3", intent="greeting",
                route=ConversationRoute.SDR, confidence=1,
                lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                evidence_node_ids=[question_id] if question_id else [],
            ),
            AgentResponse(
                reply_text=str(context.retrieval_trace.get("deterministic_reply") or "") or None,
                role=ConversationRoute.SDR,
                evidence_node_ids=[question_id] if question_id else [],
                cart_state=state, handoff_required=False, proof=proof,
                token_usage={"model_calls": 0, "repair_calls": 0, "prompt_tokens": 0,
                             "completion_tokens": 0, "total_tokens": 0},
            ),
        )
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
    proposal = _apply_authoritative_branch_resolution(proposal, context, document)
    contract = (document.get("branch_contracts") or {}).get(proposal.branch_anchor_node_id) or {}
    grouped_facts = context.cart.get("facts_by_key") or {}
    contract_facts = (
        _facts_for_contract(contract, grouped_facts)
        if grouped_facts else context.cart.get("facts") or {}
    )
    proposal = _normalize_servico_owner(proposal, contract)
    proposal = _normalize_premature_servico_requestion(proposal, contract, contract_facts)
    proposal = _normalize_stale_next_question_after_branch_change(proposal, contract, contract_facts)
    proposal = _normalize_next_question_to_first_missing(
        proposal, contract, contract_facts,
    )
    chunk_sources = {
        str(row.get("chunk_id") or row.get("id")): str(
            row.get("source_node_id") or row.get("source_graph_node_id") or ""
        )
        for row in context.rag_chunks
    } | {
        str(chunk_id): str(source_id)
        for chunk_id, source_id in (observation.get("repair_context_chunk_sources") or {}).items()
    }
    if (
        proposal.branch_action.value == "switch"
        and context.active_branch_node_id
        and context.active_branch_node_id != proposal.branch_anchor_node_id
    ):
        previous_contract = (document.get("branch_contracts") or {}).get(context.active_branch_node_id) or {}
        proposal = _drop_stale_branch_citations(
            proposal,
            previous_branch_closure=set(previous_contract.get("closure_node_ids") or []),
            chunk_sources=chunk_sources,
        )
    ledger = {
        "active_branch_node_id": context.active_branch_node_id,
        "publication_id": context.publication_id, "graph_checksum": context.graph_checksum,
        "revision": context.retrieval_trace.get("ledger_revision", 0),
        "facts": contract_facts,
        "asked_question_node_ids": context.cart.get("asked_question_node_ids") or [],
    }
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract, ledger=ledger,
        proposal=proposal.model_dump(mode="json"), message=next(
            (str(row.get("content") or row.get("texto") or row.get("message") or "") for row in reversed(context.messages)
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
        package_chunk_sources=chunk_sources,
        active_branch_node_ids=context.active_branch_node_ids or (
            [context.active_branch_node_id] if context.active_branch_node_id else []
        ),
    )
    # An explicit switch/add is only a Phase-A decision on the first pass.
    # Force one directed Phase-B retrieval for the selected branch before
    # any reply or fact can be committed, even if an anchor snippet
    # happened to suffice.
    if (
        int(observation.get("repair_attempt") or 0) == 0
        and proposal.branch_action.value in {"select", "switch", "add"}
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
        logger.warning(
            "graph proof repair triggered persona=%s lead_stage=%s branch=%s errors=%s",
            context.persona_slug, context.cart.get("_lead_stage"),
            proposal.branch_anchor_node_id, proof.get("errors"),
        )
        proof["repair_contract"] = contract
        rows = supabase_client.get_graph_rag_repair_chunks(
            publication_id=publication["id"], branch_node_id=proposal.branch_anchor_node_id,
            requirements=proof["repair_requirements"],
        )
        repair_chunks = _repair_chunks(rows, proof["repair_requirements"])
        if len(repair_chunks) > RAG_CHUNK_LIMIT:
            raise RuntimeError(
                "required graph repair package exceeds the 12-chunk prompt limit"
            )
        rows = repair_chunks
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
    discovery_only = (
        not proof["valid"]
        and context.active_branch_node_id is None
        and proposal.branch_action.value == "keep"
        and proof.get("errors") == ["keep_without_active_branch"]
        and not context.retrieval_trace.get("branch_candidates")
    )
    if proof["valid"] or discovery_only:
        if discovery_only:
            proof = {
                **proof,
                "valid": True,
                "errors": [],
                "mode": "discovery",
                "branch_committed": False,
            }
        accepted_facts = list(proof.get("accepted_facts") or [])
        next_grouped = {
            str(key): list(values) for key, values in grouped_facts.items()
        }
        for fact in accepted_facts:
            key = str(fact.get("field_key") or "")
            owner = str(fact.get("owner_node_id") or "")
            next_grouped[key] = [
                current for current in next_grouped.get(key, [])
                if str(current.get("owner_node_id") or "") != owner
            ] + [fact]

        active_branch_ids = list(dict.fromkeys([
            *([context.active_branch_node_id] if context.active_branch_node_id else []),
            *context.active_branch_node_ids,
        ]))
        if not discovery_only:
            action = proposal.branch_action.value
            anchor = proposal.branch_anchor_node_id
            if action == "select":
                active_branch_ids = [anchor]
            elif action == "add" and anchor not in active_branch_ids:
                active_branch_ids.append(anchor)
            elif action == "switch":
                active_branch_ids = [
                    item for item in active_branch_ids
                    if item != context.active_branch_node_id
                ]
                if anchor not in active_branch_ids:
                    active_branch_ids.append(anchor)
        committed_branch = (
            context.active_branch_node_id
            if discovery_only else proposal.branch_anchor_node_id
        )

        aggregate_missing = graph_proof_checker_v3.aggregate_missing_fields(
            document.get("branch_contracts") or {}, active_branch_ids, next_grouped,
        ) if active_branch_ids else []
        next_question_id = next(
            (field.get("question_node_id") for field in aggregate_missing if field.get("question_node_id")),
            None,
        )
        question_contract = next(
            (
                candidate for candidate in (document.get("branch_contracts") or {}).values()
                if next_question_id in (candidate.get("questions") or {})
            ),
            contract,
        )
        reply_seed = proposal.reply
        if (
            not accepted_facts
            and next_question_id
            and not context.retrieval_trace.get("deterministic_branch_resolution")
            and len(_latest_user_message(context).split()) <= 3
        ):
            reply_seed = ""
        reply = graph_proof_checker_v3.compose_published_question(
            reply=reply_seed,
            next_question_node_id=next_question_id,
            contract=question_contract,
        )
        if _repeats_recent_outbound(reply, context.messages):
            raise RuntimeError("semantic reply repetition blocked by recent outbound proof")

        facts = _facts_for_contract(
            (document.get("branch_contracts") or {}).get(committed_branch) or {},
            next_grouped,
        )
        state = {**context.cart, "facts": facts, "facts_by_key": next_grouped,
                 "active_branch_node_id": committed_branch,
                 "active_branch_node_ids": active_branch_ids,
                 "asked_question_node_ids": list(dict.fromkeys([
                      *(context.cart.get("asked_question_node_ids") or []),
                      *([next_question_id] if next_question_id else []),
                  ]))}
        qualification_complete = not aggregate_missing and not discovery_only
        route = (
            ConversationRoute.HUMAN
            if proposal.handoff_requested and qualification_complete
            else ConversationRoute.SDR
        )
        proof = {
            **proof,
            "missing_fields": [field.get("key") for field in aggregate_missing],
            "aggregate_missing_fields": aggregate_missing,
            "next_question_node_id": next_question_id,
            "asked_field_key": next(
                (field.get("key") for field in aggregate_missing
                 if field.get("question_node_id") == next_question_id),
                None,
            ),
            "qualification_complete": qualification_complete,
            "accepted_facts": accepted_facts,
        }
        return (
            ConversationDecision(classifier="graph_proof_checker_v3",
                                 intent="qualification_complete" if qualification_complete else "collect_graph_fields",
                                 route=route, confidence=1, lead_stage="qualificado" if qualification_complete else "engajado",
                                 handoff_reason="graph_handoff_rule" if proposal.handoff_requested else None,
                                 evidence_node_ids=proposal.cited_node_ids),
            AgentResponse(reply_text=reply, role=route, evidence_node_ids=proposal.cited_node_ids,
                          cart_state=state,
                          handoff_required=proposal.handoff_requested and qualification_complete,
                          proposal=proposal, proof=proof),
        )
    # A technical failure emits only the next published question.  It never
    # fabricates commercial copy and never requests handoff by itself.
    fallback_id = next((field.get("question_node_id") for field in contract.get("fields") or []
                        if field["key"] in proof.get("missing_fields") or []), None)
    closing_text = ""
    if not fallback_id:
        # Confirmed live 2026-08-09: when the rejected proposal's own
        # completion/handoff signal was the only problem (no field actually
        # missing), fallback_id is None and compose_published_question(reply="",
        # next_question_node_id=None, ...) returns an empty string -- and
        # commit() only ever sends a non-empty reply_text, so the customer's
        # message that completes qualification got silently no response at
        # all. The branch's own published closing text (the same text a
        # normal handoff turn would use) is exactly what belongs here
        # instead of empty, and only applies when nothing is left to ask.
        facts = (proof.get("ledger") or {}).get("facts") or {}
        closing_rule = next(
            (
                rule for rule in contract.get("handoff_rules") or []
                if rule.get("text")
                and graph_proof_checker_v3.handoff_rule_matches(
                    rule, facts=facts, qualification_complete=True,
                )
            ),
            None,
        )
        closing_text = str((closing_rule or {}).get("text") or "")
    fallback = graph_proof_checker_v3.compose_published_question(
        reply=closing_text, next_question_node_id=fallback_id, contract=contract
    )
    deterministic_fallback_valid = bool(fallback_id or closing_text)
    fallback_proof = {
        **proof,
        "valid": deterministic_fallback_valid,
        "errors": [] if deterministic_fallback_valid else proof.get("errors") or [],
        "model_proposal_errors": proof.get("errors") or [],
        "mode": "published_fallback",
        "repair_required": False,
        "fallback_used": True,
    }
    fallback_facts = dict(context.cart.get("facts") or {})
    for fact in proof.get("accepted_facts") or []:
        fallback_facts[str(fact.get("field_key") or "")] = fact
    proposal_errors = [str(error) for error in proof.get("errors") or []]
    branch_safe = not any(
        error.startswith((
            "branch_", "keep_", "add_", "publication_", "fact_", "field_owner_",
        ))
        or error in {"branch_not_published", "branch_path_checksum_mismatch"}
        for error in proposal_errors
    )
    fallback_branch = context.active_branch_node_id
    if branch_safe and proposal.branch_action.value in {"select", "switch", "keep", "add"}:
        fallback_branch = proposal.branch_anchor_node_id
    fallback_active_branches = list(context.active_branch_node_ids)
    if proposal.branch_action.value == "add" and branch_safe and proposal.branch_anchor_node_id not in fallback_active_branches:
        fallback_active_branches.append(proposal.branch_anchor_node_id)
    fallback_state = {
        **context.cart,
        "facts": fallback_facts,
        "active_branch_node_id": fallback_branch,
        "active_branch_node_ids": fallback_active_branches,
        "asked_question_node_ids": list(dict.fromkeys([
            *(context.cart.get("asked_question_node_ids") or []),
            *([fallback_id] if fallback_id else []),
        ])),
    }
    return (
        ConversationDecision(classifier="graph_proof_checker_v3", intent="published_fallback",
                             route=ConversationRoute.SDR, confidence=0,
                             lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                             evidence_node_ids=[fallback_id] if fallback_id else []),
        AgentResponse(reply_text=fallback or None, role=ConversationRoute.SDR,
                      evidence_node_ids=[fallback_id] if fallback_id else [], cart_state=fallback_state,
                      handoff_required=False, proposal=proposal, proof=fallback_proof),
    )

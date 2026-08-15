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
MAX_PENDING_QUESTION_ATTEMPTS = 1
FAQ_SEMANTIC_MIN_SCORE = 0.18
FAQ_SEMANTIC_MIN_MARGIN = 0.03


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
    pending = graph_proof_checker_v3.askable_pending_fields(contract, ledger_facts)
    substitute = next((field.get("question_node_id") for field in pending if field.get("question_node_id")), None)
    if not substitute or substitute == proposal.next_question_node_id:
        return proposal
    return proposal.model_copy(update={"next_question_node_id": substitute})


def _normalize_stale_next_question_after_branch_change(
    proposal: ConversationProposal, contract: dict[str, Any], ledger_facts: dict[str, Any],
) -> ConversationProposal:
    """Repoint a next_question_node_id that doesn't fit the branch just selected.

    Confirmed live 2026-08-09: right when the model proposes
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
    pending = graph_proof_checker_v3.askable_pending_fields(contract, effective_facts)
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
    pending = graph_proof_checker_v3.askable_pending_fields(contract, facts)
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


def _overlay_canonical_inbound(
    messages: list[dict[str, Any]], message: str, message_id: str | None,
) -> list[dict[str, Any]]:
    """Use the claimed burst text for the current turn's proof package."""
    if not message:
        return messages
    current_identity = str(message_id or "")
    matched = False
    projected: list[dict[str, Any]] = []
    for row in messages:
        row_identity = str(row.get("message_id") or row.get("external_message_id") or "")
        if current_identity and row_identity == current_identity:
            row = {**row, "content": message, "texto": message}
            matched = True
        projected.append(row)
    if not matched:
        projected.append({
            "message_id": message_id,
            "sender_type": "lead",
            "role": "user",
            "texto": message,
        })
    return projected


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
    for key, stored in (facts or {}).items():
        values = stored if isinstance(stored, list) else [stored]
        for fact in values:
            if not isinstance(fact, dict) or fact.get("status") != "known":
                continue
            source_id = str(fact.get("source_message_id") or "")
            origem = (
                "esta_conversa"
                if current_message_id and source_id == str(current_message_id)
                else "anterior"
            )
            payload.append({
                "chave": key,
                "valor": fact.get("value", fact.get("value_json")),
                "owner_node_id": fact.get("owner_node_id"),
                "origem": origem,
            })
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


def _interrogative_clause(message: str) -> str:
    """Isolate the customer's doubt from a compound qualification answer."""
    raw = str(message or "").strip()
    if not raw:
        return ""
    clauses = [
        part.strip(" \t\r\n,;:-")
        for part in re.split(r"(?<=[.!?…])\s+|[\r\n]+", raw)
        if part.strip(" \t\r\n,;:-")
    ]
    questions = [part for part in clauses if _looks_like_customer_question(part)]
    if questions:
        return questions[-1]
    normalized = _normalized_phrase(raw)
    prefixes = (
        "como ", "quando ", "onde ", "qual ", "quais ", "quanto ",
        "por que ", "porque ", "posso ", "podem ", "poderia ",
        "voces ", "tem como ", "gostaria de saber ", "queria saber ",
        "sera que ",
    )
    positions = [normalized.rfind(prefix) for prefix in prefixes]
    start = max(positions, default=-1)
    if start > 0:
        # Use the original suffix only as a best-effort fallback; normalized
        # text is reserved for comparison and is never shown to the customer.
        words_before = len(normalized[:start].split())
        return " ".join(raw.split()[words_before:]).strip()
    return raw if _looks_like_customer_question(raw) else ""


def _select_faq_candidate(
    interrogative_clause: str, rows: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
    """Select an exact FAQ or a safely separated semantic winner."""
    normalized_query = _normalized_phrase(interrogative_clause)
    candidates: list[dict[str, Any]] = []
    exact_by_node: dict[str, dict[str, Any]] = {}
    for row in rows:
        aliases = row.get("aliases") or []
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except (TypeError, ValueError):
                aliases = []
        phrases = [row.get("question"), *(aliases if isinstance(aliases, list) else [])]
        exact = bool(normalized_query) and normalized_query in {
            _normalized_phrase(value) for value in phrases if value
        }
        candidate = {
            "faq_node_id": str(row.get("faq_node_id") or row.get("source_node_id") or ""),
            "chunk_id": str(row.get("chunk_id") or row.get("id") or ""),
            "question": str(row.get("question") or ""),
            "semantic_score": round(float(row.get("semantic_score") or 0), 6),
            "lexical_score": round(float(row.get("lexical_score") or 0), 6),
            "exact": exact,
        }
        candidates.append(candidate)
        if exact and candidate["faq_node_id"]:
            exact_by_node[candidate["faq_node_id"]] = row
    if len(exact_by_node) == 1:
        return next(iter(exact_by_node.values())), "exact_normalized", candidates
    if len(exact_by_node) > 1:
        return None, "ambiguous_exact", candidates

    ranked = sorted(
        rows,
        key=lambda row: (
            -float(row.get("semantic_score") or 0),
            str(row.get("faq_node_id") or row.get("source_node_id") or ""),
        ),
    )
    if not ranked:
        return None, "no_candidates", candidates
    top = float(ranked[0].get("semantic_score") or 0)
    second = float(ranked[1].get("semantic_score") or 0) if len(ranked) > 1 else 0.0
    if top < FAQ_SEMANTIC_MIN_SCORE:
        return None, "semantic_below_threshold", candidates
    if top - second < FAQ_SEMANTIC_MIN_MARGIN:
        return None, "semantic_ambiguous_margin", candidates
    return ranked[0], "semantic_margin", candidates


_ADDITIVE_SERVICE_MARKER = re.compile(
    r"\b(?:tamb[eé]m|al[eé]m(?:\s+de)?|junto(?:s|\s+com)?|adiciona(?:r|ndo)?|"
    r"incluir|inclui(?:r|ndo)?|mais\s+um|also|too)\b",
    re.IGNORECASE,
)

_SERVICE_CHANGE_MARKER = re.compile(
    r"\b(?:na\s+verdade|corrig\w*|retific\w*|prefir\w*|troca\w*|mud\w*|"
    r"em\s+vez|ao\s+inv[eé]s|quero\s+agora|vamos\s+de)\b",
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


def _message_explicitly_changes_service(message: str) -> bool:
    return bool(
        _message_requests_additional_service(message)
        or _SERVICE_CHANGE_MARKER.search(message or "")
    )


def _is_direct_answer_to_pending_non_service_field(
    *,
    message: str,
    contract: dict[str, Any],
    missing_fields: list[str],
    asked_question_node_ids: list[str],
) -> bool:
    """Keep service words inside a field answer from changing branch focus.

    A customer can describe a vehicle condition with phrases such as
    "the paint lost its shine" while the focused service is another active
    branch.  That is evidence for the pending field, not a service-selection
    command.  Explicit add/switch language remains authoritative.
    """
    if (
        not missing_fields
        or not asked_question_node_ids
        or _looks_like_customer_question(message)
        or _message_explicitly_changes_service(message)
    ):
        return False
    first_missing = str(missing_fields[0] or "")
    if not first_missing or first_missing == "servico":
        return False
    field = next(
        (
            row for row in contract.get("fields") or []
            if str(row.get("key") or "") == first_missing
        ),
        None,
    )
    if not field:
        return False
    expected_question = str(field.get("question_node_id") or "")
    return bool(
        expected_question
        and str(asked_question_node_ids[-1] or "") == expected_question
    )


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
                "match_length": len(matched[0]),
            })
    if len(matches) <= 1:
        return matches
    # More than one anchor's title/slug/alias literally appears in the
    # message -- this happens whenever a generic alias (e.g. "polimento")
    # is a substring of a more specific one ("polimento de vidros"). Prefer
    # the single strictly-more-specific (longer) match instead of discarding
    # every candidate; only a genuine tie falls through to semantic search.
    matches.sort(key=lambda item: item["match_length"], reverse=True)
    if matches[0]["match_length"] > matches[1]["match_length"]:
        return [matches[0]]
    return []


def _previously_mentioned_service_titles(
    document: dict[str, Any], messages: list[dict[str, Any]],
) -> list[str]:
    """Service titles the agent already pitched earlier in this conversation.

    Computed from the same recent-history window already loaded for every
    turn (`messages`) -- no new persisted state. Used only to tell the model
    what not to re-introduce as if it were new; it never blocks a reply.
    """
    node_by_id = document.get("node_by_id") or {}
    agent_texts = [
        _normalized_phrase(str(row.get("content") or row.get("texto") or row.get("text") or ""))
        for row in messages if _is_agent_message(row)
    ]
    titles: list[str] = []
    for anchor in document.get("branch_anchors") or []:
        node = node_by_id.get(anchor) or {}
        phrase = _normalized_phrase(node.get("title"))
        if not phrase or len(phrase) < 3:
            continue
        padded = f" {phrase} "
        if any(padded in f" {text} " for text in agent_texts):
            titles.append(str(node.get("title")))
    return titles


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
    pending = graph_proof_checker_v3.askable_pending_fields(contract, effective_facts)
    expected = pending[0].get("question_node_id") if pending else None
    if proposal.next_question_node_id == expected:
        return proposal
    return proposal.model_copy(update={"next_question_node_id": expected})


def _coerce_direct_field_value(message: str, schema: dict[str, Any]) -> Any:
    """Conservatively coerce a literal reply for one graph-declared field."""
    literal = str(message or "").strip()
    if not literal:
        return None
    candidates = schema.get("anyOf") or [schema]
    for candidate in candidates:
        expected = candidate.get("type")
        value: Any = None
        if expected == "string" or not expected:
            value = literal
            enum = candidate.get("enum") or []
            if enum:
                folded = _normalized_phrase(literal)
                value = next(
                    (item for item in enum if _normalized_phrase(item) == folded),
                    None,
                )
        elif expected in {"integer", "number"} and re.fullmatch(
            r"[-+]?\d+(?:[.,]\d+)?", literal,
        ):
            parsed = float(literal.replace(",", "."))
            value = int(parsed) if expected == "integer" and parsed.is_integer() else parsed
        elif expected == "boolean":
            folded = _normalized_phrase(literal)
            if folded in {"sim", "yes", "verdadeiro"}:
                value = True
            elif folded in {"nao", "no", "falso"}:
                value = False
        if value is not None and graph_proof_checker_v3._schema_error(candidate, value) is None:
            return value
    return None


def _looks_like_customer_question(message: str) -> bool:
    normalized = _normalized_phrase(message)
    if "?" in str(message or ""):
        return True
    question_prefixes = (
        "como ", "quando ", "onde ", "qual ", "quais ", "quanto ",
        "por que ", "porque ", "posso ", "podem ", "poderia ",
        "voces oferecem ", "voces fazem ", "voces tem ", "tem como ",
        "gostaria de saber ", "queria saber ", "sera que ",
    )
    return normalized.startswith(question_prefixes)


def _factual_answer_only(value: Any) -> str:
    """Remove qualification questions embedded in legacy FAQ answers."""
    return " ".join(
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", str(value or ""))
        if sentence.strip() and "?" not in sentence
    ).strip()


def _doubt_resolution(
    *, context: ConversationContext, document: dict[str, Any],
    proposal: ConversationProposal, contract: dict[str, Any],
    chunk_sources: dict[str, str], package_node_ids: set[str],
) -> dict[str, Any] | None:
    message = _latest_user_message(context)
    closure = set(contract.get("closure_node_ids") or [])
    selected_faq_node_id = str(
        context.retrieval_trace.get("selected_faq_node_id") or ""
    )
    selected_faq_chunk_id = str(
        context.retrieval_trace.get("selected_faq_chunk_id") or ""
    )
    deterministic_faq_trace = "faq_selection_method" in context.retrieval_trace
    cited = [selected_faq_node_id] if selected_faq_node_id else []
    if not deterministic_faq_trace:
        cited.extend(proposal.cited_node_ids)
        cited.extend(
            chunk_sources.get(chunk_id, "") for chunk_id in proposal.cited_chunk_ids
        )
    factual_faqs: list[dict[str, Any]] = []
    for node_id in dict.fromkeys(value for value in cited if value):
        node = (document.get("node_by_id") or {}).get(node_id) or {}
        data = node.get("data") or {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        claims = data.get("claims")
        if (
            node.get("node_type") == "faq"
            and node_id in closure
            and node_id in package_node_ids
            and (metadata.get("role") or data.get("role")) != "qualification_question"
            and str(data.get("answer") or "").strip()
            and isinstance(claims, list)
            and any(
                isinstance(claim, dict)
                and claim.get("policy")
                and [str(value) for value in claim.get("evidence_node_ids") or []] == [node_id]
                for claim in claims
            )
        ):
            factual_faqs.append(node)
    detected = bool(
        context.retrieval_trace.get("interrogative_clause")
        or _looks_like_customer_question(message)
        or proposal.claims
        or factual_faqs
    )
    if not detected:
        return None
    persona = _persona_node(document)
    conversation_policy = ((persona.get("data") or {}).get("conversation_policy") or {})
    doubt_policy = conversation_policy.get("doubt_handling")
    if not isinstance(doubt_policy, dict):
        raise RuntimeError("published appointment graph missing conversation_policy.doubt_handling")
    if factual_faqs:
        faq = factual_faqs[0]
        answer = _factual_answer_only((faq.get("data") or {}).get("answer"))
        if answer:
            used_chunks = (
                [selected_faq_chunk_id] if selected_faq_chunk_id
                else [
                    chunk_id for chunk_id, source_id in chunk_sources.items()
                    if source_id == faq.get("id")
                ]
            )
            if not used_chunks or any(
                chunk_sources.get(chunk_id) != faq.get("id") for chunk_id in used_chunks
            ):
                raise RuntimeError("selected FAQ evidence is outside the proof package")
            return {
                "customer_doubt_detected": True,
                "doubt_resolution": "answered",
                "text": answer,
                "faq_node_id": faq.get("id"),
                "doubt_node_ids": [faq.get("id")],
                "doubt_chunk_ids": used_chunks,
                "interrogative_clause": context.retrieval_trace.get("interrogative_clause"),
                "faq_candidates": context.retrieval_trace.get("faq_candidates") or [],
                "faq_selection_method": context.retrieval_trace.get("faq_selection_method"),
            }
    deferred = str(doubt_policy.get("deferred_response") or "").strip()
    if not deferred:
        raise RuntimeError("published appointment graph missing doubt deferral text")
    return {
        "customer_doubt_detected": True,
        "doubt_resolution": "deferred",
        "text": deferred,
        "faq_node_id": None,
        "doubt_node_ids": [],
        "doubt_chunk_ids": [],
        "interrogative_clause": context.retrieval_trace.get("interrogative_clause"),
        "faq_candidates": context.retrieval_trace.get("faq_candidates") or [],
        "faq_selection_method": context.retrieval_trace.get("faq_selection_method"),
        "faq_deferral_reason": context.retrieval_trace.get("faq_deferral_reason") or "no_safe_match",
    }


def _reconcile_direct_answer_to_pending_field(
    proposal: ConversationProposal,
    context: ConversationContext,
    contract: dict[str, Any],
    ledger_facts: dict[str, Any],
) -> ConversationProposal:
    """Persist a valid literal answer to the last published graph question.

    The model remains useful for extraction, but omission cannot make the
    runtime loop when the database proves exactly which field was asked.
    """
    if proposal.branch_action.value != "keep" or proposal.claims:
        return proposal
    message = _latest_user_message(context).strip()
    if not message or _looks_like_customer_question(message):
        return proposal
    pending = graph_proof_checker_v3.askable_pending_fields(contract, ledger_facts)
    if not pending:
        return proposal
    field = pending[0]
    question_id = str(field.get("question_node_id") or "")
    asked = [str(value) for value in context.cart.get("asked_question_node_ids") or []]
    if not question_id or not asked or asked[-1] != question_id:
        return proposal
    key = str(field.get("key") or "")
    if not key or any(fact.field_key == key for fact in proposal.extracted_facts):
        return proposal
    value = _coerce_direct_field_value(message, field.get("value_schema") or {})
    if value is None:
        return proposal
    fact = ExtractedFact(
        field_key=key,
        value=value,
        status="known",
        source_message_id=_source_message_id(context.messages),
        owner_node_id=str(field.get("owner_node_id") or ""),
        evidence_span=message,
        confidence=1.0,
    )
    return proposal.model_copy(update={
        "extracted_facts": [*proposal.extracted_facts, fact],
    })


def _unanswered_fact_after_question_limit(
    *,
    context: ConversationContext,
    contract: dict[str, Any],
    ledger_facts: dict[str, Any],
    proposal: ConversationProposal,
) -> dict[str, Any] | None:
    """Mark an unanswered field unknown after two published attempts."""
    pending = graph_proof_checker_v3.askable_pending_fields(contract, ledger_facts)
    if not pending:
        return None
    field = pending[0]
    key = str(field.get("key") or "")
    owner = str(field.get("owner_node_id") or "")
    question_id = str(field.get("question_node_id") or "")
    if not key or not owner or not question_id:
        return None
    accepted_statuses = set(field.get("accepted_statuses") or ["known"])
    if any(
        fact.field_key == key
        and fact.owner_node_id == owner
        and str(fact.status.value if hasattr(fact.status, "value") else fact.status)
        in accepted_statuses
        for fact in proposal.extracted_facts
    ):
        return None
    asked = [str(value) for value in context.cart.get("asked_question_node_ids") or []]
    question_text = str(
        ((contract.get("questions") or {}).get(question_id) or {}).get("text") or ""
    ).strip()
    observed_attempts = sum(
        1
        for row in context.messages
        if (
            str(row.get("role") or "") == "assistant"
            or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
        )
        and question_text
        and graph_proof_checker_v3._question_already_asked(
            question_text,
            str(row.get("content") or row.get("texto") or row.get("text") or ""),
        )
    )
    if max(asked.count(question_id), observed_attempts) < MAX_PENDING_QUESTION_ATTEMPTS:
        return None
    return {
        "field_key": key,
        "owner_node_id": owner,
        "status": "unknown",
        "value": None,
        "source_message_id": _source_message_id(context.messages),
        "evidence_span": "",
        "confidence": 1.0,
    }


def _normalize_fact_source_message_ids(
    proposal: ConversationProposal,
    context: ConversationContext,
) -> ConversationProposal:
    """Attach facts to the backend-authoritative current inbound identity.

    ``source_message_id`` is technical lineage, not model-authored content.
    The n8n prompt exposes the provider/external identity while the projected
    recent-message package can use the database message identity.  Both refer
    to the same inbound, but requiring the model to echo whichever projection
    the proof checker happened to choose made valid literal facts fail
    nondeterministically.  Values still have to pass owner, literal-span,
    schema, overwrite and dependency proof below.
    """
    source_message_id = _source_message_id(context.messages)
    return proposal.model_copy(update={
        "extracted_facts": [
            fact.model_copy(update={"source_message_id": source_message_id})
            for fact in proposal.extracted_facts
        ],
    })


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


def _repeated_pending_question_is_allowed(
    *,
    next_question_node_id: str | None,
    aggregate_missing: list[dict[str, Any]],
    asked_question_node_ids: list[str],
) -> bool:
    """Allow a repeated reply only when its published question is still pending."""
    if not next_question_node_id:
        return False
    return (
        0 < asked_question_node_ids.count(next_question_node_id)
        < MAX_PENDING_QUESTION_ATTEMPTS
        and any(
            field.get("question_node_id") == next_question_node_id
            for field in aggregate_missing
        )
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
    or complaint signal at all) got waved into an unrelated complaint branch
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


# Matched against _normalized_phrase output, so accents and punctuation are
# already gone ("Olá!" -> "ola"). Ordered longest-first where two alternatives
# share a prefix ("boa tarde" before the bare "boa"), because alternation
# takes the first match, not the longest one. The trailing repeated-letter
# allowances ("oiii", "olaa", "bom diaa") are how people actually type a
# greeting on WhatsApp; "oio" stays out because \b fails mid-word.
_GREETING_PATTERN = re.compile(
    r"^(?:"
    r"bo[ma]\s+(?:dia|tarde|noite)a*"
    r"|tudo\s+(?:bem|bom|certo)|td\s+bem|como\s+vai(?:\s+voce)?"
    r"|oi+e?|ola+|opa+|alo+|salve|e\s?a(?:i+|e+)|ei+"
    r"|beleza|blz|boa"
    r"|hello|hey|hi"
    r")\b"
)


def _is_greeting(message: str) -> bool:
    """Recognize only the linguistic intent; response copy remains graph-owned."""
    return bool(_GREETING_PATTERN.match(_normalized_phrase(message)))


def _greeting_remainder(message: str) -> str:
    """What the customer actually said once every greeting form is stripped.

    Greetings chain in PT-BR ("oi, bom dia, tudo bem"), so this consumes
    every leading form rather than only the first one -- what is left is the
    real request, if there is one.
    """
    remainder = _normalized_phrase(message)
    while match := _GREETING_PATTERN.match(remainder):
        remainder = remainder[match.end():].strip()
    return remainder


def _is_bare_greeting(message: str) -> bool:
    """A greeting carrying no request -- the only turn that may skip the model.

    Confirmed live 2026-08-14 (captured in the aurora-premium-sdr skill's
    exemplos-de-conversas): "Oi! Tudo bem? Queria saber quais serviços vocês
    fazem aí na Aurora." took the deterministic greeting short-circuit
    because "serviços" matches no branch anchor, so the reply was the canned
    greeting plus the name question and the question about services was
    never answered at all. A greeting that carries a doubt has to reach the
    model; only a greeting with nothing else in it stays model-free.
    """
    return _is_greeting(message) and not _greeting_remainder(message)


def _is_agent_message(row: dict[str, Any]) -> bool:
    return (
        str(row.get("role") or "") == "assistant"
        or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
    )


def _already_engaged(messages: list[dict[str, Any]]) -> bool:
    """True once the agent has already replied at least once in this window.

    A mid-conversation message that happens to start with "oi"/"olá" (very
    natural in PT-BR -- "oi, e sobre os faróis?") must not re-trigger the
    canned greeting. `messages` is the same recent-history window already
    used by `_repeats_recent_outbound`/`_repeated_pending_question_is_allowed`,
    so this adds no new state or persistence -- it only asks a question that
    window can already answer: has the agent said anything here before?
    """
    return any(_is_agent_message(row) for row in messages)


def _persona_node(document: dict[str, Any]) -> dict[str, Any]:
    return next(
        (node for node in document.get("nodes") or [] if node.get("node_type") == "persona"),
        {},
    )


def _qualification_question_node_id(document: dict[str, Any], field_key: str) -> str | None:
    """Find the published question node for a field outside any branch contract.

    On a first-contact greeting there is no active branch yet, so
    contract["questions"] is empty and the greeting turn used to carry
    question_node_id=None -- which meant _decide never recorded the question
    in asked_question_node_ids, leaving the ask-once guard
    (MAX_PENDING_QUESTION_ATTEMPTS) with nothing but a fuzzy text match to
    work from. The nodes exist regardless of contract: they are the FAQs
    materialized by graph_conversation_contract.materialize_qualification_questions,
    carrying the same data.metadata.role/field_key contract read here.
    """
    if not field_key:
        return None
    for node in document.get("nodes") or []:
        if node.get("node_type") != "faq":
            continue
        data = node.get("data") or {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        role = metadata.get("role") or data.get("role")
        key = str(metadata.get("field_key") or data.get("field_key") or "").strip()
        if role == "qualification_question" and key == field_key:
            return str(node.get("id") or "") or None
    return None


def _greeting_policy(
    document: dict[str, Any], *, contract: dict[str, Any], facts: dict[str, Any],
    lead_ref: int = 0,
) -> dict[str, Any] | None:
    persona = _persona_node(document)
    data = persona.get("data") or {}
    policy = data.get("conversation_policy") or {}
    greeting = ((policy.get("intents") or {}).get("greeting") or {})
    responses = [
        text for value in (greeting.get("responses") or [])
        if isinstance(value, str) and (text := value.strip())
    ]
    # The graph may publish several openings. Rotating by lead_ref keeps every
    # lead on a stable phrase across their own turns while spreading the
    # variants across leads, and needs no extra persisted state to do it.
    response = (
        responses[int(lead_ref) % len(responses)] if responses
        else str(greeting.get("response") or "").strip()
    )
    if not response:
        return None
    pending = graph_proof_checker_v3.pending_fields(contract, facts) if contract else []
    askable = graph_proof_checker_v3.askable_pending_fields(contract, facts) if contract else []
    # The published contract is the sole owner of qualification order. The
    # graph validator guarantees that a declared identity_field is the first
    # required field, so the greeting must never bypass missing_fields[0].
    chosen = askable[0] if askable else None
    question_id = chosen.get("question_node_id") if chosen else None
    question = str(
        (((contract.get("questions") or {}).get(str(question_id or "")) or {}).get("text"))
        or ""
    ).strip()
    field_key = chosen.get("key") if chosen else None
    if not contract:
        appointment = data.get("appointment_policy") or {}
        required = [str(value) for value in appointment.get("required_fields") or [] if value]
        questions = appointment.get("field_questions") or {}
        unresolved = [
            key for key in required
            if not graph_proof_checker_v3.field_resolved({}, facts.get(key))
        ]
        field_key = next(iter(unresolved), None)
        question = str(questions.get(field_key) or "").strip() if field_key else ""
        question_id = _qualification_question_node_id(document, str(field_key or ""))
    return {
        "response": response,
        "question": question,
        "question_node_id": question_id,
        "asked_field_key": field_key,
        "missing_fields": [field.get("key") for field in pending]
        if pending else ([field_key] if field_key else []),
    }


SYSTEM_PROMPT = (
    "Você propõe a conversa; o backend apenas prova o GraphRAG publicado. "
    "Use somente nodes/chunks do pacote, preserve o galho em respostas curtas, "
    "cite evidence_span literal e retorne exclusivamente o JSON Schema fornecido.\n\n"

    "branch_action tem quatro valores e cada um significa algo diferente. Use "
    "\"select\" na primeira vez que o cliente demonstrar interesse real em um "
    "produto ou serviço específico -- sempre que ainda não existir um galho "
    "estabelecido nesta conversa (active_branch_node_id vazio), mesmo que "
    "pareça a continuação natural do papo que vocês já estavam tendo. Nunca "
    "proponha \"keep\" nesse momento: \"keep\" só faz sentido quando já existe "
    "um galho estabelecido e o cliente está respondendo o próximo campo "
    "pendente dele. \"switch\" troca para um galho diferente, descartando o "
    "anterior -- use quando o cliente muda de ideia sobre o serviço. \"add\" "
    "soma um segundo galho sem descartar o primeiro -- use quando o cliente "
    "pede um serviço adicional mantendo o que já estava em andamento (ex.: "
    "\"quero higienização interna e também polimento\").\n\n"

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

    "Prefira respostas curtas, do tamanho de uma mensagem real de WhatsApp -- "
    "evite parágrafos longos ou explicações que o cliente não pediu. Calibre "
    "o tamanho pela forma como o próprio cliente escreve: se ele manda "
    "mensagens curtas e diretas, responda igualmente enxuto; só se estenda "
    "um pouco mais quando ele mesmo escrever mensagens longas e detalhadas.\n\n"

    "Quando a resposta do cliente for genuinamente ambígua entre dois ou "
    "mais produtos parecidos (por exemplo, um termo que bate em várias "
    "variações do catálogo), não arrisque escolher um galho no achismo -- "
    "peça um esclarecimento rápido e natural antes de selecionar. Reconheça "
    "o que ele disse antes de perguntar, do jeito que um vendedor de "
    "verdade faria (\"Entendi, temos algumas opções de polimento -- qual "
    "encaixa melhor: X ou Y?\"), nunca dando a entender que ele foi confuso "
    "ou impreciso (evite \"não entendi\" ou \"pode ser mais específico?\").\n\n"

    "Uma pergunta publicada é feita uma única vez enquanto o campo estiver "
    "pendente. Se o cliente não responder, o backend marca o campo como "
    "unknown e segue para o próximo; não tente perguntá-lo novamente. Se o "
    "cliente fornecer esse dado espontaneamente mais tarde, extraia-o "
    "normalmente como known para substituir unknown. Além disso, "
    "nunca repita a pergunta ou frase do turno anterior "
    "quase palavra por palavra, nem a mesma construção turno após turno. "
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
    "última mensagem do cliente. Um intervalo de algumas horas é normal "
    "numa conversa de WhatsApp -- o cliente pode ter ficado ocupado e "
    "voltado no mesmo dia, isso não significa que o assunto mudou. Só trate "
    "a nova mensagem como início de uma conversa nova (não como continuação "
    "direta) quando o intervalo for mais de ~3-4 horas -- e mesmo assim não "
    "assuma que o assunto ou a urgência de antes ainda valem, especialmente "
    "se o assunto mudou (ex.: uma reclamação depois de um agendamento já "
    "concluído).\n\n"

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
    # The buffer can canonically coalesce several physical messages. Use that
    # ordered text for this decision/proof without rewriting persisted history
    # or changing the canonical inbound identity.
    messages = _overlay_canonical_inbound(messages, message, message_id)
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
    # A direct answer to the last published non-service question can contain a
    # service title as part of the value (for example, a vehicle condition).
    # Do not reinterpret that title as branch routing unless the customer uses
    # explicit add/switch language.
    pending_field_answer = _is_direct_answer_to_pending_non_service_field(
        message=message,
        contract=active_contract,
        missing_fields=missing,
        asked_question_node_ids=ledger.get("asked_question_node_ids") or [],
    )
    deterministic_candidates = (
        [] if pending_field_answer
        else _deterministic_branch_candidates(document, message)
    )
    greeting_eligible = _is_greeting(message) and not _already_engaged(messages)
    greeting_prefix = _greeting_policy(
        document, contract=active_contract, facts=ledger.get("facts") or {},
        lead_ref=lead_ref,
    ) if greeting_eligible else None
    # Only a greeting that asks nothing and names no service skips the model.
    # Anything else -- a doubt, a service, both -- has to be answered, with
    # the greeting riding along as a prefix instead.
    greeting = greeting_prefix if (
        greeting_eligible
        and _is_bare_greeting(message)
        and not deterministic_candidates
    ) else None
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
            known_facts=_known_facts_payload(
                ledger.get("facts_by_key") or ledger.get("facts") or {}, message_id,
            ),
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
    suppress_global_branch_search = bool(
        pending_field_answer or short_expected_answer
    )
    branch_rank_started = time.perf_counter()
    candidates = deterministic_candidates or ([] if suppress_global_branch_search else _candidate_branches(
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
    interrogative_clause = _interrogative_clause(message)
    faq_rows: list[dict[str, Any]] = []
    selected_faq_row: dict[str, Any] | None = None
    faq_selection_method = "no_interrogative_clause"
    faq_candidates: list[dict[str, Any]] = []
    eligible_faq_node_ids = [
        str(node_id) for node_id in contract.get("eligible_faq_node_ids") or [] if node_id
    ]
    if interrogative_clause and eligible_faq_node_ids:
        faq_embedding = graph_compiler_v3.query_embeddings([interrogative_clause])[0]
        faq_rows = supabase_client.search_graph_faq_v3(
            persona_id=str(persona["id"]), publication_id=publication["id"],
            branch_node_id=retrieval_branch, query=interrogative_clause,
            query_embedding=faq_embedding,
            eligible_faq_node_ids=eligible_faq_node_ids, limit=64,
        )
        selected_faq_row, faq_selection_method, faq_candidates = _select_faq_candidate(
            interrogative_clause, faq_rows,
        )
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
    selected_faq_chunk: dict[str, Any] | None = None
    if selected_faq_row:
        selected_faq_chunk = {
            **selected_faq_row,
            "source_node_id": str(
                selected_faq_row.get("faq_node_id")
                or selected_faq_row.get("source_node_id") or ""
            ),
            "chunk_kind": "faq",
            "hybrid_score": float(selected_faq_row.get("faq_score") or 1),
        }
        if not selected_faq_chunk.get("chunk_id") or not selected_faq_chunk.get("source_node_id"):
            raise RuntimeError("selected FAQ evidence is missing its chunk or node identity")
    merged = {
        str(row.get("chunk_id") or row.get("id")): row
        for row in [*rows, *structural, *([selected_faq_chunk] if selected_faq_chunk else [])]
    }
    required_structural = _required_structural_chunks(structural)
    reserved = [selected_faq_chunk] if selected_faq_chunk else []
    reserved_ids = {
        str(row.get("chunk_id") or row.get("id")) for row in reserved
    }
    if len(required_structural) + len(reserved) > RAG_CHUNK_LIMIT:
        raise RuntimeError(
            "required structural and FAQ chunks exceed the 12-chunk prompt limit"
        )
    structural_ids = {
        str(row.get("chunk_id") or row.get("id")) for row in required_structural
    }
    required_token_count = sum(
        _estimated_tokens(str(row.get("chunk_text") or ""))
        for row in [*required_structural, *reserved]
    )
    if required_token_count > RAG_CHUNK_TOKEN_BUDGET:
        raise RuntimeError("required structural and FAQ chunks exceed the prompt token budget")
    remaining_token_budget = RAG_CHUNK_TOKEN_BUDGET - required_token_count
    selected = (
        _mmr(
            [
                row for key, row in merged.items()
                if key not in structural_ids and key not in reserved_ids
            ],
            RAG_CHUNK_LIMIT - len(required_structural) - len(reserved),
            max_tokens=remaining_token_budget,
        )
        if remaining_token_budget > 0 else []
    )
    # Phase-A candidates are represented only by their compact snippets in the
    # retrieval trace. Full content enters the prompt solely from phase B.
    package = list({
        **{str(row.get("chunk_id") or row.get("id")): row for row in required_structural},
        **{str(row.get("chunk_id") or row.get("id")): row for row in reserved},
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
        "pending_field_branch_resolution_suppressed": pending_field_answer,
        "global_branch_search_executed": not suppress_global_branch_search,
        "deterministic_branch_match": bool(deterministic_candidates),
        "deterministic_branch_resolution": (
            deterministic_candidates[0] if len(deterministic_candidates) == 1 else None
        ),
        # Reached only when the deterministic greeting turn did not return
        # above, so any eligible greeting here is one that must be prefixed
        # onto a model reply -- whether it named a service or asked a doubt.
        "greeting_response": (
            greeting_prefix.get("response") if greeting_prefix else None
        ),
        "retrieval_branch_node_id": retrieval_branch,
        "interrogative_clause": interrogative_clause or None,
        "faq_candidates": faq_candidates,
        "selected_faq_node_id": (
            str(selected_faq_chunk.get("source_node_id")) if selected_faq_chunk else None
        ),
        "selected_faq_chunk_id": (
            str(selected_faq_chunk.get("chunk_id") or selected_faq_chunk.get("id"))
            if selected_faq_chunk else None
        ),
        "faq_selection_method": faq_selection_method,
        "faq_deferral_reason": faq_selection_method if interrogative_clause and not selected_faq_chunk else None,
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
    prompt = SYSTEM_PROMPT
    already_mentioned_services = _previously_mentioned_service_titles(document, messages)
    if already_mentioned_services:
        prompt += (
            "\n\nServiços que você já apresentou nesta conversa: "
            + ", ".join(already_mentioned_services)
            + ". Não reapresente a descrição desses serviços como se fosse "
            "novidade de novo -- responda só o que for perguntado sobre "
            "eles, ou siga para o próximo passo, sem repetir a explicação "
            "inteira."
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
        known_facts=_known_facts_payload(
            ledger.get("facts_by_key") or ledger.get("facts") or {}, message_id,
        ),
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
    proposal = _normalize_fact_source_message_ids(proposal, context)
    proposal = _reconcile_direct_answer_to_pending_field(
        proposal, context, contract, contract_facts,
    )
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
    selected_faq_node_id = str(
        context.retrieval_trace.get("selected_faq_node_id") or ""
    )
    selected_faq_chunk_id = str(
        context.retrieval_trace.get("selected_faq_chunk_id") or ""
    )
    if selected_faq_node_id and selected_faq_chunk_id:
        node_by_id = document.get("node_by_id") or {}
        cited_nodes = [
            node_id for node_id in proposal.cited_node_ids
            if (node_by_id.get(node_id) or {}).get("node_type") != "faq"
            or node_id == selected_faq_node_id
        ]
        cited_chunks = [
            chunk_id for chunk_id in proposal.cited_chunk_ids
            if (node_by_id.get(chunk_sources.get(chunk_id, "")) or {}).get("node_type") != "faq"
            or chunk_id == selected_faq_chunk_id
        ]
        proposal = proposal.model_copy(update={
            "cited_node_ids": list(dict.fromkeys([*cited_nodes, selected_faq_node_id])),
            "cited_chunk_ids": list(dict.fromkeys([*cited_chunks, selected_faq_chunk_id])),
        })
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
    package_node_ids = {card.id for card in context.context_cards} | {
        str(value) for value in observation.get("repair_context_node_ids") or [] if value
    }
    doubt = _doubt_resolution(
        context=context,
        document=document,
        proposal=proposal,
        contract=contract,
        chunk_sources=chunk_sources,
        package_node_ids=package_node_ids,
    )
    if doubt:
        original_errors = [str(error) for error in proof.get("errors") or []]
        non_claim_errors = [
            error for error in original_errors
            if not error.startswith((
                "claim_not_authorized:",
                "claim_without_evidence:",
                "claim_node_evidence_outside_package:",
                "claim_chunk_evidence_outside_package:",
                "claim_evidence_not_authorized:",
            ))
        ]
        if not non_claim_errors:
            proof.update({
                "valid": True,
                "errors": [],
                "repair_required": False,
                "repair_requirements": [],
                "model_proposal_errors": original_errors,
                "fallback_used": False,
                **doubt,
            })
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
        unanswered_fact = _unanswered_fact_after_question_limit(
            context=context,
            contract=contract,
            ledger_facts=contract_facts,
            proposal=proposal,
        )
        if unanswered_fact:
            accepted_facts.append(unanswered_fact)
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
        aggregate_askable = graph_proof_checker_v3.aggregate_askable_fields(
            document.get("branch_contracts") or {}, active_branch_ids, next_grouped,
        ) if active_branch_ids else []
        next_question_id = next(
            (field.get("question_node_id") for field in aggregate_askable if field.get("question_node_id")),
            None,
        )
        question_contract = next(
            (
                candidate for candidate in (document.get("branch_contracts") or {}).values()
                if next_question_id in (candidate.get("questions") or {})
            ),
            contract,
        )
        reply_seed = str((doubt or {}).get("text") or proposal.reply)
        if (
            not accepted_facts
            and next_question_id
            and not doubt
            and not context.retrieval_trace.get("deterministic_branch_resolution")
            and len(_latest_user_message(context).split()) <= 3
        ):
            reply_seed = ""
        reply = graph_proof_checker_v3.compose_published_question(
            reply=reply_seed,
            next_question_node_id=next_question_id,
            contract=question_contract,
        )
        greeting_response = str(context.retrieval_trace.get("greeting_response") or "").strip()
        if greeting_response and not _normalized_phrase(reply).startswith(
            _normalized_phrase(greeting_response)
        ):
            reply = "\n\n".join(part for part in (greeting_response, reply) if part)
        if unanswered_fact and not next_question_id:
            reply = " ".join(
                sentence.strip()
                for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", reply_seed)
                if sentence.strip() and "?" not in sentence
            ).strip()
        repeated_pending_question = _repeated_pending_question_is_allowed(
            next_question_node_id=next_question_id,
            aggregate_missing=aggregate_missing,
            asked_question_node_ids=context.cart.get("asked_question_node_ids") or [],
        )
        if (
            _repeats_recent_outbound(reply, context.messages)
            and not repeated_pending_question
        ):
            raise RuntimeError("semantic reply repetition blocked by recent outbound proof")

        facts = _facts_for_contract(
            (document.get("branch_contracts") or {}).get(committed_branch) or {},
            next_grouped,
        )
        state = {**context.cart, "facts": facts, "facts_by_key": next_grouped,
                 "active_branch_node_id": committed_branch,
                 "active_branch_node_ids": active_branch_ids,
                 "asked_question_node_ids": [
                      *(context.cart.get("asked_question_node_ids") or []),
                      *([next_question_id] if next_question_id else []),
                  ]}
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
            "fallback_used": False,
            **(doubt or {}),
        }
        evidence_node_ids = list(dict.fromkeys([
            *proposal.cited_node_ids,
            *((doubt or {}).get("doubt_node_ids") or []),
        ]))
        return (
            ConversationDecision(classifier="graph_proof_checker_v3",
                                 intent="qualification_complete" if qualification_complete else "collect_graph_fields",
                                 route=route, confidence=1, lead_stage="qualificado" if qualification_complete else "engajado",
                                 handoff_reason="graph_handoff_rule" if proposal.handoff_requested else None,
                                 evidence_node_ids=evidence_node_ids),
            AgentResponse(reply_text=reply, role=route, evidence_node_ids=evidence_node_ids,
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
        "asked_question_node_ids": [
            *(context.cart.get("asked_question_node_ids") or []),
            *([fallback_id] if fallback_id else []),
        ],
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

"""Two-phase, branch-scoped GraphRAG context and proposal reconciliation."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from schemas.conversation import (
    AgentResponse,
    BranchAction,
    CommercialClaim,
    ContextCard,
    ConversationContext,
    ConversationDecision,
    ConversationFactStatus,
    ConversationProposal,
    ConversationRoute,
    ExtractedFact,
    InteractionKind,
    JourneyAction,
    ServiceOperation,
    ServiceOperationAction,
    ServiceObservation,
)
from services import (
    conversation_repetition,
    graph_compiler_v3,
    graph_proof_checker_v3,
    shared_lead_memory,
    supabase_client,
)


logger = logging.getLogger("graph_agent_runtime_v3")

RUNTIME_VERSION = "graph_agent_runtime_v3"
CONTRACT_VERSION = "graph_agent_contract_v4"
FAQ_SEMANTIC_MIN_SCORE = 0.18
FAQ_SEMANTIC_MIN_MARGIN = 0.03
SERVICE_MAX_EDIT_DISTANCE = 3
SERVICE_TEXT_MIN_SIMILARITY = 0.80
SERVICE_SEMANTIC_MIN_SCORE = 0.78
SERVICE_SEMANTIC_MIN_MARGIN = 0.08
# How sure the model has to be before its own reading of a semantic field
# stands without a confirmation turn. Generic default; the graph overrides
# it per field with `validation.model_confidence_min`.
MODEL_FACT_CONFIDENCE_MIN = 0.90
# How long after the customer's last unanswered message the agent may still
# speak when the AI is switched back on. Past it the agent waits for the
# customer to start. Overridden by the persona graph.
RESUME_ANSWER_WINDOW_SECONDS = 36000


def _normalize_initial_service_keep(
    proposal: ConversationProposal,
    *,
    context: ConversationContext,
) -> ConversationProposal:
    """Convert a literal first-service ``keep`` into a proven selection.

    A model can answer a service FAQ correctly while emitting ``keep`` even
    though no branch is active yet. The proof checker must reject an
    unsupported guess, but it should not reject a literal customer service
    answer and discard its grounded reply. Normalize only when the service
    evidence is present verbatim in this turn.
    """
    if context.active_branch_node_id or proposal.branch_action is not BranchAction.KEEP:
        return proposal
    message = _latest_user_message(context)
    matching = [
        operation
        for operation in proposal.service_operations
        if operation.action.value == "keep"
        and operation.branch_anchor_node_id == proposal.branch_anchor_node_id
        and graph_proof_checker_v3._literal_span(message, operation.evidence_span)
    ]
    branch_span = proposal.branch_evidence_span or (matching[0].evidence_span if matching else "")
    if not branch_span or not graph_proof_checker_v3._literal_span(message, branch_span):
        return proposal
    return proposal.model_copy(update={
        "branch_action": BranchAction.SELECT,
        "branch_evidence_span": branch_span,
        "service_operations": [
            operation.model_copy(update={"action": ServiceOperationAction.ADD})
            if operation in matching else operation
            for operation in proposal.service_operations
        ],
    })


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
    context: ConversationContext,
    raw: Any,
    errors: list[str],
    *,
    repair_attempt: int = 0,
) -> tuple[ConversationDecision, AgentResponse]:
    model_errors = list(dict.fromkeys(errors))
    if repair_attempt < 1:
        return (
            ConversationDecision(
                classifier="graph_proof_checker_v3",
                intent="repair_retrieval",
                route=ConversationRoute.SDR,
                confidence=0,
                lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            ),
            AgentResponse(
                reply_text=None,
                role=ConversationRoute.SDR,
                cart_state=context.cart,
                handoff_required=False,
                proof={
                    "valid": False,
                    "delivery_authorized": False,
                    "errors": model_errors,
                    "gating_errors": ["model_output_invalid"],
                    "repair_required": True,
                    "repair_requirements": [{
                        "kind": "schema",
                        "issue": "model_output_invalid",
                        "instruction": (
                            "Return one complete grounded model observation; "
                            "do not add deterministic copy."
                        ),
                    }],
                    "fallback_used": False,
                    "mode": "model_output_repair",
                    "accepted_facts": [],
                    "model_reply_preserved": True,
                },
            ),
        )
    return (
        ConversationDecision(
            classifier="graph_proof_checker_v3",
            intent="model_repair_exhausted",
            route=ConversationRoute.HUMAN,
            confidence=0,
            lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            handoff_reason="model_metadata_inconsistent_after_repair",
        ),
        AgentResponse(
            reply_text=None,
            role=ConversationRoute.HUMAN,
            cart_state=context.cart,
            handoff_required=True,
            proof={
                "valid": False,
                "delivery_authorized": False,
                "errors": model_errors,
                "gating_errors": ["model_output_invalid_after_repair"],
                "repair_required": False,
                "fallback_used": False,
                "model_reply_preserved": True,
                "technical_pass": False,
                "quality_pass": False,
                "handoff_observable": True,
                "accepted_facts": [],
            },
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
                # Only ever set by _seed_carried_facts, which only seeds
                # fields the compiled contract marked carry_over=true (see
                # _carry_over_field_keys) -- i.e. this is never a
                # this-order fact, always customer identity.
                "carregado_do_pedido_anterior": bool(fact.get("carried_from_journey")),
            })
    return payload


def _estimated_tokens(text: str) -> int:
    """Same rough chars/4 estimate context_cards.resolve_cards() already
    uses for its own max_tokens budget -- good enough for a guardrail, not
    meant to match a real tokenizer exactly."""
    return max(1, len(text or "") // 4)


# Retrieval remains bounded by relevance and cardinality. The provider owns
# its context/completion limits; a local fixed token ceiling can reject the
# graph-owned structural and FAQ chunks before the model sees the turn.
RAG_CHUNK_TOKEN_BUDGET: int | None = None
RAG_CHUNK_LIMIT = 12
RAG_FAQ_CHUNK_RESERVE = 4


def _mmr(
    candidates: list[dict[str, Any]],
    limit: int,
    *,
    max_tokens: int | None = RAG_CHUNK_TOKEN_BUDGET,
) -> list[dict[str, Any]]:
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
        if max_tokens is not None and selected and token_count + estimated > max_tokens:
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


def _optional_retrieval_chunk_slots(
    required_structural: list[dict[str, Any]],
    reserved_faq: list[dict[str, Any]],
) -> int:
    """Return optional MMR capacity without charging FAQ against structure.

    The branch contract can legitimately require all twelve structural slots.
    A current-turn FAQ is separately selected, graph-authorized evidence and
    therefore gets one explicit reserve.  The shared token budget still caps
    the complete structural + FAQ package.
    """
    if len(required_structural) > RAG_CHUNK_LIMIT:
        raise RuntimeError(
            f"required structural chunks exceed the {RAG_CHUNK_LIMIT}-chunk prompt limit"
        )
    if len(reserved_faq) > RAG_FAQ_CHUNK_RESERVE:
        raise RuntimeError("ranked FAQ evidence exceeds its reserved chunk limit")
    return max(0, RAG_CHUNK_LIMIT - len(required_structural) - len(reserved_faq))


def _required_retrieval_node_ids(
    document: dict[str, Any],
    branch_node_id: str,
    contract: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    """Return the executable structural package for one turn.

    The published branch contract already carries every question and handoff
    rule verbatim. The chunk package therefore needs the full active path and
    handoff rule nodes. Question order is model-owned in agentic mode; the
    contract exposes every still-askable authored question without reserving
    one question chunk as the backend-selected next step.
    """
    path = (
        ((document.get("coordinates") or {}).get(branch_node_id) or {})
        .get("path_node_ids") or []
    )
    return list(dict.fromkeys([
        *path,
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


_FAQ_LEXICAL_STOPWORDS = {
    "a", "ao", "as", "da", "das", "de", "do", "dos", "e", "em", "esse",
    "essa", "este", "esta", "eu", "me", "meu", "minha", "no", "na", "nos",
    "nas", "o", "os", "para", "por", "qual", "quais", "que", "um", "uma",
}
_FAQ_INTENT_CANONICAL = {
    "custa": "preco", "custam": "preco", "custo": "preco", "preco": "preco",
    "valor": "preco", "valores": "preco",
    "material": "tecido", "materiais": "tecido", "tecidos": "tecido",
}
_FAQ_INTENT_TERMS = frozenset(_FAQ_INTENT_CANONICAL.values())


def _faq_lexical_terms(value: Any) -> set[str]:
    return {
        _FAQ_INTENT_CANONICAL.get(token, token)
        for token in _normalized_phrase(value).split()
        if token not in _FAQ_LEXICAL_STOPWORDS
    }


def _faq_context_hint(messages: list[dict[str, Any]]) -> str:
    """Return only the latest agent turn preceding the current customer turn.

    Short follow-up questions commonly refer to a product named in the previous
    response. Older conversation text is deliberately ignored so stale catalog
    mentions cannot silently disambiguate a current commercial claim.
    """
    for row in reversed(messages[:-1]):
        if (
            str(row.get("role") or "") == "assistant"
            or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
        ):
            return str(
                row.get("content") or row.get("texto") or row.get("text") or ""
            ).strip()
    return ""


def _rank_faq_candidates(
    interrogative_clause: str, rows: list[dict[str, Any]], *, context_hint: str = ""
) -> list[dict[str, Any]]:
    """Rank scoped FAQs for the model without choosing a public answer."""
    normalized_query = _normalized_phrase(interrogative_clause)
    candidates: list[dict[str, Any]] = []
    query_terms = _faq_lexical_terms(interrogative_clause)
    query_intent = query_terms & _FAQ_INTENT_TERMS
    query_subject = query_terms - _FAQ_INTENT_TERMS
    context_terms = _faq_lexical_terms(context_hint)
    for row in rows:
        aliases = row.get("aliases") or []
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except (TypeError, ValueError):
                aliases = []
        phrases = [row.get("question"), *(aliases if isinstance(aliases, list) else [])]
        phrase_terms = set().union(*(
            _faq_lexical_terms(value) for value in phrases if value
        )) if any(phrases) else set()
        intent_overlap = len(query_intent & phrase_terms)
        subject_overlap = len(query_subject & phrase_terms)
        # Two shared content terms are enough to establish a contextual
        # mention. Do not reward a longer product name when two different
        # published products were both named in the previous response.
        context_overlap = min(2, len(context_terms & phrase_terms))
        lexical_rank = (intent_overlap, subject_overlap, context_overlap)
        exact = bool(normalized_query) and normalized_query in {
            _normalized_phrase(value) for value in phrases if value
        }
        candidate = {
            "faq_node_id": str(row.get("faq_node_id") or row.get("source_node_id") or ""),
            "chunk_id": str(row.get("chunk_id") or row.get("id") or ""),
            "question": str(row.get("question") or ""),
            "semantic_score": round(float(row.get("semantic_score") or 0), 6),
            "lexical_score": round(float(row.get("lexical_score") or 0), 6),
            "contextual_lexical_rank": list(lexical_rank),
            "exact": exact,
        }
        candidates.append(candidate)
    return sorted(
        candidates,
        key=lambda candidate: (
            not bool(candidate["exact"]),
            *(-value for value in candidate["contextual_lexical_rank"]),
            -float(candidate["semantic_score"]),
            -float(candidate["lexical_score"]),
            candidate["faq_node_id"],
        ),
    )


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

_SERVICE_DROP_MARKER = re.compile(
    r"\b(?:remov\w*|retir\w*|cancel\w*|exclu\w*|n[aã]o\s+quero\s+mais|"
    r"deixa\w*\s+de\s+fora|sem\s+o\s+servi[cç]o)\b",
    re.IGNORECASE,
)

_SERVICE_SELECT_MARKER = re.compile(
    r"\b(?:quero|queria|gostaria|preciso|tenho\s+interesse|fazer|contratar|"
    r"selecion\w*|escolh\w*|adicion\w*|inclu\w*|coloc\w*)\b",
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
    return bool(_SERVICE_CHANGE_MARKER.search(message or ""))


def _service_selection_field(contract: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            field for field in contract.get("fields") or []
            if field.get("branch_selection_field") is True
            or str(field.get("key") or "") == "servico"
        ),
        None,
    )


def branch_selection_field_key(document: dict[str, Any]) -> str:
    """The field key that selects a branch (service, product, whatever the
    persona sells) -- resolved from the compiled contract's
    branch_selection_field flag (graph_compiler_v3.branch_selection_field_key),
    falling back to the legacy literal "servico" only when a publication
    predates that flag. Public so other modules (e.g. conversation_runtime's
    lead projection) never need to hardcode the field name either.
    """
    field = _service_selection_field(document.get("common_contract") or {})
    return str(field.get("key")) if field else "servico"


def _is_direct_answer_to_service_question(
    contract: dict[str, Any], asked_question_node_ids: list[str], message: str,
) -> bool:
    field = _service_selection_field(contract)
    return bool(
        field
        and asked_question_node_ids
        and field.get("question_node_id")
        and str(asked_question_node_ids[-1]) == str(field["question_node_id"])
        and not _looks_like_customer_question(message)
    )


def _safe_active_focus(
    active_branch_node_id: str | None,
    persisted_active_branch_node_ids: list[str],
) -> tuple[str | None, list[str], bool]:
    """Repair scalar/set drift for this turn without mutating production state."""
    active = list(dict.fromkeys(
        str(value) for value in persisted_active_branch_node_ids if value
    ))
    focus = str(active_branch_node_id or "") or None
    if not active and focus:
        active = [focus]
    derived = bool(active and focus not in set(active))
    if derived:
        focus = active[-1]
    if not active:
        focus = None
    return focus, active, derived


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
        or _message_requests_additional_service(message)
        or _message_explicitly_changes_service(message)
    ):
        return False
    last_question_id = str(asked_question_node_ids[-1] or "")
    field = next(
        (
            row for row in contract.get("fields") or []
            if str(row.get("question_node_id") or "") == last_question_id
            and str(row.get("key") or "") in set(missing_fields)
        ),
        None,
    )
    if not field or str(field.get("key") or "") == "servico":
        return False
    return True


def _has_explicit_service_intent(message: str) -> bool:
    return bool(
        _SERVICE_SELECT_MARKER.search(message or "")
        or _SERVICE_CHANGE_MARKER.search(message or "")
        or _SERVICE_DROP_MARKER.search(message or "")
        or _ADDITIVE_SERVICE_MARKER.search(message or "")
    )


def _reserve_message_for_pending_field(
    resolution: dict[str, Any], *, pending_field_answer: bool, message: str,
    active_branch_node_id: str | None, active_branch_node_ids: list[str],
) -> dict[str, Any]:
    if not pending_field_answer or _has_explicit_service_intent(message):
        return resolution
    return {
        "status": "none",
        "matches": [],
        "ambiguities": [],
        "consumed_spans": [],
        "reserved_spans": [],
        "previous_active_branch_node_ids": list(active_branch_node_ids),
        "next_active_branch_node_ids": list(active_branch_node_ids),
        "focused_branch_node_id": active_branch_node_id,
        "operations": [],
        "resolution_method": "suppressed_for_pending_non_service_field",
        "rejection_reason": "evidence_reserved_for_pending_field",
    }


def _routable_deterministic_candidates(
    message: str,
    candidates: list[dict[str, Any]],
    *,
    pending_field_answer: bool,
) -> list[dict[str, Any]]:
    """Do not let a literal service word steal an answer to the pending field."""
    if pending_field_answer and not _has_explicit_service_intent(message):
        return []
    return candidates


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


# Uma claim declarada por um unico galho vale na descoberta -- menos quando o
# assunto e comercial. Preco e regra de pagamento continuam exigindo que o
# cliente tenha escolhido o servico, e para a Aurora tambem continuam passando
# por `price_disclosure: human_only` no commit. O agente pode explicar o que um
# servico e; quanto custa segue sendo assunto de gente.
DISCOVERY_BLOCKED_CLAIM_TYPES = frozenset({"price", "payment_policy"})


def _discovery_claims(
    common: dict[str, Any], branch: dict[str, Any],
) -> list[dict[str, Any]]:
    """Claims que valem antes de o cliente escolher um servico."""
    claims: list[dict[str, Any]] = list(common.get("claims") or [])
    seen = {graph_compiler_v3.canonical_checksum(claim) for claim in claims}
    for claim in branch.get("claims") or []:
        if str(claim.get("claim_type") or "") in DISCOVERY_BLOCKED_CLAIM_TYPES:
            continue
        checksum = graph_compiler_v3.canonical_checksum(claim)
        if checksum in seen:
            continue
        seen.add(checksum)
        claims.append(claim)
    return claims


def _preselection_contract(
    document: dict[str, Any], retrieval_branch_node_id: str,
) -> dict[str, Any]:
    """Bind common fields to a real retrieval branch for proof coordinates."""
    branch = (
        (document.get("branch_contracts") or {}).get(retrieval_branch_node_id) or {}
    )
    common = document.get("common_contract") or {}
    if not common:
        return branch
    return {
        **branch,
        "fields": list(common.get("fields") or []),
        "required_fields": list(common.get("required_fields") or []),
        "questions": dict(common.get("questions") or {}),
        "completion": dict(common.get("completion") or {}),
        "conversation_policy": (
            common.get("conversation_policy") or branch.get("conversation_policy") or {}
        ),
        "field_labels": common.get("field_labels") or branch.get("field_labels") or {},
        "handoff": {}, "handoff_rule_node_ids": [], "handoff_rules": [],
        # As claims do contrato comum sao exatamente as que TODOS os galhos
        # autorizam -- as FAQs projetadas de `global_context`. Elas nao dependem
        # de qual servico o cliente vai escolher, entao valem antes da escolha.
        #
        # Isso sozinho nao basta. Confirmado em producao 2026-08-17 (lead 12):
        # a FAQ de um servico pendura no proprio servico, entao ela vive em 1
        # dos 17 contratos de galho da Aurora e nunca no comum. O cliente que
        # perguntava "como funciona o ppf?" antes de escolher recebia
        # `claim_not_authorized`/`claim_evidence_not_authorized`, a proposta
        # inteira era descartada e o turno caia no fallback legado -- ou
        # em silencio, quando o fallback repetia a pergunta anterior. Ou seja:
        # para perguntar sobre um servico o cliente precisava ja te-lo
        # escolhido, o inverso de como uma venda consultiva funciona.
        #
        # Por isso o galho de recuperacao tambem autoriza durante a descoberta.
        # A regua de evidencia nao muda: `check()` continua exigindo que todo
        # `evidence_node_id` esteja em `package_node_ids & closure_node_ids`,
        # entao o agente so pode afirmar o que o RAG trouxe para este turno --
        # nao o catalogo inteiro. O que muda e so quando a autoridade passa a
        # valer, nao o que ela cobre.
        "claims": _discovery_claims(common, branch),
    }


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


def _literal_phrase_occurrences(message: str, phrase: Any) -> list[dict[str, Any]]:
    target_tokens = _normalized_phrase(phrase).split()
    if not target_tokens:
        return []
    tokens = list(re.finditer(r"\w+", str(message or ""), flags=re.UNICODE))
    normalized_tokens = [_normalized_phrase(match.group(0)) for match in tokens]
    width = len(target_tokens)
    return [
        {
            "start": tokens[index].start(),
            "end": tokens[index + width - 1].end(),
            "span": str(message)[tokens[index].start():tokens[index + width - 1].end()],
            "match_length": len(" ".join(target_tokens)),
        }
        for index in range(0, len(tokens) - width + 1)
        if normalized_tokens[index:index + width] == target_tokens
    ]


def _literal_service_resolution(
    document: dict[str, Any], message: str,
) -> dict[str, Any]:
    """Return every non-overlapping, graph-owned service mention.

    Overlapping aliases are resolved by the longest published phrase. A tie
    between distinct anchors is an ambiguity and must never mutate state.
    """
    raw_matches: list[dict[str, Any]] = []
    for anchor in document.get("branch_anchors") or []:
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        phrases = [
            node.get("title"), node.get("slug"),
            *((node.get("data") or {}).get("aliases") or []),
        ]
        seen_phrases: set[str] = set()
        for phrase in phrases:
            normalized = _normalized_phrase(phrase)
            if len(normalized) < 3 or normalized in seen_phrases:
                continue
            seen_phrases.add(normalized)
            for occurrence in _literal_phrase_occurrences(message, phrase):
                raw_matches.append({
                    **occurrence,
                    "branch_anchor_node_id": anchor,
                    "branch_path_checksum": (
                        ((document.get("coordinates") or {}).get(anchor) or {})
                        .get("path_checksum")
                    ),
                    "title": node.get("title"),
                    "slug": node.get("slug"),
                    "matched_phrase": str(phrase),
                })
    if not raw_matches:
        return {"status": "none", "matches": [], "ambiguities": [], "consumed_spans": []}

    raw_matches.sort(key=lambda item: (item["start"], item["end"]))
    groups: list[list[dict[str, Any]]] = []
    for match in raw_matches:
        overlapping = next(
            (group for group in groups if any(
                match["start"] < item["end"] and item["start"] < match["end"]
                for item in group
            )),
            None,
        )
        if overlapping is None:
            groups.append([match])
        else:
            overlapping.append(match)

    selected: list[dict[str, Any]] = []
    ambiguities: list[dict[str, Any]] = []
    for group in groups:
        longest = max(int(item["match_length"]) for item in group)
        finalists = [item for item in group if int(item["match_length"]) == longest]
        anchors = list(dict.fromkeys(item["branch_anchor_node_id"] for item in finalists))
        representative = finalists[0]
        if len(anchors) > 1:
            ambiguities.append({
                "evidence_span": representative["span"],
                "start": representative["start"],
                "end": representative["end"],
                "candidate_branch_node_ids": anchors,
            })
            continue
        selected.append(representative)

    selected.sort(key=lambda item: item["start"])
    consumed = [
        {
            "text": item["span"], "start": item["start"], "end": item["end"],
            "branch_anchor_node_id": item["branch_anchor_node_id"],
            "evidence_type": "exact_catalog",
        }
        for item in selected
    ]
    return {
        "status": "ambiguous" if ambiguities else "resolved",
        "matches": selected,
        "ambiguities": ambiguities,
        "consumed_spans": consumed,
    }


def _deterministic_branch_candidates(
    document: dict[str, Any], message: str,
) -> list[dict[str, Any]]:
    """Resolve graph-owned titles/aliases before semantic retrieval.

    This is generic graph data, not commercial copy in backend code. An
    unambiguous phrase opens the branch directly and avoids an LLM repair call.
    """
    resolution = _literal_service_resolution(document, message)
    if resolution["status"] == "ambiguous":
        return []
    return [{
        **item,
        "score": 1.0,
        "snippet": item["span"],
        "branch_evidence_span": item["span"],
        "evidence_chunk_ids": [],
        "deterministic_alias_match": True,
    } for item in resolution["matches"]]


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def _textual_service_candidates(
    document: dict[str, Any], message: str,
) -> list[dict[str, Any]]:
    """Return unique conservative typo candidates from published catalog text."""
    raw = str(message or "")
    message_tokens = list(re.finditer(r"\w+", raw, flags=re.UNICODE))
    candidates: dict[str, dict[str, Any]] = {}
    for anchor in document.get("branch_anchors") or []:
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        phrases = [
            node.get("title"), node.get("slug"),
            *((node.get("data") or {}).get("aliases") or []),
        ]
        best: dict[str, Any] | None = None
        for phrase in phrases:
            normalized_phrase = _normalized_phrase(phrase)
            if len(normalized_phrase) < 4:
                continue
            width = len(normalized_phrase.split())
            for index in range(0, len(message_tokens) - width + 1):
                start = message_tokens[index].start()
                end = message_tokens[index + width - 1].end()
                span = raw[start:end]
                normalized_span = _normalized_phrase(span)
                distance = _levenshtein_distance(normalized_span, normalized_phrase)
                similarity = 1 - distance / max(len(normalized_span), len(normalized_phrase), 1)
                if distance == 0 or distance > SERVICE_MAX_EDIT_DISTANCE:
                    continue
                if similarity < SERVICE_TEXT_MIN_SIMILARITY:
                    continue
                candidate = {
                    "branch_anchor_node_id": anchor,
                    "branch_path_checksum": (
                        ((document.get("coordinates") or {}).get(anchor) or {})
                        .get("path_checksum")
                    ),
                    "title": node.get("title"),
                    "slug": node.get("slug"),
                    "evidence_span": span,
                    "start": start,
                    "end": end,
                    "edit_distance": distance,
                    "text_similarity": round(similarity, 6),
                    "resolution_method": "textual_similarity",
                }
                if best is None or (
                    candidate["edit_distance"], -candidate["text_similarity"]
                ) < (best["edit_distance"], -best["text_similarity"]):
                    best = candidate
        if best:
            candidates[anchor] = best
    return sorted(
        candidates.values(),
        key=lambda item: (
            item["edit_distance"], -item["text_similarity"],
            item["branch_anchor_node_id"],
        ),
    )


def _resolve_service_operations(
    document: dict[str, Any], message: str, *,
    active_branch_node_id: str | None,
    active_branch_node_ids: list[str],
    contract: dict[str, Any] | None = None,
    asked_question_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    literal = _literal_service_resolution(document, message)
    before = list(dict.fromkeys([
        *([active_branch_node_id] if active_branch_node_id else []),
        *active_branch_node_ids,
    ]))
    base = {
        **literal,
        "previous_active_branch_node_ids": before,
        "next_active_branch_node_ids": list(before),
        "focused_branch_node_id": active_branch_node_id,
        "operations": [],
    }
    direct_answer = _is_direct_answer_to_service_question(
        contract or {}, asked_question_node_ids or [], message,
    )
    explicit_selection = bool(
        _has_explicit_service_intent(message)
        and not _looks_like_customer_question(message)
    )
    if literal["status"] != "resolved" or not literal["matches"]:
        if literal["status"] == "ambiguous":
            return {**base, "resolution_method": "exact_catalog", "confirmation": {
                "kind": "service_disambiguation",
                "options": literal.get("ambiguities") or [],
            }}
        textual = _textual_service_candidates(document, message)
        if not textual:
            return {**base, "resolution_method": "none"}
        best = textual[0]
        tied = [
            item for item in textual
            if item["edit_distance"] == best["edit_distance"]
            and item["text_similarity"] == best["text_similarity"]
        ]
        if len(tied) != 1:
            return {
                **base, "status": "ambiguous", "resolution_method": "textual_similarity",
                "textual_candidates": textual,
                "confirmation": {"kind": "service_disambiguation", "options": tied},
            }
        operation_ambiguous = bool(
            before
            and not _ADDITIVE_SERVICE_MARKER.search(message or "")
            and not _SERVICE_CHANGE_MARKER.search(message or "")
            and not _SERVICE_DROP_MARKER.search(message or "")
        )
        action = (
            "drop" if _SERVICE_DROP_MARKER.search(message or "")
            else "switch" if (
                _SERVICE_CHANGE_MARKER.search(message or "")
                and active_branch_node_id
                and best["branch_anchor_node_id"] != active_branch_node_id
            )
            else "keep" if best["branch_anchor_node_id"] in before else "add"
        )
        candidate = {
            **best, "action": action,
            "operation_ambiguous": operation_ambiguous,
            "replace_branch_node_id": (
                active_branch_node_id if action == "switch" else None
            ),
        }
        return {
            **base, "status": "needs_confirmation",
            "resolution_method": "textual_similarity",
            "textual_candidates": textual,
            "candidate": candidate,
            "reserved_spans": [{
                "text": best["evidence_span"], "start": best["start"], "end": best["end"],
                "branch_anchor_node_id": best["branch_anchor_node_id"],
                "evidence_type": "candidate",
            }],
            "confirmation": {"kind": "service", "candidate": candidate},
        }

    if not (direct_answer or explicit_selection):
        candidate = literal["matches"][-1]
        action = "keep" if candidate["branch_anchor_node_id"] in before else "add"
        operation_ambiguous = bool(
            before
            and candidate["branch_anchor_node_id"] not in before
            and not _ADDITIVE_SERVICE_MARKER.search(message or "")
            and not _SERVICE_CHANGE_MARKER.search(message or "")
            and not _SERVICE_DROP_MARKER.search(message or "")
        )
        return {
            **base, "status": "needs_confirmation",
            "consumed_spans": [],
            "reserved_spans": literal.get("consumed_spans") or [],
            "resolution_method": "exact_catalog_informative_mention",
            "candidate": {
                **candidate, "evidence_span": candidate["span"], "action": action,
                "operation_ambiguous": operation_ambiguous,
            },
            "confirmation": {
                "kind": "service",
                "candidate": {
                    **candidate, "evidence_span": candidate["span"], "action": action,
                    "operation_ambiguous": operation_ambiguous,
                },
            },
        }

    matches = literal["matches"]
    mentioned = [item["branch_anchor_node_id"] for item in matches]
    explicit_change = bool(_SERVICE_CHANGE_MARKER.search(message or ""))
    explicit_drop = bool(_SERVICE_DROP_MARKER.search(message or ""))
    operations: list[dict[str, Any]] = []
    derived_consumed_spans: list[dict[str, Any]] = []
    after = list(before)

    def append_operation(
        action: str, anchor: str, evidence: str, *, evidence_type: str = "exact_catalog",
    ) -> None:
        checksum = str(
            ((document.get("coordinates") or {}).get(anchor) or {}).get("path_checksum")
            or ""
        )
        operations.append({
            "action": action,
            "branch_anchor_node_id": anchor,
            "branch_path_checksum": checksum,
            "evidence_span": evidence,
            "evidence_type": evidence_type,
            "resolution_method": "exact_catalog",
        })

    if explicit_drop and not explicit_change:
        for item in matches:
            anchor = item["branch_anchor_node_id"]
            if anchor in after:
                after.remove(anchor)
                append_operation("drop", anchor, item["span"])
    else:
        if explicit_change:
            drop_targets = [anchor for anchor in mentioned if anchor in after]
            if not drop_targets and active_branch_node_id:
                drop_targets = [active_branch_node_id]
            change_match = _SERVICE_CHANGE_MARKER.search(message or "")
            change_evidence = str((change_match or [""])[0])
            for anchor in drop_targets:
                if anchor in after:
                    after.remove(anchor)
                    own_match = next((item for item in matches if item["branch_anchor_node_id"] == anchor), None)
                    if own_match:
                        append_operation("drop", anchor, str(own_match.get("span") or ""))
                    else:
                        append_operation(
                            "drop", anchor, change_evidence, evidence_type="explicit_change",
                        )
                        if change_match:
                            derived_consumed_spans.append({
                                "text": change_evidence,
                                "start": change_match.start(),
                                "end": change_match.end(),
                                "branch_anchor_node_id": anchor,
                                "evidence_type": "explicit_change",
                            })
        for item in matches:
            anchor = item["branch_anchor_node_id"]
            if explicit_change and anchor in before:
                continue
            if anchor in after:
                append_operation("keep", anchor, item["span"])
            else:
                after.append(anchor)
                append_operation("add", anchor, item["span"])

    focus_candidates = [
        item["branch_anchor_node_id"] for item in matches
        if any(
            operation["branch_anchor_node_id"] == item["branch_anchor_node_id"]
            and operation["action"] in {"add", "keep"}
            for operation in operations
        )
    ]
    focus = focus_candidates[-1] if focus_candidates else (after[-1] if after else None)
    return {
        **base,
        "resolution_method": "exact_catalog",
        "direct_answer_to_service_question": direct_answer,
        "explicit_service_intent": explicit_selection,
        "operations": operations,
        "consumed_spans": [
            *(literal.get("consumed_spans") or []),
            *derived_consumed_spans,
        ],
        "next_active_branch_node_ids": after,
        "focused_branch_node_id": focus,
    }


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
    service_resolution = context.retrieval_trace.get("service_resolution") or {}
    operations = service_resolution.get("operations") or []
    active = str(context.active_branch_node_id or "") or None
    resolved_anchor = str(
        service_resolution.get("focused_branch_node_id")
        or ""
    ) or None
    if resolved_anchor:
        anchor = resolved_anchor
        active_set = set(context.active_branch_node_ids)
        if active:
            active_set.add(active)
        if anchor in active_set:
            action = "keep"
        else:
            dropped_focus = any(
                item.get("action") == "drop"
                and item.get("branch_anchor_node_id") == active
                for item in operations
            )
            action = "switch" if active and dropped_focus else ("add" if active else "select")
        focused_operation = next(
            (
                item for item in reversed(operations)
                if item.get("branch_anchor_node_id") == anchor
                and item.get("action") in {"add", "keep"}
            ),
            {},
        )
        evidence_span = str(
            focused_operation.get("evidence_span")
            or ""
        )
    elif active:
        anchor = active
        action = "keep"
        evidence_span = ""
    else:
        # Retrieval focus answers content; it is never proof that the customer
        # selected that offering.  Absence of a resolved branch is explicit.
        anchor = None
        action = "none"
        evidence_span = ""

    coordinate = ((document.get("coordinates") or {}).get(anchor) or {})
    selection_key = branch_selection_field_key(document)
    extracted = [
        fact for fact in proposal.extracted_facts
        if fact.field_key != selection_key
    ]
    existing_service_fact = any(
        str(fact.get("owner_node_id") or "") == anchor
        and fact.get("status") == "known"
        for fact in (context.cart.get("facts_by_key") or {}).get(selection_key, [])
        if isinstance(fact, dict)
    )
    if resolved_anchor and evidence_span and not (action == "keep" and existing_service_fact):
        branch_node = (document.get("node_by_id") or {}).get(anchor) or {}
        extracted.append(ExtractedFact(
            field_key=selection_key,
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
        "service_operations": [ServiceOperation.model_validate(item) for item in operations],
        "extracted_facts": extracted,
    })


def _normalize_referential_service_fact(
    proposal: ConversationProposal,
    context: ConversationContext,
    document: dict[str, Any],
) -> ConversationProposal:
    """Bind ``servico`` to one published branch; arbitrary strings never qualify."""
    service_facts = [fact for fact in proposal.extracted_facts if fact.field_key == "servico"]
    if not service_facts:
        return proposal
    message = _latest_user_message(context)
    anchor = str(proposal.branch_anchor_node_id or "")
    branch = (document.get("node_by_id") or {}).get(anchor) or {}
    coordinate = ((document.get("coordinates") or {}).get(anchor) or {})
    deterministic = (
        (context.retrieval_trace.get("deterministic_branch_resolution") or {})
        .get("branch_anchor_node_id") == anchor
    )
    candidate_ids = {
        str(item.get("branch_anchor_node_id") or "")
        for item in context.retrieval_trace.get("branch_candidates") or []
    }
    switching = proposal.branch_action.value in {"select", "switch", "add"}
    evidence = str(proposal.branch_evidence_span or "").strip()
    evidence_is_literal = bool(evidence and _literal_phrase_span(message, evidence))
    valid = bool(
        branch
        and anchor in set(document.get("branch_anchors") or [])
        and proposal.branch_path_checksum == str(coordinate.get("path_checksum") or "")
        and not _is_social_or_non_service_value(message)
        and (
            deterministic
            or (switching and anchor in candidate_ids and evidence_is_literal)
        )
    )
    kept = [fact for fact in proposal.extracted_facts if fact.field_key != "servico"]
    if valid:
        kept.append(ExtractedFact(
            field_key="servico",
            value=str(branch.get("slug") or branch.get("title") or anchor),
            status="known",
            source_message_id=_source_message_id(context.messages),
            owner_node_id=anchor,
            evidence_span=evidence,
            confidence=1.0,
        ))
    return proposal.model_copy(update={"extracted_facts": kept})
def _fact_consumes_service_evidence(
    fact: ExtractedFact,
    *,
    message: str,
    service_resolution: dict[str, Any],
    document: dict[str, Any],
) -> bool:
    if fact.field_key == "servico":
        return False
    normalized_value = _normalized_phrase(fact.value)
    service_phrases = {
        _normalized_phrase(value)
        for anchor in document.get("branch_anchors") or []
        for value in (
            ((document.get("node_by_id") or {}).get(anchor) or {}).get("title"),
            ((document.get("node_by_id") or {}).get(anchor) or {}).get("slug"),
            *(
                (((document.get("node_by_id") or {}).get(anchor) or {}).get("data") or {})
                .get("aliases", [])
            ),
        )
        if value
    }
    if normalized_value and normalized_value in service_phrases:
        return True
    evidence = str(fact.evidence_span or "")
    start = str(message or "").find(evidence) if evidence else -1
    if start < 0:
        return False
    end = start + len(evidence)
    return any(
        start >= int(span.get("start") or 0) and end <= int(span.get("end") or 0)
        for span in service_resolution.get("consumed_spans") or []
    )


def _remove_consumed_service_facts(
    proposal: ConversationProposal,
    *,
    context: ConversationContext,
    document: dict[str, Any],
) -> tuple[ConversationProposal, list[dict[str, Any]]]:
    service_resolution = context.retrieval_trace.get("service_resolution") or {}
    message = _latest_user_message(context)
    kept: list[ExtractedFact] = []
    rejected: list[dict[str, Any]] = []
    for fact in proposal.extracted_facts:
        if _fact_consumes_service_evidence(
            fact, message=message, service_resolution=service_resolution,
            document=document,
        ):
            rejected.append({
                "field_key": fact.field_key,
                "owner_node_id": fact.owner_node_id,
                "valid": False,
                "errors": ["service_evidence_consumed"],
                "evidence_span": fact.evidence_span,
            })
        else:
            kept.append(fact)
    return proposal.model_copy(update={"extracted_facts": kept}), rejected


def _remove_invalid_declared_facts(
    proposal: ConversationProposal, contract: dict[str, Any],
) -> tuple[ConversationProposal, list[dict[str, Any]]]:
    fields = {str(field.get("key") or ""): field for field in contract.get("fields") or []}
    kept: list[ExtractedFact] = []
    rejected: list[dict[str, Any]] = []
    for fact in proposal.extracted_facts:
        field = fields.get(fact.field_key)
        status = str(fact.status.value if hasattr(fact.status, "value") else fact.status)
        error = None
        canonical = fact.value
        if status == "invalid":
            error = "model_marked_invalid"
        elif field and status == "unknown":
            error = "unknown_requires_runtime_policy"
        elif field and status == "known":
            canonical, error = graph_proof_checker_v3._canonical_field_value(
                field, fact.value, fact.evidence_span,
            )
        if error:
            rejected.append({
                "field_key": fact.field_key,
                "owner_node_id": fact.owner_node_id,
                "valid": False,
                "errors": [error],
                "evidence_span": fact.evidence_span,
            })
            continue
        kept.append(fact.model_copy(update={"value": canonical}))
    return proposal.model_copy(update={"extracted_facts": kept}), rejected


def _message_without_consumed_services(
    message: str, service_resolution: dict[str, Any],
) -> str:
    chars = list(str(message or ""))
    for span in service_resolution.get("consumed_spans") or []:
        for index in range(
            max(0, int(span.get("start") or 0)),
            min(len(chars), int(span.get("end") or 0)),
        ):
            chars[index] = " "
    return re.sub(r"\s+", " ", "".join(chars)).strip(" ,.;:-")


def _service_facts_for_operations(
    *,
    operations: list[dict[str, Any]],
    document: dict[str, Any],
    grouped_facts: dict[str, list[dict[str, Any]]],
    source_message_id: str,
) -> list[dict[str, Any]]:
    selection_key = branch_selection_field_key(document)
    current_owners = {
        str(fact.get("owner_node_id") or "")
        for fact in grouped_facts.get(selection_key, [])
        if fact.get("status") == "known"
    }
    facts: list[dict[str, Any]] = []
    for operation in operations:
        action = str(operation.get("action") or "")
        anchor = str(operation.get("branch_anchor_node_id") or "")
        if action not in {"add", "keep", "drop"} or not anchor:
            continue
        if action == "keep" and anchor in current_owners:
            continue
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        facts.append({
            "field_key": selection_key,
            "owner_node_id": anchor,
            "status": "declined" if action == "drop" else "known",
            "value": None if action == "drop" else str(
                node.get("slug") or node.get("title") or anchor
            ),
            "source_message_id": source_message_id,
            "evidence_span": str(operation.get("evidence_span") or ""),
            "confidence": 1.0,
            "metadata": {
                "source": "service_resolution",
                "operation": action,
                "evidence_type": operation.get("evidence_type"),
                "resolution_method": operation.get("resolution_method"),
                "score": operation.get("score"),
                "margin": operation.get("margin"),
                "branch_path_checksum": operation.get("branch_path_checksum"),
            },
        })
    return facts




def active_offering_titles(
    document: dict[str, Any],
    active_branch_ids: list[str],
    facts_by_key: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Titles of every active branch whose selection fact is known.

    Generic across service/product graphs and across "one" vs "many" active
    offerings: the selector field key is resolved from the compiled contract
    (branch_selection_field, see _service_selection_field) instead of
    assuming the literal key "servico", so a persona selling products (or a
    catalog of many products) works the same way.
    """
    selection_key = branch_selection_field_key(document)
    node_by_id = document.get("node_by_id") or {}
    owners = {
        str(fact.get("owner_node_id") or "")
        for fact in facts_by_key.get(selection_key) or []
        # graph_compiler_v3._with_confirmable_status always authorizes
        # "needs_confirmation" on the branch selector field -- a service
        # resolved by approximate match stays in that state until the
        # customer confirms, but the branch is already active and its
        # other collected facts already count toward qualification. Titles
        # gated on "known" only silently dropped that branch's name from
        # every summary/interest projection while it was still pending.
        if fact.get("status") in ("known", "needs_confirmation")
    }
    return [
        str((node_by_id.get(anchor) or {}).get("title") or anchor)
        for anchor in active_branch_ids if anchor in owners
    ]


def _commercial_note_projection(
    *,
    document: dict[str, Any],
    active_branch_ids: list[str],
    focused_branch_id: str | None,
    facts_by_key: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Project shared and service-owned facts without flattening the ledger."""
    contracts = document.get("branch_contracts") or {}
    active = list(dict.fromkeys(str(anchor) for anchor in active_branch_ids if anchor))
    selection_key = branch_selection_field_key(document)

    def fact_for(key: str, owner: str) -> dict[str, Any] | None:
        return next(
            (
                fact for fact in facts_by_key.get(key, [])
                if str(fact.get("owner_node_id") or "") == owner
            ),
            None,
        )

    common: dict[str, Any] = {}
    services: dict[str, Any] = {}
    node_by_id = document.get("node_by_id") or {}
    for anchor in active:
        service_facts: dict[str, Any] = {}
        selector_entry: tuple[str, Any] | None = None
        for field in (contracts.get(anchor) or {}).get("fields") or []:
            key = str(field.get("key") or "")
            owner = str(field.get("owner_node_id") or "")
            fact = fact_for(key, owner)
            if not fact or fact.get("status") not in {"known", "unknown", "declined"}:
                continue
            value = fact.get("value") if fact.get("status") == "known" else "desconhecido"
            if key == selection_key and owner == anchor:
                # This branch's own selector fact just restates identity the
                # group's `title` (below) already conveys -- surfacing it as
                # a normal fact produced a noisy raw-slug chip ("chapeacao")
                # duplicating the branch's own title in the header. Held back
                # as a fallback-only entry so an offering whose only known
                # fact IS the selector still shows up in the header instead
                # of silently disappearing.
                if fact.get("status") == "known":
                    value = _render_field_value(field, fact.get("value"))
                selector_entry = (key, value)
                continue
            # A field whose owner is not one of the currently active branches
            # is persona-scoped by construction (every field in a branch's
            # own contract is owned either by that branch or by the persona,
            # never by some other/dropped branch) -- shared regardless of
            # whether every other active branch's contract also happens to
            # redeclare it. Requiring that redeclaration made a real vehicle
            # field (vehicle_color) misfile as owned by only one of two
            # active branches purely because the other branch's own catalog
            # contract was missing that declaration.
            if owner not in active:
                common[key] = value
            else:
                service_facts[key] = value
        if not service_facts and selector_entry:
            service_facts[selector_entry[0]] = selector_entry[1]
        node = node_by_id.get(anchor) or {}
        services[anchor] = {
            "slug": node.get("slug"),
            "title": node.get("title"),
            "facts": service_facts,
        }
    return {
        "version": 1,
        "focused_service_id": focused_branch_id,
        "active_service_ids": active,
        "common_facts": common,
        "services": services,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


_EXPLICIT_UNKNOWN = re.compile(
    r"^\s*(?:n[aã]o\s+sei|n[aã]o\s+tenho\s+certeza|prefiro\s+n[aã]o\s+responder|"
    r"desconhe[cç]o|sem\s+ideia)\s*[.!]?\s*$",
    re.IGNORECASE,
)








def _looks_like_customer_question(message: str) -> bool:
    normalized = _normalized_phrase(message)
    if "?" in str(message or ""):
        return True
    question_prefixes = (
        "como ", "quando ", "onde ", "qual ", "quais ", "quanto ",
        "por que ", "porque ", "posso ", "podem ", "poderia ",
        "voces oferecem ", "voces fazem ", "voces tem ", "tem como ",
        "gostaria de saber ", "queria saber ", "quero saber ", "sera que ",
    )
    return normalized.startswith(question_prefixes)














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




def _question_repetition_max_attempts(contract: dict[str, Any]) -> int:
    repetition = ((contract.get("conversation_policy") or {}).get("question_repetition") or {})
    value = repetition.get("max_attempts", 1)
    return value if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1} else 1


def _assistant_replies(messages: Sequence[dict[str, Any]], limit: int = 4) -> list[str]:
    """The agent's own recent turns, the only baseline repetition compares to."""
    return [
        text
        for row in messages
        if str(row.get("role") or "") == "assistant"
        or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
        if (text := str(row.get("content") or row.get("texto") or "").strip())
    ][-limit:]












def _active_contract_fields(
    document: dict[str, Any], active_branch_ids: list[str], fallback: dict[str, Any],
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    contracts = document.get("branch_contracts") or {}
    for branch_id in active_branch_ids or [str(fallback.get("branch_anchor_node_id") or "")]:
        contract = contracts.get(branch_id) or fallback
        for field in contract.get("fields") or []:
            identity = (str(field.get("key") or ""), str(field.get("owner_node_id") or ""))
            if not identity[0] or identity in seen:
                continue
            seen.add(identity)
            fields.append(field)
    return fields


def _unknown_fields(
    fields: list[dict[str, Any]], facts_by_key: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Fields explicitly exhausted as unknown, even if the graph accepts them."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for field in fields:
        key = str(field.get("key") or "")
        owner = str(field.get("owner_node_id") or "")
        identity = (key, owner)
        if not key or identity in seen:
            continue
        if any(
            str(fact.get("owner_node_id") or "") == owner
            and fact.get("status") == "unknown"
            for fact in facts_by_key.get(key) or []
        ):
            seen.add(identity)
            result.append(field)
    return result


def _dedupe_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for field in fields:
        identity = (
            str(field.get("key") or ""), str(field.get("owner_node_id") or ""),
        )
        if not identity[0] or identity in seen:
            continue
        seen.add(identity)
        result.append(field)
    return result




def _render_fact_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _humanize_field_key(key: str) -> str:
    """Fallback label when a field has no entry in the published field_labels.

    Never let the raw snake_case key (e.g. "modelo_veiculo") reach the
    customer with an underscore in it -- "Modelo veiculo" reads like copy
    instead of a variable name.
    """
    words = [word for word in str(key or "").replace("_", " ").split() if word]
    return " ".join(words).capitalize()


def _enum_option_label(field: dict[str, Any], value: Any) -> str | None:
    """Human alias for a field's declared enum option value.

    graph_compiler_v3._compiled_field_validation preserves
    validation.values = [{value, aliases}] for mode="enum" fields (e.g.
    Aurora's "objective": {"value": "continuar_cuidar_proteger", "aliases":
    ["continuar com o veículo e cuidar bem dele", ...]}). None when the
    field isn't an enum, the value doesn't match a declared option, or the
    matching option has no alias -- callers fall back on their own.
    """
    validation = field.get("validation") or {}
    if str(validation.get("mode") or "").lower() != "enum":
        return None
    for option in validation.get("values") or []:
        if option.get("value") == value:
            aliases = option.get("aliases") or []
            return str(aliases[0]) if aliases else None
    return None


def _render_field_value(field: dict[str, Any], value: Any) -> str:
    """Customer-facing rendering of a fact's value for this field.

    An enum field's stored value is the internal slug used for matching
    (e.g. "continuar_cuidar_proteger"), never meant to be shown verbatim --
    the grounding guard for the natural summary
    A former deterministic summary guard would otherwise force
    the model to literally write that slug to pass validation. Prefer the
    published alias; if an enum value somehow has none, humanize the slug
    like any other field key rather than leak the underscore.
    """
    alias = _enum_option_label(field, value)
    if alias is not None:
        return alias
    if isinstance(value, str) and str((field.get("validation") or {}).get("mode") or "").lower() == "enum":
        return _humanize_field_key(value)
    return _render_fact_value(value)






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
    if deterministic_candidates:
        return str(deterministic_candidates[-1].get("branch_anchor_node_id") or "") or None
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


_EXPLICIT_CONFIRMATIONS = {
    "sim", "isso", "isso mesmo", "correto", "esta correto", "estao corretos",
    "confirmo", "pode seguir", "pode prosseguir", "tudo certo", "ok pode seguir",
}
_EXPLICIT_REJECTIONS = {
    "nao", "nao esta correto", "nao estao corretos", "tem algo errado",
    "quero corrigir", "preciso corrigir",
}
_SOCIAL_RESPONSES = {
    "obrigado", "obrigada", "valeu", "agradeco", "tchau", "ate mais",
    "beleza", "ok", "certo",
}


def _is_explicit_confirmation(message: str) -> bool:
    """Accept only an unequivocal confirmation of the published summary."""
    normalized = _normalized_phrase(message)
    return normalized in _EXPLICIT_CONFIRMATIONS


def _is_explicit_rejection(message: str) -> bool:
    return _normalized_phrase(message) in _EXPLICIT_REJECTIONS


def _is_social_or_non_service_value(message: str) -> bool:
    normalized = _normalized_phrase(message)
    return bool(
        not normalized
        or _is_bare_greeting(message)
        or _is_explicit_confirmation(message)
        or _is_explicit_rejection(message)
        or normalized in _SOCIAL_RESPONSES
        or re.fullmatch(r"\d+(?:[.,]\d+)?", normalized)
    )


def _explicit_change_requested(message: str) -> bool:
    normalized = _normalized_phrase(message)
    return bool(
        _message_explicitly_changes_service(message)
        or re.search(r"\b(?:corrig|alter|muda|troca|ajusta|na verdade|quis dizer)\w*\b", normalized)
    )










def _is_agent_message(row: dict[str, Any]) -> bool:
    return (
        str(row.get("role") or "") == "assistant"
        or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
    )


def _persona_node(document: dict[str, Any]) -> dict[str, Any]:
    return next(
        (node for node in document.get("nodes") or [] if node.get("node_type") == "persona"),
        {},
    )






SYSTEM_PROMPT = (
    "Três camadas, e cada uma manda no que é dela. VOCÊ entende: o que o "
    "cliente quis dizer, tudo o que ele informou de uma vez, com que "
    "confiança, e em que voz responder. O BACKEND prova: evidência "
    "literal, escopo do galho, idempotência e segurança -- ele valida a "
    "sua proposta contra a publicação e substitui o que não puder provar. "
    "O GRAFO manda no conteúdo: serviços, perguntas, regras, identidade e "
    "copy. Proponha com convicção dentro da sua camada e não invente nada "
    "das outras duas.\n\n"

    "Antes de propor qualquer mutação, descreva a interação atual em "
    "interaction_observation: continue_current, new_demand, "
    "post_completion_question, courtesy_close, post_sale_operation ou "
    "unclear. Inclua evidence_span literal e confiança. Isso é apenas "
    "observação: o backend reconcilia com a jornada persistida e decide "
    "journey_action. Agradecimento, encerramento e dúvida depois da "
    "conclusão não são nova demanda; pedido operacional de pós-venda "
    "também não abre jornada.\n\n"

    "Observe serviços antes de qualquer outro campo. Registre cada "
    "hipótese em service_observations com anchor publicado, "
    "evidence_span literal, intenção observada e confiança. "
    "service_operations e branch_action existem apenas por "
    "compatibilidade e nunca autorizam mutação: descreva seleção, "
    "adição, troca ou remoção somente quando a intenção estiver "
    "literalmente presente, preserve o foco informado no contexto, e "
    "saiba que o resolvedor do backend substitui essas propostas pela "
    "resolução comprovada. Nunca reutilize um span consumido ou "
    "reservado de serviço como evidência de outro campo.\n\n"

    "Leia a mensagem inteira do cliente antes de responder. Capture em "
    "extracted_facts todo campo reconhecível mencionado nela, mesmo que "
    "não seja o campo que você acabou de perguntar -- um cliente "
    "frequentemente responde algo diferente do que foi pedido, ou "
    "adianta mais de uma informação na mesma mensagem. Quando ele "
    "escrever um valor abreviado, colado ou informal (\"fordka\" para "
    "\"Ford Ka\"), interprete com a inteligência que uma pessoa teria no "
    "WhatsApp: se a leitura mais provável for razoavelmente clara, "
    "extraia o fato com essa interpretação, sem parar a conversa para "
    "confirmar o óbvio.\n\n"

    "Em evidence_span, recorte exatamente o trecho da mensagem que "
    "sustenta o fato -- as mesmas palavras, na mesma ordem, sem "
    "reescrever, traduzir nem recapitalizar. O valor em value pode ser a "
    "sua leitura normalizada; o span é a prova, e o backend precisa "
    "reencontrá-lo na mensagem original. Em confidence, publique o "
    "quanto você realmente acredita naquela leitura: acima do piso do "
    "campo o backend grava direto e a conversa segue; abaixo dele o "
    "cliente terá de confirmar antes. Não infle e não se encolha por "
    "precaução -- pedir confirmação do óbvio atrapalha mais do que "
    "protege.\n\n"

    "Nunca pergunte o que você já sabe. fatos_conhecidos e shared_memory "
    "trazem tudo o que esse lead já informou, nesta conversa ou em "
    "pedidos anteriores. Usar isso é a diferença entre um atendimento e "
    "um formulário: se o dado está lá, use direto; se ele adiantou dois "
    "ou três campos numa frase só, registre todos e pergunte apenas o "
    "próximo que realmente falta.\n\n"

    "Respeite o tempo do cliente. Silêncio não é objeção, nem motivo "
    "para reperguntar, cobrar retorno ou encerrar o atendimento. Uma "
    "informação pendente por mensagem, e só depois que ele responder. "
    "Se ele voltar horas depois, retome de onde parou, sem cobrança e "
    "sem recomeçar do zero.\n\n"

    "Ao primeiro sinal mínimo de intenção -- uma dúvida solta, um "
    "serviço citado de passagem, um incômodo relatado -- responda esse "
    "sinal: resolva a dúvida com o que o grafo publica, ou pergunte o "
    "que ele quer conhecer ou melhorar. Nunca devolva um turno sem "
    "conteúdo e nunca deixe a conversa parada esperando que o cliente se "
    "explique melhor sozinho.\n\n"

    "Você propõe a conversa; o backend apenas prova o GraphRAG "
    "publicado. Use somente nodes/chunks do pacote, preserve o galho em "
    "respostas curtas, cite evidence_span literal e retorne "
    "exclusivamente o JSON Schema fornecido. Se a resposta não estiver "
    "no pacote que você recebeu, não preencha a lacuna de memória: cite "
    "o que existe e deixe claro que falta base -- o backend tem um passo "
    "de reparo que busca de novo, mais fundo, a partir disso. Se nem "
    "assim houver fonte, pergunte ao cliente, com uma pergunta curta e "
    "específica, em vez de escolher no achismo.\n\n"

    "Você é um SDR de verdade conversando por WhatsApp, não um "
    "formulário. Sempre que extrair um campo diferente do que estava "
    "perguntando, reconheça esse dado com suas próprias palavras antes "
    "de retomar a pergunta pendente. Nunca ignore silenciosamente um "
    "dado que o cliente acabou de dar, e só reconheça o que realmente "
    "esteja em extracted_facts deste turno ou já conhecido em "
    "factual_ledger -- nunca finja ter entendido algo que não foi "
    "extraído. Evite as palavras 'confirmado', 'reservado', 'agendado' "
    "e 'fechado' fora do encerramento real da qualificação, pois "
    "indicam conclusão do atendimento.\n\n"

    "Prefira respostas curtas, do tamanho de uma mensagem real de "
    "WhatsApp -- evite parágrafos longos ou explicações que o cliente "
    "não pediu. Calibre o tamanho pela forma como o próprio cliente "
    "escreve: se ele manda mensagens curtas e diretas, responda "
    "igualmente enxuto; só se estenda quando ele mesmo escrever "
    "mensagens longas e detalhadas. Peça no máximo uma informação "
    "pendente por mensagem, salvo duas muito relacionadas. Você tem "
    "liberdade para usar seu próprio critério dentro do que o grafo "
    "autoriza -- não existe roteiro rígido de frases prontas nem "
    "obrigação de soar formal.\n\n"

    "Nunca repita uma frase que você já disse neste atendimento -- nem "
    "literal, nem quase palavra por palavra, nem a mesma construção "
    "turno após turno. Isso vale para perguntas, para reconhecimentos "
    "('entendi', 'perfeito'), para pedidos de confirmação e para o "
    "resumo final. Confira recent_messages, que inclui suas próprias "
    "respostas, antes de escrever a reply, e varie a formulação mesmo "
    "quando a pergunta de fundo (next_question_node_id) continuar a "
    "mesma. Um prefixo vazio como 'Certo' não conta como variação, e "
    "uma mensagem que só reconhece, sem perguntar nem informar nada, "
    "não é um turno -- é um silêncio disfarçado.\n\n"

    "Quando precisar retomar algo já dito, siga esta ordem. Primeiro, "
    "diga de outro jeito: outra formulação da mesma pergunta, "
    "reconhecendo antes o que o cliente trouxe de novo. Se já tentou de "
    "outra forma e ainda não deu, assuma com naturalidade que não "
    "captou e registre o campo como desconhecido, sem culpar o cliente. "
    "Só em último caso pare de perguntar aquele campo e siga para o "
    "próximo assunto pendente. Fora dessa terceira situação, toda "
    "mensagem do cliente merece resposta com conteúdo real neste turno "
    "-- não devolva silêncio.\n\n"

    "Quando a resposta for genuinamente ambígua entre dois ou mais "
    "produtos parecidos, ou quando um termo tiver duas leituras "
    "plausíveis, não escolha no achismo: peça um esclarecimento curto e "
    "natural, reconhecendo antes o que ele disse (\"Entendi, temos "
    "algumas opções de polimento -- qual encaixa melhor: X ou Y?\" ou "
    "\"Fordka é Ford Ka, certo?\"). Nessa situação não dê a entender que "
    "o cliente foi confuso; a admissão de não ter entendido é para "
    "quando você realmente falhou em ler o campo, não para ambiguidade "
    "do catálogo.\n\n"

    "conversation_policy.question_repetition.max_attempts informa "
    "quantas retomadas são permitidas além da pergunta inicial (somente "
    "zero ou uma). Na primeira ignorada, reconheça ou responda o "
    "conteúdo novo antes de retomar a pergunta com uma ponte contextual "
    "substantiva. Esgotado o orçamento, o backend marca o campo como "
    "unknown e segue ou encaminha; nunca faça uma terceira emissão. Uma "
    "resposta explícita de que o cliente não sabe pode gerar unknown "
    "imediatamente. Se ele fornecer o dado espontaneamente mais tarde, "
    "extraia normalmente como known para substituir unknown.\n\n"

    "handoff_requested só pode ser true quando TODOS os campos "
    "obrigatórios do galho atual já estão em factual_ledger -- nunca "
    "proponha handoff assim que colher só o primeiro campo (por "
    "exemplo, o nome) se o galho ainda exigir outros depois dele. "
    "Depois de colher um campo, a próxima ação é sempre perguntar o "
    "próximo campo pendente do galho, nunca encerrar o turno oferecendo "
    "encaminhamento antes disso.\n\n"

    "tempo_desde_ultima_mensagem indica quanto tempo se passou desde a "
    "última mensagem do cliente. Um intervalo de algumas horas é normal "
    "no WhatsApp -- o cliente pode ter ficado ocupado e voltado no "
    "mesmo dia, isso não significa que o assunto mudou. Só trate a "
    "mensagem como início de conversa nova quando o intervalo passar de "
    "~3-4 horas, e mesmo assim não assuma que o assunto ou a urgência "
    "de antes ainda valem.\n\n"

    "journey traz sequence e state. sequence maior que 1 significa que "
    "este cliente já foi atendido antes: você não está descobrindo, "
    "está continuando. Use shared_memory -- fatos do perfil, pedidos "
    "anteriores e seus desfechos -- para não refazer a descoberta; "
    "confirme apenas o que muda de um pedido para o outro, que é o "
    "serviço desta vez; e trate dúvida depois de um pedido concluído "
    "como suporte ao que já foi feito, não como nova qualificação.\n\n"

    "fatos_conhecidos lista tudo que já se sabe sobre esse cliente, "
    "cada um com origem 'esta_conversa' ou 'anterior'. Um fato "
    "'anterior' com carregado_do_pedido_anterior=true segue a política "
    "carry_over do contrato publicado e pertence ao perfil do lead: use "
    "direto, sem perguntar de novo e sem pedir confirmação, inclusive "
    "para chamar o cliente pelo nome. Qualquer outro fato 'anterior' "
    "(data, janela ou resultado de atendimento passado) pode "
    "personalizar a conversa, mas sempre confirme antes de seguir com "
    "base nele -- o veículo pode ter mudado, o interesse pode ser "
    "outro. Isso vale ainda mais quando reconfirmacao_pendente for true "
    "(a IA acabou de ser reativada por um humano), exceto para os fatos "
    "carregado_do_pedido_anterior=true.\n\n"

    "Em operational_mode post_qualification_support, use esses fatos "
    "apenas para apoiar o pedido atual: responda saudação e dúvidas sem "
    "reiniciar o roteiro, sem perguntar serviço de novo e sem pedir "
    "reconfirmação por conta própria. Só altere o pedido quando a "
    "mensagem atual pedir correção ou troca de forma explícita. Em "
    "operational_mode confirmation, responda dúvidas antes de retomar a "
    "confirmation_question publicada; o backend é o único dono da "
    "transição e do handoff.\n\n"

    "Quando todos os campos obrigatórios já são conhecidos e chega a "
    "hora de confirmar o pedido, escreva você mesma o resumo, com suas "
    "palavras -- não existe texto fixo para copiar. Mencione "
    "naturalmente cada dado coletado (sem rótulos tipo \"Nome:\" nem "
    "lista com ponto e vírgula) e termine com uma pergunta curta "
    "pedindo confirmação. Não use \"confirmado\", \"agendado\" ou \"fechado\" "
    "nesse resumo: o pedido só fecha depois que o cliente responder que "
    "sim.\n\n"
)



def _carry_over_field_keys(document: dict) -> set[str]:
    """Fields que atravessam o fim de um pedido, segundo o contrato compilado.

    Sem lista de nomes no codigo: quem decide e o `carry_over` que o compilador
    grava por origem do field (identidade da persona atravessa, dado do pedido
    nao) e que o grafo pode sobrescrever campo a campo.
    """
    keys: set[str] = set()
    for contract in (document.get("branch_contracts") or {}).values():
        for field in (contract or {}).get("fields") or []:
            if isinstance(field, dict) and field.get("carry_over"):
                key = str(field.get("key") or "").strip()
                if key:
                    keys.add(key)
    return keys




def _agent_identity_prompt(document: dict[str, Any]) -> str:
    """Who the agent says she is, authored by the persona graph.

    Until 2026-08-19 the name existed only inside the published greeting, so
    the model itself never knew it: any turn that was not a greeting -- including
    a customer plainly asking "qual o seu nome?" -- had nothing to answer with.
    The name stays graph-owned (`AGENTS.md` §26 forbids it in code); this only
    puts what the graph already publishes in front of the model.
    """
    persona = _persona_node(document) or {}
    identity = ((persona.get("data") or {}).get("agent_identity") or {})
    name = str(identity.get("name") or "").strip()
    if not name:
        return ""
    role = str(identity.get("role") or "").strip()
    company = str(identity.get("company") or "").strip()
    short = str(identity.get("company_short") or "").strip() or company
    lead = f"Você se chama {name}"
    if role and company:
        lead += f" e é {role} da {company}"
    elif company:
        lead += f", da {company}"
    return (
        f"{lead}. Esse é o seu nome e você o usa quando se apresenta ou quando "
        f"o cliente pergunta com quem está falando. Você não é a empresa: "
        f"{short} é o negócio que você atende, você é a pessoa que fala com o "
        f"cliente. Não repita a apresentação a cada mensagem -- só quando fizer "
        f"sentido, como numa conversa de verdade."
    )




def _post_sale_route(document: dict[str, Any]) -> str:
    persona = _persona_node(document) or {}
    policy = ((persona.get("data") or {}).get("conversation_policy") or {})
    return str(policy.get("post_sale_operation_route") or "HUMAN").upper()


def _seed_carried_facts(
    ledger: dict, document: dict, previous_journey: dict,
    *, persona_id: str = "", lead_ref: int = 0,
) -> dict:
    """Semeia no ledger vazio do ciclo novo os fatos herdados do lead.

    Eles entram com `carried_from_journey`, entao `_known_facts_payload` os
    rotula como `origem: "anterior"` e o prompt ja manda confirmar antes de
    usar -- e a diferenca entre reperguntar o nome e conferi-lo.

    A busca cobre o historico completo do lead (toda jornada/pedido ja
    registrado), nao so a jornada anterior imediata -- um ponteiro de uma
    jornada so perdia o fato assim que uma segunda jornada fechasse antes
    do campo ser respondido de novo (confirmado ao vivo 2026-08-18: nome
    do cliente sumiu na terceira jornada do mesmo dia). Jornadas/pedidos
    ja registrados sao a fonte de verdade -- ver
    conversation_carry_over_facts_by_lead_v1.
    """
    keys = _carry_over_field_keys(document)
    previous_id = str(previous_journey.get("id") or "")
    if not keys or not previous_id or (ledger.get("facts") or {}):
        return ledger
    try:
        rows = supabase_client.get_lead_carry_over_facts(
            persona_id, lead_ref, sorted(keys),
        )
    except Exception:
        # Herdar e uma melhoria de conversa, nunca um bloqueio de turno.
        return ledger
    carried = {}
    grouped: dict[str, list[dict]] = {}
    carry_fields = {
        str(field.get("key") or ""): field
        for contract in [
            document.get("common_contract") or {},
            *((document.get("branch_contracts") or {}).values()),
        ]
        for field in contract.get("fields") or []
        if field.get("carry_over")
    }
    for row in rows:
        key = str(row.get("field_key") or "")
        if key not in keys or str(row.get("status") or "") != "known":
            continue
        field = carry_fields.get(key) or {}
        semantic_type = str((field.get("validation") or {}).get("semantic_type") or "")
        if (
            semantic_type == "human_full_name"
            and not graph_proof_checker_v3.is_human_full_name(row.get("value_json"))
        ):
            continue
        fact = {
            **row, "value": row.get("value_json"), "fact_id": row.get("id"),
            "carried_from_journey": previous_id,
            "metadata": {
                **dict(row.get("metadata") or {}),
                "origin_journey_id": str(row.get("journey_id") or previous_id),
                "reuse_policy": "carry_over",
                "policy_version": shared_lead_memory.POLICY_VERSION,
            },
        }
        carried.setdefault(key, fact)
        grouped.setdefault(key, []).append(fact)
    if not carried:
        return ledger
    seeded = dict(ledger)
    seeded["facts"] = {**carried, **(ledger.get("facts") or {})}
    seeded["facts_by_key"] = {**grouped, **(ledger.get("facts_by_key") or {})}
    return seeded


def _journey_operational_mode(journey_state: str) -> str:
    if journey_state == "awaiting_confirmation":
        return "confirmation"
    if journey_state in {"qualified_confirmed", "handed_off", "converted"}:
        return "post_qualification_support"
    return "collection"


def _journey_has_confirmed_conversion(
    journey: dict[str, Any], outcomes: Sequence[dict[str, Any]],
) -> bool:
    """Whether the current/latest request already has a commercial booking.

    `converted_at` is the journey-level canonical stamp.  The outcomes check
    keeps compatibility with projections where only `sales_conversions` was
    returned.  A conversion from an older request must not lock a newer one.
    """
    if journey.get("converted_at"):
        return True
    journey_id = str(journey.get("id") or "")
    if not journey_id:
        return False
    inactive = {"cancelled", "reverted", "refunded", "void"}
    return any(
        str(row.get("journey_id") or "") == journey_id
        and str(row.get("conversion_type") or "") in {
            "appointment_booked", "purchase", "contract_signed",
        }
        and str(row.get("status") or "completed").lower() not in inactive
        for row in outcomes
    )


def build_context(
    *, persona_slug: str, lead_ref: int, message: str, message_id: str | None,
    publication_id: str | None = None,
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
        batch = supabase_client.get_graph_turn_context_batch_v4(
            persona_id=str(persona["id"]), lead_ref=lead_ref, message_limit=8,
        )
    except Exception:
        # Rolling-deploy compatibility while migration 114 is being applied.
        batch = {}
    context_batch_ms = round((time.perf_counter() - context_batch_started) * 1000, 3)
    if publication_id:
        # Validator shadow runs must not reuse the active-publication batch:
        # its ledger/facts belong to another graph version.
        batch = {}
        publication = supabase_client.get_graph_publication_by_id(publication_id)
        if not publication or str(publication.get("persona_id") or "") != str(persona["id"]):
            raise PermissionError("publication does not belong to requested persona")
        if publication.get("status") not in {"compiled", "active"}:
            raise RuntimeError("shadow GraphRAG publication is not compiled")
    else:
        publication = batch.get("publication") or supabase_client.get_active_graph_publication(str(persona["id"]))
    if not publication:
        raise RuntimeError("active GraphRAG v3 publication not found")
    document = publication.get("document_json") or {}
    messages = batch.get("messages") or supabase_client.get_messages(str(lead_ref), limit=8) or []
    # The buffer can canonically coalesce several physical messages. Use that
    # ordered text for this decision/proof without rewriting persisted history
    # or changing the canonical inbound identity.
    messages = _overlay_canonical_inbound(messages, message, message_id)
    shared_memory = shared_lead_memory.project_shared_lead_memory(
        batch=batch, document=document, messages=messages,
    )
    # A shadow session is a clean synthetic conversation against one compiled
    # candidate. Never import active-publication ledger/fact state into it.
    ledger = None if publication_id else (batch.get("ledger") or None)
    if ledger:
        ledger["facts_by_key"] = _facts_by_key(batch.get("facts") or [])
    ledger = ledger or (None if publication_id else supabase_client.get_conversation_ledger(str(persona["id"]), lead_ref)) or {
        "active_branch_node_id": None, "publication_id": publication["id"],
        "graph_checksum": publication["checksum"], "revision": 0,
        "asked_question_node_ids": [], "facts": {}, "facts_by_key": {},
    }
    journey = ({} if publication_id else batch.get("journey")) or (None if publication_id else supabase_client.get_current_conversation_journey(
        str(persona["id"]), lead_ref,
    )) or {}
    latest_journey: dict[str, Any] = {}
    if not journey:
        latest_journey = ({} if publication_id else supabase_client.get_latest_conversation_journey(
            str(persona["id"]), lead_ref,
        )) or {}
        if latest_journey and latest_journey.get("is_current") is False:
            journey = {
                "id": None,
                "sequence": int(latest_journey.get("sequence") or 0) + 1,
                "state": "collecting",
                "opening_reason": "new_demand_after_closed_request",
                "previous_journey_id": latest_journey.get("id"),
                "metadata": {},
            }
            # O pedido seguinte nasce com ledger proprio e zero fatos, entao o
            # SDR reperguntaria o nome a cada ciclo. Os fields que o contrato
            # marca como `carry_over` atravessam; servico e campos do galho nao
            # -- o pedido novo comeca em branco de proposito.
            ledger = _seed_carried_facts(
                ledger, document, latest_journey,
                persona_id=str(persona["id"]), lead_ref=lead_ref,
            )
    lead_conversation_state = ((lead.get("metadata") or {}).get("conversation_state") or {})
    journey_state = str(
        journey.get("state") or lead_conversation_state.get("sdr_state") or "collecting"
    )
    completion_journey = latest_journey or journey
    has_confirmed_conversion = _journey_has_confirmed_conversion(
        completion_journey, shared_memory.journey_outcomes,
    )
    pending_reconfirmation = bool(
        (lead.get("metadata") or {}).get("pending_reconfirmation")
    )
    operational_mode = _journey_operational_mode(journey_state)
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
    active_branch, active_branches, focus_derived_in_memory = _safe_active_focus(
        active_branch, persisted_active_branches,
    )
    ledger_id = str(ledger.get("id") or "")
    completed_branch_node_ids: list[str] = []
    if ledger_id and operational_mode == "post_qualification_support":
        branch_states = supabase_client.get_ledger_branch_states(ledger_id)
        completed_branch_node_ids = [
            anchor for anchor, state in branch_states.items() if state == "completed"
        ]
        if not completed_branch_node_ids and persisted_active_branches:
            # Grandfather: this journey was already handed off before
            # per-branch confirmation tracking existed (migration 128), so
            # nothing is marked 'completed' yet. Whatever was active coming
            # into this turn is what the customer already confirmed -- only
            # an offering added from here on should ask for its own
            # confirmation. One-time; idempotent on every later turn once the
            # rows exist.
            supabase_client.mark_ledger_branches_completed(
                ledger_id, persisted_active_branches,
            )
            completed_branch_node_ids = list(persisted_active_branches)
    common_contract = document.get("common_contract") or {}
    active_contract = (
        (document.get("branch_contracts") or {}).get(active_branch) or {}
        if active_branch else common_contract
    )
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
    pending_fields = graph_proof_checker_v3.askable_pending_fields(
        active_contract, ledger.get("facts") or {},
    )
    missing = [field["key"] for field in graph_proof_checker_v3.pending_fields(active_contract, ledger.get("facts") or {})]
    pending_field = pending_fields[0] if pending_fields else {}
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
    service_resolution = _resolve_service_operations(
        document, message,
        active_branch_node_id=active_branch,
        active_branch_node_ids=active_branches,
        contract=active_contract,
        asked_question_node_ids=ledger.get("asked_question_node_ids") or [],
    )
    service_resolution = _reserve_message_for_pending_field(
        service_resolution, pending_field_answer=pending_field_answer,
        message=message, active_branch_node_id=active_branch,
        active_branch_node_ids=active_branches,
    )
    # Greeting is a transversal current-turn intent. Historical replies,
    # handoffs and long pauses must never suppress it.
    deterministic_candidates = _routable_deterministic_candidates(
        message,
        _deterministic_branch_candidates(document, message),
        pending_field_answer=pending_field_answer,
    )
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
        faq_candidates = _rank_faq_candidates(
            interrogative_clause,
            faq_rows,
            context_hint=_faq_context_hint(messages),
        )
        faq_selection_method = "ranked_candidates_for_model"
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
    faq_rows_by_chunk = {
        str(row.get("chunk_id") or row.get("id") or ""): row for row in faq_rows
    }
    ranked_faq_chunks = []
    for candidate in faq_candidates[:RAG_FAQ_CHUNK_RESERVE]:
        row = faq_rows_by_chunk.get(str(candidate.get("chunk_id") or ""))
        if not row:
            continue
        chunk = {
            **row,
            "source_node_id": str(
                row.get("faq_node_id") or row.get("source_node_id") or ""
            ),
            "chunk_kind": "faq",
            "hybrid_score": float(row.get("faq_score") or 1),
        }
        if chunk.get("chunk_id") and chunk.get("source_node_id"):
            ranked_faq_chunks.append(chunk)
    merged = {
        str(row.get("chunk_id") or row.get("id")): row
        for row in [*rows, *structural, *ranked_faq_chunks]
    }
    required_structural = _required_structural_chunks(structural)
    reserved = ranked_faq_chunks
    reserved_ids = {
        str(row.get("chunk_id") or row.get("id")) for row in reserved
    }
    optional_chunk_slots = _optional_retrieval_chunk_slots(
        required_structural, reserved,
    )
    structural_ids = {
        str(row.get("chunk_id") or row.get("id")) for row in required_structural
    }
    selected = (
        _mmr(
            [
                row for key, row in merged.items()
                if key not in structural_ids and key not in reserved_ids
            ],
            optional_chunk_slots,
        )
        if optional_chunk_slots > 0 else []
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
        "focus_derived_in_memory": focus_derived_in_memory,
        "common_contract": common_contract,
        "pending_field": None,
        "askable_fields": pending_fields,
        "missing_fields": missing,
        "confirmation_templates": document.get("confirmation_templates") or {},
        "service_resolution_policy": document.get("service_resolution_policy") or {},
        "post_sale_operation_route": _post_sale_route(document),
        "short_expected_answer": short_expected_answer,
        "pending_field_branch_resolution_suppressed": pending_field_answer,
        "global_branch_search_executed": not suppress_global_branch_search,
        "deterministic_branch_match": bool(deterministic_candidates),
        "service_resolution": service_resolution,
        "deterministic_branch_resolution": (
            next(
                (
                    item for item in deterministic_candidates
                    if item.get("branch_anchor_node_id")
                    == service_resolution.get("focused_branch_node_id")
                ),
                None,
            )
        ),
        "retrieval_branch_node_id": retrieval_branch,
        "interrogative_clause": interrogative_clause or None,
        "faq_candidates": faq_candidates,
        "selected_faq_node_id": None,
        "selected_faq_chunk_id": None,
        "faq_selection_method": faq_selection_method,
        "faq_deferral_reason": None,
        "branch_candidates": _evidenced_branch_candidates(candidates),
        "possible_switches": possible_switches,
        "journey_state": journey_state,
        "journey_sequence": int(journey.get("sequence") or 1),
        "operational_mode": operational_mode,
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
    # Identity leads the prompt: the agent has to know who she is before any
    # rule about how she behaves. Authored by the persona graph, never here.
    identity = _agent_identity_prompt(document)
    prompt = f"{identity}\n\n{SYSTEM_PROMPT}" if identity else SYSTEM_PROMPT
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
            "branch_anchor_node_id": anchor,
            "slug": document["node_by_id"][anchor]["slug"], "label": document["node_by_id"][anchor]["title"]
        } for anchor in document.get("branch_anchors") or []],
        active_branch_node_id=active_branch,
        active_branch_node_ids=active_branches,
        completed_branch_node_ids=completed_branch_node_ids, ledger_id=ledger_id or None,
        active_path_checksum=((document.get("coordinates") or {}).get(active_branch) or {}).get("path_checksum"),
        branch_node_ids=contract.get("closure_node_ids") or [], graph_contract=contract,
        publication_id=publication["id"], runtime_version=RUNTIME_VERSION, retrieval_trace=trace,
        known_facts=_known_facts_payload(
            ledger.get("facts_by_key") or ledger.get("facts") or {}, message_id,
        ),
        time_since_last_client_message=_time_since_last_client_message(messages, message_id),
        pending_reconfirmation=bool((lead.get("metadata") or {}).get("pending_reconfirmation")),
        journey_id=str(journey.get("id") or "") or None,
        journey_sequence=int(journey.get("sequence") or 1),
        journey_state=journey_state,
        pending_field_key=None,
        pending_question_node_id=None,
        last_handoff={
            "at": journey.get("handed_off_at"),
            "reason": (journey.get("metadata") or {}).get("handoff_reason")
            or (lead.get("metadata") or {}).get("handoff_reason"),
        },
        operational_mode=operational_mode,
        shared_memory=shared_memory,
        post_completion_state={
            "has_terminal_journey": str(
                completion_journey.get("state") or journey_state
            ) in {
                "qualified_confirmed", "handed_off", "converted", "closed"
            },
            "has_confirmed_conversion": has_confirmed_conversion,
            "latest_journey_sequence": int(journey.get("sequence") or 1),
            "latest_journey_state": str(
                completion_journey.get("state") or journey_state
            ),
        },
    )
















def _turn_publication(context: ConversationContext) -> dict[str, Any]:
    """Load the immutable publication captured at turn start.

    The active fallback exists only for offline/rolling QA fixtures that lack
    the by-ID repository method. Production always fails closed.
    """
    try:
        publication = supabase_client.get_graph_publication_by_id(
            str(context.publication_id or "")
        )
    except (KeyError, RuntimeError):
        publication = None
    if publication:
        return publication
    runtime = (os.environ.get("ENV") or os.environ.get("ENVIRONMENT") or "").lower()
    if runtime == "production":
        raise RuntimeError("turn-pinned GraphRAG publication not found")
    persona = supabase_client.get_persona(context.persona_slug) or {}
    publication = supabase_client.get_active_graph_publication(
        str(persona.get("id") or "")
    ) or {}
    if str(publication.get("id") or "") != str(context.publication_id or ""):
        raise RuntimeError("turn-pinned GraphRAG publication not found")
    return publication






def _confirmation_capability(confirmation: dict[str, Any]) -> str:
    return str(
        confirmation.get("capability") or confirmation.get("kind") or "common_fact"
    )






def _with_structural_proof_audit(
    context: ConversationContext,
    decision: ConversationDecision,
    response: AgentResponse,
) -> AgentResponse:
    message = _latest_user_message(context)
    resolver = context.retrieval_trace.get("service_resolution") or {}
    state = response.cart_state
    active_branch = str(state.get("active_branch_node_id") or "") or None
    service_fact = (state.get("facts") or {}).get("servico") or {}
    referential_service_values = {
        _normalized_phrase(value)
        for service in context.available_services
        for value in (service.get("slug"), service.get("label"))
        if value
    } | ({_normalized_phrase(active_branch)} if active_branch else set())
    service_is_referential = bool(
        _normalized_phrase(service_fact.get("value")) in referential_service_values
    )
    repetition = response.proof.get("repetition_audit") or {}
    repetition_action = response.proof.get("repetition_action") or (
        "allowed" if repetition.get("passed", True) else "quality_failure_recorded"
    )
    next_state = str(
        state.get("sdr_state")
        or ("handed_off" if response.handoff_required else context.journey_state)
    )
    proof = {
        **response.proof,
        "intent_audit": {
            "greeting": _is_greeting(message),
            "bare_greeting": _is_bare_greeting(message),
            "explicit_confirmation": _is_explicit_confirmation(message),
            "explicit_change": _explicit_change_requested(message),
            "resolved_intent": decision.intent,
        },
        "service_resolution": {
            **resolver,
            "resolved": bool(
                active_branch
                and service_fact.get("status") == "known"
                and str(service_fact.get("owner_node_id") or "") == active_branch
                and service_is_referential
            ),
            "branch_anchor_node_id": active_branch,
            "value": service_fact.get("value"),
            "path_checksum": (
                response.proposal.branch_path_checksum
                if response.proposal else context.active_path_checksum
            ),
            "method": (
                str(resolver.get("resolution_method"))
                if resolver.get("resolution_method")
                else "retained_graph_fact"
                if service_fact else "none"
            ),
            "rejected_non_service_value": bool(
                _is_social_or_non_service_value(message)
                and not context.retrieval_trace.get("deterministic_branch_resolution")
            ),
        },
        "journey_transition": {
            "journey_id": context.journey_id,
            "sequence": context.journey_sequence,
            "from": str(context.journey_state),
            "to": next_state,
            "operational_mode": str(context.operational_mode),
        },
        "confirmation_state": response.proof.get("confirmation_state") or next_state,
        "repetition_action": repetition_action,
    }
    return response.model_copy(update={"proof": proof})


def _interaction_observation(
    context: ConversationContext, model_observation: dict[str, Any] | None,
) -> tuple[InteractionKind, str, float]:
    raw = model_observation or {}
    proposal = raw.get("proposal") if isinstance(raw.get("proposal"), dict) else raw
    observed = (
        proposal.get("interaction_observation")
        if isinstance(proposal, dict) else None
    ) or {}
    kind = _coerce_interaction_kind(observed.get("kind"))
    span = str(observed.get("evidence_span") or "").strip()
    confidence = float(observed.get("confidence") or 0)
    message = _latest_user_message(context)
    if not _interaction_is_grounded(kind, span, confidence, message):
        return InteractionKind.UNCLEAR, span, confidence
    return kind, span, confidence


def _coerce_interaction_kind(value: Any) -> InteractionKind:
    try:
        return InteractionKind(str(value or "unclear"))
    except ValueError:
        return InteractionKind.UNCLEAR


def _interaction_is_grounded(
    kind: InteractionKind, span: str, confidence: float, message: str,
) -> bool:
    return kind is InteractionKind.UNCLEAR or bool(
        confidence >= 0.65 and span and span in message
    )


def _resolve_journey_action(
    context: ConversationContext, kind: InteractionKind,
) -> JourneyAction:
    terminal = bool(context.post_completion_state.get("has_terminal_journey"))
    if context.journey_id is None and not terminal:
        return JourneyAction.OPEN
    if terminal:
        if context.post_completion_state.get("has_confirmed_conversion"):
            return JourneyAction.NONE
        if kind is InteractionKind.NEW_DEMAND:
            return JourneyAction.OPEN
        # Confirmed live 2026-08-19 (lead 26, publication v64): once a journey
        # closed, every later message came back from the model as `unclear` --
        # including "quero chapeacao no meu charro" and "Quero pintar o meu
        # carro" -- so the customer received the same no-journey fallback
        # sentence eight times in a row and could never start a second order.
        # Opening a journey must not depend solely on the model's self-report
        # about its own intent. When the published graph itself resolves the
        # message to a service branch, that is objective evidence of a new
        # demand, so honour it. Courtesy closes and post-sale operations still
        # never open a journey: they carry no branch of their own.
        service_resolution = context.retrieval_trace.get("service_resolution") or {}
        if kind is InteractionKind.UNCLEAR and (
            context.retrieval_trace.get("deterministic_branch_match")
            or bool(service_resolution.get("candidate"))
        ):
            return JourneyAction.OPEN
        return JourneyAction.NONE
    return JourneyAction.CONTINUE


def _without_journey_mutation(
    context: ConversationContext,
    decision: ConversationDecision,
    response: AgentResponse,
    kind: InteractionKind,
) -> tuple[ConversationDecision, AgentResponse, list[dict[str, Any]]]:
    rejected = []
    accepted = response.proof.get("accepted_facts") or []
    if accepted:
        rejected.append({
            "component": "facts", "reason": "journey_action_none",
            "count": len(accepted),
        })
    proposal = response.proposal.model_copy(update={
        "branch_action": BranchAction.NONE,
        "branch_anchor_node_id": None,
        "branch_path_checksum": None,
        "extracted_facts": [],
        "next_question_node_id": None,
        "qualification_complete": False,
        "handoff_requested": False,
    }) if response.proposal else None
    response = response.model_copy(update={
        "cart_state": dict(context.cart),
        "handoff_required": False,
        "proposal": proposal,
        "proof": {
            **response.proof,
            "model_proposal_errors": response.proof.get("errors") or [],
            "valid": True, "errors": [], "fallback_used": False,
            "reply_policy": "model_owned_no_journey",
            "accepted_facts": [], "missing_fields": [],
            "next_question_node_id": None, "qualification_complete": False,
            "confirmation_state": "no_journey",
        },
    })
    route = _no_journey_route(context, kind)
    decision = decision.model_copy(update={
        "classifier": "graph_interaction_policy_v4", "intent": kind.value,
        "route": route,
        "handoff_reason": (
            "post_sale_operation" if route is ConversationRoute.HUMAN else None
        ),
    })
    response = response.model_copy(update={"role": route})
    return decision, response, rejected


def _no_journey_route(
    context: ConversationContext, kind: InteractionKind,
) -> ConversationRoute:
    if context.post_completion_state.get("has_confirmed_conversion"):
        resolution = context.retrieval_trace.get("service_resolution") or {}
        if (
            resolution.get("candidate")
            or resolution.get("matches")
            or resolution.get("operations")
            or _has_explicit_service_intent(_latest_user_message(context))
        ):
            return ConversationRoute.HUMAN
    if kind is not InteractionKind.POST_SALE_OPERATION:
        return ConversationRoute.SDR
    try:
        return ConversationRoute(str(
            context.retrieval_trace.get("post_sale_operation_route") or "HUMAN"
        ).upper())
    except ValueError:
        return ConversationRoute.HUMAN


def _apply_journey_policy(
    context: ConversationContext,
    decision: ConversationDecision,
    response: AgentResponse,
    *, model_observation: dict[str, Any] | None,
) -> tuple[ConversationDecision, AgentResponse]:
    # The contract probe is phase one of a two-phase decision. It deliberately
    # has no model interaction observation yet, so applying terminal-journey
    # policy here would coerce it to unclear/no_journey before the model gate.
    # The reconciled proposal returns through this function on phase two.
    if (
        decision.intent == "await_model_proposal"
        or response.proof.get("mode") == "contract_probe"
    ):
        return decision, response
    kind, evidence_span, confidence = _interaction_observation(
        context, model_observation,
    )
    action = _resolve_journey_action(context, kind)
    if action is JourneyAction.OPEN:
        response = _seed_profile_facts_for_open_journey(context, response)
    accepted_components = list(response.proof.get("accepted_components") or [])
    rejected_components = list(response.proof.get("rejected_components") or [])
    if action is JourneyAction.NONE:
        decision, response, rejected = _without_journey_mutation(
            context, decision, response, kind,
        )
        rejected_components.extend(rejected)
        accepted_components.append({"component": "reply", "policy": "no_journey"})
    interaction_observation = {
        "kind": kind.value,
        "evidence_span": evidence_span,
        "confidence": confidence,
        "authority": "model_observation_backend_reconciled",
    }
    proof = {
        **response.proof,
        "journey_action": action.value,
        "interaction_observation": interaction_observation,
        "accepted_components": accepted_components,
        "rejected_components": rejected_components,
        "agent_slug": context.agent_slug,
        "agent_role": response.role.value,
        "policy_version": CONTRACT_VERSION,
    }
    return decision, response.model_copy(update={"proof": proof})


def _seed_profile_facts_for_open_journey(
    context: ConversationContext, response: AgentResponse,
) -> AgentResponse:
    accepted = list(response.proof.get("accepted_facts") or [])
    identities = {
        (str(fact.get("field_key") or ""), str(fact.get("owner_node_id") or ""))
        for fact in accepted
    }
    source_message_id = _source_message_id(context.messages)
    for fact in context.shared_memory.profile_facts:
        identity = (fact.key, fact.owner_node_id)
        if identity in identities:
            continue
        accepted.append({
            "field_key": fact.key, "owner_node_id": fact.owner_node_id,
            "status": fact.status.value, "value": fact.value,
            "source_message_id": fact.source_message_id or source_message_id,
            "evidence_span": "", "confidence": fact.confidence,
            "metadata": {
                **fact.metadata, "origin_journey_id": fact.journey_id,
                "reuse_policy": "carry_over",
                "policy_version": context.shared_memory.policy_version,
            },
        })
        identities.add(identity)
    return response.model_copy(update={
        "proof": {**response.proof, "accepted_facts": accepted},
    })


def decide(
    context: ConversationContext, *, model_observation: dict[str, Any]
) -> tuple[ConversationDecision, AgentResponse]:
    if not isinstance(model_observation, dict):
        raise ValueError("model_observation is required for graph_agent_runtime_v3")
    decision, response = _decide(
        context, model_observation=model_observation,
    )
    token_usage = (model_observation or {}).get("token_usage")
    if token_usage:
        response = response.model_copy(update={"token_usage": token_usage})
    # A carried-over fact (_seed_carried_facts) only ever lived in
    # context.cart["facts"] for this one turn's in-memory processing -- it
    # was never folded into accepted_facts, the only thing commit_graph_-
    # turn_v3 persists. So it survived exactly one journey-close-then-
    # reopen hop "for free" and then vanished the moment a SECOND journey
    # closed before the customer independently restated it (confirmed
    # live 2026-08-18: nome_cliente asked again on the third journey).
    # context.journey_id is None precisely on the turn build_context
    # creates the new journey's in-memory placeholder (before the DB
    # trigger assigns a real id) -- write the carried facts into this
    # turn's accepted_facts exactly then, so they land durably in the new
    # journey's own ledger in the same commit transaction that creates it.
    if context.journey_id is None:
        already_accepted = {
            str(fact.get("field_key") or "")
            for fact in response.proof.get("accepted_facts") or []
        }
        carried = [
            {
                "field_key": key,
                "owner_node_id": fact.get("owner_node_id"),
                "status": fact.get("status"),
                "value": fact.get("value"),
                "source_message_id": fact.get("source_message_id"),
                "evidence_span": fact.get("evidence_span"),
                "confidence": fact.get("confidence"),
                "metadata": fact.get("metadata"),
            }
            for key, fact in (context.cart.get("facts") or {}).items()
            if fact.get("carried_from_journey") and key not in already_accepted
        ]
        if carried:
            response = response.model_copy(update={
                "proof": {
                    **response.proof,
                    "accepted_facts": [
                        *(response.proof.get("accepted_facts") or []), *carried,
                    ],
                },
            })
    audited = _with_structural_proof_audit(context, decision, response)
    if (
        response.reply_text is None
        or response.proof.get("delivery_authorized") is False
        or response.proof.get("repair_required") is True
    ):
        return decision, audited.model_copy(update={
            "reply_text": None,
            "proof": {
                **audited.proof,
                "model_reply_preserved": True,
            },
        })
    final_decision, final_response = _apply_journey_policy(
        context, decision, audited, model_observation=model_observation,
    )
    # Journey policy may adjust routing/state, but it does not own public
    # language in agentic mode. Safety failures already return reply_text=None
    # before this point; every non-empty grounded model reply stays byte exact.
    if response.reply_text is not None:
        final_response = final_response.model_copy(update={
            "reply_text": response.reply_text,
            "proof": {
                **final_response.proof,
                "model_reply_preserved": True,
            },
        })
    return final_decision, final_response


def _sanitize_untrusted_service_operations(raw: Any) -> Any:
    """Discard model-only service operations that have no literal evidence.

    Service state is resolved deterministically from the inbound before the
    model is called and replaces this untrusted list after parsing.  Some
    models still emit ``keep`` with an empty span on ordinary field answers;
    letting that fail Pydantic would suppress a valid answer before the
    authoritative resolver can apply its empty operation set.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("service_operations"), list):
        return raw
    operations = [
        operation
        for operation in raw["service_operations"]
        if not isinstance(operation, dict)
        or str(operation.get("evidence_span") or "").strip()
    ]
    return {**raw, "service_operations": operations}


def _discard_invalid_structured_components(
    raw: Any,
) -> tuple[Any, list[str]]:
    """Drop malformed ancillary components without touching ``reply``.

    A malformed fact/claim/service observation is not permission to replace a
    valid public answer. Each component is independently parsed; proof later
    decides which surviving commercial claims are safe to publish.
    """
    if not isinstance(raw, dict):
        return raw, []
    result = dict(raw)
    discarded: list[str] = []
    component_models = {
        "service_observations": ServiceObservation,
        "service_operations": ServiceOperation,
        "extracted_facts": ExtractedFact,
        "claims": CommercialClaim,
    }
    for key, model in component_models.items():
        value = result.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            discarded.append(f"discarded_invalid_component:{key}")
            result[key] = []
            continue
        accepted = []
        for index, item in enumerate(value):
            try:
                accepted.append(model.model_validate(item).model_dump(mode="json"))
            except ValidationError:
                discarded.append(f"discarded_invalid_component:{key}:{index}")
        result[key] = accepted
    return result, discarded


def _folded_with_origin(text: Any) -> tuple[str, list[int]]:
    """Case/accent-folded text plus the raw offset each folded char came from."""
    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(str(text or "")):
        for part in unicodedata.normalize("NFKD", char.casefold()):
            if unicodedata.combining(part):
                continue
            folded.append(part)
            origin.append(index)
    return "".join(folded), origin


def _fact_span_interval(message: str, span: Any) -> tuple[int, int] | None:
    """Locate the evidence inside the message, ignoring case and accents.

    A model routinely echoes a span in its own capitalization ("Allan
    Rodrigues" for a message that reads "allan rodrigues"). A case-sensitive
    `find` reported that evidence as absent, so a perfectly grounded fact
    lost its only proof of literalness. Folding both sides keeps the
    comparison literal in the sense that matters -- same characters, same
    order, same position -- without pretending the customer types like a
    form.
    """
    folded_span, _ = _folded_with_origin(span)
    if not folded_span:
        return None
    folded_message, origin = _folded_with_origin(message)
    start = folded_message.find(folded_span)
    if start < 0:
        return None
    return origin[start], origin[start + len(folded_span) - 1] + 1


def _overlaps_any(
    interval: tuple[int, int] | None, spans: list[dict[str, Any]],
) -> bool:
    return bool(interval and any(
        interval[0] < int(span.get("end") or 0)
        and int(span.get("start") or 0) < interval[1]
        for span in spans
    ))


def _model_confidence_floor(validation: Any) -> float:
    """Confidence the graph demands before a model reading stands on its own."""
    published = validation if isinstance(validation, dict) else {}
    try:
        floor = float(published.get("model_confidence_min"))
    except (TypeError, ValueError):
        return MODEL_FACT_CONFIDENCE_MIN
    return floor if 0.0 <= floor <= 1.0 else MODEL_FACT_CONFIDENCE_MIN


def _reconcile_human_full_name_facts(
    proposal: ConversationProposal,
    *,
    context: ConversationContext,
    contract: dict[str, Any],
) -> tuple[ConversationProposal, list[dict[str, Any]]]:
    """Trust the model's reading of a name; make the backend prove it.

    Until 2026-08-19 a name only became `known` when the raw message was
    byte-identical to the extracted value. A customer typing "allan
    rodrigues" against a model answering "Allan Rodrigues" failed that
    equality, so a correct, high-confidence extraction was demoted to
    `needs_confirmation` -- and that confirmation could only be resolved by
    one of a handful of literal confirmation phrases, which is how the live
    conversation deadlocked repeating the same template.

    The division of labour is now the one the contract states: the model
    owns the semantics (what the customer meant, with a calibrated
    confidence), the backend owns the proof (the span is literally in the
    message, the shape is a name, and it does not steal a span already
    consumed as a service). Confirmation is the last resort, not the
    default.
    """
    message = _latest_user_message(context)
    asked = context.cart.get("asked_question_node_ids") or []
    resolution = context.retrieval_trace.get("service_resolution") or {}
    service_spans = list(resolution.get("consumed_spans") or [])
    residual = _normalized_phrase(
        _message_without_consumed_services(message, resolution)
    )
    kept: list[ExtractedFact] = []
    validation: list[dict[str, Any]] = []
    fields = {str(field.get("key") or ""): field for field in contract.get("fields") or []}
    for fact in proposal.extracted_facts:
        field = fields.get(fact.field_key) or {}
        rules = field.get("validation") or {}
        if str(rules.get("semantic_type") or "") != "human_full_name":
            kept.append(fact)
            continue
        candidate = str(fact.value or "").strip()
        minimum, maximum = graph_proof_checker_v3.name_token_bounds(rules)
        if not graph_proof_checker_v3.is_human_full_name(
            candidate, min_tokens=minimum, max_tokens=maximum,
        ):
            validation.append({
                "field_key": fact.field_key,
                "owner_node_id": fact.owner_node_id,
                "valid": False,
                "errors": ["human_full_name_invalid"],
            })
            continue
        evidence = str(fact.evidence_span or "").strip() or candidate
        interval = _fact_span_interval(message, evidence)
        if _overlaps_any(interval, service_spans):
            validation.append({
                "field_key": fact.field_key,
                "owner_node_id": fact.owner_node_id,
                "valid": False,
                "errors": ["human_full_name_overlaps_service_evidence"],
                "evidence_span": evidence,
            })
            continue
        # The persisted evidence is the customer own slice of text, never the
        # model re-cased echo -- that is what a later audit has to be able to
        # find again in the original message.
        literal_evidence = message[interval[0]:interval[1]] if interval else ""
        confident = float(fact.confidence or 0) >= _model_confidence_floor(rules)
        # Low-confidence fallback, with no language-specific phrasing:
        # everything the customer wrote (minus spans already consumed as a
        # service) is the name, and the published name question was the last
        # thing asked.
        direct_answer = bool(
            asked
            and field.get("question_node_id")
            and str(asked[-1]) == str(field["question_node_id"])
            and residual == _normalized_phrase(candidate)
        )
        if literal_evidence and (confident or direct_answer):
            kept.append(fact.model_copy(update={
                "status": ConversationFactStatus.KNOWN,
                "value": candidate,
                "evidence_span": literal_evidence,
                "metadata": {
                    **fact.metadata,
                    "validation_method": (
                        "model_confidence" if confident
                        else "direct_published_name_answer"
                    ),
                },
            }))
            continue
        kept.append(fact.model_copy(update={
            "status": ConversationFactStatus.NEEDS_CONFIRMATION,
            "value": None,
            "evidence_span": literal_evidence or evidence,
            "metadata": {
                **fact.metadata,
                "confirmation": {
                    "kind": "name",
                    "capability": "common_fact",
                    "template_key": "name",
                    "candidate": candidate,
                    "field_key": fact.field_key,
                    "owner_node_id": fact.owner_node_id,
                    "evidence_span": literal_evidence or evidence,
                    "method": (
                        "unproven_evidence" if not literal_evidence
                        else "low_model_confidence"
                    ),
                },
            },
        }))
    return proposal.model_copy(update={"extracted_facts": kept}), validation


def _semantic_service_candidate(
    context: ConversationContext,
    proposal: ConversationProposal,
) -> tuple[dict[str, Any] | None, str | None]:
    resolution = context.retrieval_trace.get("service_resolution") or {}
    if resolution.get("candidate"):
        candidate = dict(resolution["candidate"])
        message = _latest_user_message(context)
        interval = _fact_span_interval(message, candidate.get("evidence_span"))
        reserved = [
            other
            for fact in proposal.extracted_facts
            if fact.field_key != "servico"
            if (other := _fact_span_interval(message, fact.evidence_span)) is not None
        ]
        if interval is None or any(
            interval[0] < other[1] and other[0] < interval[1] for other in reserved
        ):
            return None, "service_evidence_reserved_or_non_literal"
        return candidate, None
    ranking = resolution.get("semantic_ranking") or []
    if not ranking:
        return None, "no_service_candidate"
    top = ranking[0]
    top_score = float(top.get("score") or 0)
    second_score = float(ranking[1].get("score") or 0) if len(ranking) > 1 else 0.0
    margin = top_score - second_score
    if top_score < SERVICE_SEMANTIC_MIN_SCORE:
        return None, "semantic_score_below_threshold"
    if margin < SERVICE_SEMANTIC_MIN_MARGIN:
        return None, "semantic_margin_ambiguous"
    matching = [
        observation for observation in proposal.service_observations
        if observation.branch_anchor_node_id == top.get("branch_anchor_node_id")
    ]
    if len(matching) != 1:
        return None, "model_backend_service_mismatch"
    observation = matching[0]
    message = _latest_user_message(context)
    interval = _fact_span_interval(message, observation.evidence_span)
    reserved = [
        candidate
        for fact in proposal.extracted_facts
        if fact.field_key != "servico"
        if (candidate := _fact_span_interval(message, fact.evidence_span)) is not None
    ]
    if interval is None or any(
        interval[0] < other[1] and other[0] < interval[1] for other in reserved
    ):
        return None, "service_evidence_reserved_or_non_literal"
    active = set(context.active_branch_node_ids)
    if context.active_branch_node_id:
        active.add(context.active_branch_node_id)
    intent = observation.observed_intent
    action = (
        "drop" if intent == "remove"
        else "switch" if (
            intent == "switch" and context.active_branch_node_id
            and observation.branch_anchor_node_id != context.active_branch_node_id
        )
        else "keep" if observation.branch_anchor_node_id in active
        else "add"
    )
    return {
        "branch_anchor_node_id": observation.branch_anchor_node_id,
        "branch_path_checksum": "",
        "evidence_span": observation.evidence_span,
        "start": interval[0],
        "end": interval[1],
        "action": action,
        "replace_branch_node_id": (
            context.active_branch_node_id if action == "switch" else None
        ),
        "resolution_method": "semantic_anchor_ranking",
        "semantic_score": round(top_score, 6),
        "semantic_margin": round(margin, 6),
        "model_confidence": observation.confidence,
    }, None






def _decide(
    context: ConversationContext, *, model_observation: dict[str, Any]
) -> tuple[ConversationDecision, AgentResponse]:
    observation = model_observation
    if observation.get("contract_probe") is True:
        return (
            ConversationDecision(classifier="graph_contract_probe_v3", intent="await_model_proposal",
                                 route=ConversationRoute.SDR, confidence=1, lead_stage=str(context.cart.get("_lead_stage") or "novo")),
            AgentResponse(reply_text=None, role=ConversationRoute.SDR, cart_state=context.cart,
                          proof={"valid": True, "mode": "contract_probe", "runtime_version": RUNTIME_VERSION}),
        )
    raw = observation.get("proposal") if isinstance(observation.get("proposal"), dict) else observation
    raw = _sanitize_untrusted_service_operations(raw)
    raw, discarded_components = _discard_invalid_structured_components(raw)
    parse_errors = [str(value) for value in observation.get("proposal_parse_errors") or []]
    try:
        proposal = ConversationProposal.model_validate(raw)
    except ValidationError as exc:
        return _invalid_proposal_fallback(
            context,
            raw,
            [*parse_errors, f"proposal_schema_invalid:{exc.errors(include_url=False)}"],
            repair_attempt=int(observation.get("repair_attempt") or 0),
        )
    if parse_errors:
        return _invalid_proposal_fallback(
            context,
            raw,
            parse_errors,
            repair_attempt=int(observation.get("repair_attempt") or 0),
        )
    publication = _turn_publication(context)
    if str(publication.get("id")) != str(context.publication_id) or publication.get("checksum") != context.graph_checksum:
        raise RuntimeError("GraphRAG publication changed during turn")
    document = publication.get("document_json") or {}
    model_proposed_service_operations = [
        item.model_dump(mode="json") for item in proposal.service_operations
    ]
    model_service_observations = [
        item.model_dump(mode="json") for item in proposal.service_observations
    ]
    service_candidate, service_candidate_rejection = _semantic_service_candidate(
        context, proposal,
    )
    if service_candidate:
        anchor = str(service_candidate.get("branch_anchor_node_id") or "")
        node = (document.get("node_by_id") or {}).get(anchor) or {}
        coordinate = ((document.get("coordinates") or {}).get(anchor) or {})
        service_candidate = {
            **service_candidate,
            "branch_path_checksum": str(coordinate.get("path_checksum") or ""),
            "title": str(node.get("title") or anchor),
            "slug": str(node.get("slug") or anchor),
        }
    observed_contract_anchor = (
        proposal.branch_anchor_node_id
        if proposal.branch_anchor_node_id in set(document.get("branch_anchors") or [])
        else None
    )
    proposal = _apply_authoritative_branch_resolution(proposal, context, document)
    proposal = _normalize_initial_service_keep(proposal, context=context)
    contract_anchor = (
        proposal.branch_anchor_node_id
        or context.retrieval_trace.get("retrieval_branch_node_id")
        or observed_contract_anchor
    )
    contract = (document.get("branch_contracts") or {}).get(contract_anchor) or {}
    if not context.active_branch_node_id and not (
        (context.retrieval_trace.get("service_resolution") or {}).get("operations")
    ):
        contract = _preselection_contract(document, contract_anchor)
    grouped_facts = context.cart.get("facts_by_key") or {}
    contract_facts = (
        _facts_for_contract(contract, grouped_facts)
        if grouped_facts else context.cart.get("facts") or {}
    )
    asked_field_key = str(
        ((observation.get("interpretation") or {}).get("asked_field_key") or "")
        if isinstance(observation.get("interpretation"), dict)
        else ""
    )
    if asked_field_key and not proposal.next_question_node_id:
        authored_field = next(
            (
                field for field in contract.get("fields") or []
                if str(field.get("key") or "") == asked_field_key
            ),
            None,
        )
        if authored_field and authored_field.get("question_node_id"):
            proposal = proposal.model_copy(update={
                "next_question_node_id": authored_field["question_node_id"],
            })
    proposal = _normalize_referential_service_fact(proposal, context, document)
    proposal = _normalize_servico_owner(proposal, contract)
    proposal = _normalize_fact_source_message_ids(proposal, context)
    proposal, name_field_validation = _reconcile_human_full_name_facts(
        proposal, context=context, contract=contract,
    )
    proposal, consumed_field_validation = _remove_consumed_service_facts(
        proposal, context=context, document=document,
    )
    proposal, invalid_field_validation = _remove_invalid_declared_facts(
        proposal, contract,
    )
    rejected_field_validation = [
        *name_field_validation,
        *consumed_field_validation,
        *invalid_field_validation,
    ]
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
    # The persona root is unconditionally in every branch's closure/path (it
    # owns identity-level facts like nome_cliente) -- always in scope by
    # construction, not by retrieval. It typically has no indexed prose
    # chunk of its own, so it never earns a context card and, without this,
    # never lands in package_node_ids on ANY turn. The model naturally cites
    # it while restating already-known facts on the turn qualification
    # completes -- that legitimate citation was rejected as
    # cited_node_outside_package, forcing an unnecessary (and, live, stuck)
    # repair round-trip that left the customer without a reply.
    persona_root_id = str((_persona_node(document) or {}).get("id") or "") or None
    persona_root_ids = {persona_root_id} if persona_root_id else set()
    active_ids_for_fields = context.active_branch_node_ids or (
        [context.active_branch_node_id] if context.active_branch_node_id else []
    )
    # Union of every currently active branch's own fields, not just the
    # turn's focused contract -- a customer naming two services in the same
    # message otherwise has the second one's extracted_facts rejected as
    # undeclared/owner-mismatched purely because this turn's contract is
    # scoped to whichever branch the model focused on. _active_contract_fields
    # already does the (key, owner_node_id)-deduped union this needs; claims
    # authorization deliberately stays read only from `contract` (unchanged
    # below) -- that's a different, intentional pre-selection/hallucination
    # gate, not a scoping bug.
    additional_fields = _active_contract_fields(document, active_ids_for_fields, contract)
    proof = graph_proof_checker_v3.check(
        publication=publication, contract=contract, ledger=ledger,
        proposal=proposal.model_dump(mode="json"), message=next(
            (str(row.get("content") or row.get("texto") or row.get("message") or "") for row in reversed(context.messages)
             if str(row.get("role") or "") == "user" or str(row.get("sender_type") or "") == "lead"), ""
        ), source_message_id=_source_message_id(context.messages),
        package_node_ids={card.id for card in context.context_cards} | {
            str(value) for value in observation.get("repair_context_node_ids") or [] if value
        } | persona_root_ids,
        package_chunk_ids={str(row.get("chunk_id") or row.get("id")) for row in context.rag_chunks} | {
            str(value) for value in observation.get("repair_context_chunk_ids") or [] if value
        },
        active_branch_node_id=context.active_branch_node_id,
        branch_selection_allowed=context.active_branch_node_id is None and proposal.branch_anchor_node_id in {
            item.get("branch_anchor_node_id") for item in context.retrieval_trace.get("branch_candidates") or []
        },
        branch_switch_allowed=proposal.branch_anchor_node_id in set(context.retrieval_trace.get("possible_switches") or []),
        package_chunk_sources=chunk_sources,
        active_branch_node_ids=active_ids_for_fields,
        additional_fields=additional_fields,
    )
    service_operations = [
        item.model_dump(mode="json")
        for item in proposal.service_operations
    ]
    before_services = list(dict.fromkeys([
        *([context.active_branch_node_id] if context.active_branch_node_id else []),
        *context.active_branch_node_ids,
    ]))
    service_proof = graph_proof_checker_v3.check_service_operations(
        document=document,
        message=_latest_user_message(context),
        operations=service_operations,
        active_branch_node_ids=before_services,
        consumed_service_spans=(
            (context.retrieval_trace.get("service_resolution") or {})
            .get("consumed_spans") or []
        ),
    )
    if service_operations and not service_proof["valid"]:
        proof["errors"] = [*proof.get("errors", []), *service_proof["errors"]]
        proof["valid"] = False
        proof["repair_required"] = False
    proof.update({
        "service_resolution": context.retrieval_trace.get("service_resolution") or {},
        "service_operations": service_operations,
        "model_proposed_service_operations": model_proposed_service_operations,
        "model_service_observations": model_service_observations,
        "applied_service_operations": service_operations,
        "service_operation_rejection_reason": (
            "model_operations_replaced_by_backend_resolver"
            if model_proposed_service_operations != service_operations else None
        ),
        "service_candidate": service_candidate,
        "service_candidate_rejection_reason": service_candidate_rejection,
        "service_operation_proof": service_proof,
        "consumed_service_spans": (
            (context.retrieval_trace.get("service_resolution") or {})
            .get("consumed_spans") or []
        ),
        "field_validation": [
            *(proof.get("field_validation") or []),
            *rejected_field_validation,
        ],
        "discarded_structured_components": discarded_components,
        "quality_warnings": list(dict.fromkeys([
            *(proof.get("quality_warnings") or []),
            *discarded_components,
        ])),
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
        requirements = proof["repair_requirements"]
        if requirements:
            rows = supabase_client.get_graph_rag_repair_chunks(
                publication_id=publication["id"], branch_node_id=proposal.branch_anchor_node_id,
                requirements=requirements,
            )
            repair_chunks = _repair_chunks(rows, requirements)
            if len(repair_chunks) > RAG_CHUNK_LIMIT:
                raise RuntimeError(
                    "required graph repair package exceeds the 12-chunk prompt limit"
                )
            sources: dict[str, list[dict[str, Any]]] = {}
            for row in repair_chunks:
                sources.setdefault(str(row.get("source_graph_node_id") or ""), []).append(row)
            repair_cards = [
                _card(publication, document["node_by_id"][node_id], chunks, index).model_dump(mode="json")
                for index, (node_id, chunks) in enumerate(sources.items()) if node_id in document.get("node_by_id", {})
            ]
        response = AgentResponse(reply_text=None, role=ConversationRoute.SDR, cart_state=context.cart,
                                 proposal=proposal, proof=proof, repair_context_cards=repair_cards)
        return ConversationDecision(classifier="graph_proof_checker_v3", intent="repair_retrieval",
                                    route=ConversationRoute.SDR, confidence=0, lead_stage=str(context.cart.get("_lead_stage") or "novo")), response
    # Nao existe verbo para "estou so conversando sobre isto". Sem galho ativo e
    # sem nenhuma operacao para aplicar, `keep` e a escolha honesta do modelo, e
    # nao um defeito -- entao ele nao pode, sozinho, custar o turno. Comparar a
    # lista inteira por igualdade tornava a recuperacao refem da ordem e de
    # duplicatas; o que importa e nao sobrar nenhum outro erro.
    discovery_only = (
        context.active_branch_node_id is None
        and proposal.branch_action.value == "none"
        and not service_operations
        and not proof.get("errors")
    )
    # A fact error belonging to a currently active branch OTHER than the one
    # the model focused on this turn must not, by itself, discard the whole
    # turn's natural/accepted-proposal path -- only the focused branch's own
    # errors (and any non-fact error: branch-action authorization, citation,
    # claims) still gate it exactly as before. proof["valid"]/proof["errors"]
    # stay the true, complete validation result for anyone else consuming
    # them (logging, audits); this is a local view used only for this one
    # routing decision. field_validation already carries each fact's
    # owner_node_id, so this reuses data check() already computed.
    focused_anchor = str(proposal.branch_anchor_node_id or "")
    non_focused_active = set(active_ids_for_fields) - {focused_anchor}
    deferrable_errors = {
        error
        for entry in proof.get("field_validation") or []
        if not entry.get("valid")
        and str(entry.get("owner_node_id") or "") in non_focused_active
        for error in entry.get("errors") or []
    }
    gating_errors = [
        error for error in proof.get("gating_errors") or []
        if error not in deferrable_errors
    ]
    metadata_errors = list(proof.get("metadata_errors") or [])
    repairable_errors = list(dict.fromkeys([*gating_errors, *metadata_errors]))
    if repairable_errors:
        repair_attempt = int(observation.get("repair_attempt") or 0)
        if repair_attempt < 1:
            return (
                ConversationDecision(
                    classifier="graph_proof_checker_v3",
                    intent="repair_retrieval",
                    route=ConversationRoute.SDR,
                    confidence=0,
                    lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                ),
                AgentResponse(
                    reply_text=None,
                    role=ConversationRoute.SDR,
                    cart_state=context.cart,
                    handoff_required=False,
                    proposal=proposal,
                    proof={
                        **proof,
                        "valid": False,
                        "delivery_authorized": False,
                        "repair_required": True,
                        "repair_requirements": [{
                            "kind": "model_metadata",
                            "issue": error,
                        } for error in repairable_errors],
                        "fallback_used": False,
                        "model_reply_preserved": True,
                    },
                ),
            )
        return (
            ConversationDecision(
                classifier="graph_proof_checker_v3",
                intent="safety_handoff",
                route=ConversationRoute.HUMAN,
                confidence=0,
                lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                handoff_reason="agentic_proof_failed_after_repair",
            ),
            AgentResponse(
                reply_text=None,
                role=ConversationRoute.HUMAN,
                cart_state=context.cart,
                handoff_required=True,
                proposal=proposal,
                proof={
                    **proof,
                    "valid": False,
                    "delivery_authorized": False,
                    "repair_required": False,
                    "fallback_used": False,
                    "model_reply_preserved": True,
                    "handoff_observable": True,
                },
            ),
        )
    proof_gates_turn = False
    if not proof_gates_turn or discovery_only:
        if discovery_only:
            proof = {
                **proof,
                "valid": True,
                "errors": [],
                "mode": "discovery",
                "branch_committed": False,
            }
        accepted_facts = list(proof.get("accepted_facts") or [])
        accepted_facts.extend(_service_facts_for_operations(
            operations=service_operations,
            document=document,
            grouped_facts=grouped_facts,
            source_message_id=_source_message_id(context.messages),
        ))
        if service_candidate and not service_operations:
            previous_service_fact = next(
                (
                    fact for fact in grouped_facts.get("servico", [])
                    if str(fact.get("owner_node_id") or "")
                    == str(service_candidate["branch_anchor_node_id"])
                    and fact.get("status") == "known"
                ),
                None,
            )
            accepted_facts.append({
                "field_key": "servico",
                "owner_node_id": service_candidate["branch_anchor_node_id"],
                "status": "needs_confirmation",
                "value": None,
                "source_message_id": _source_message_id(context.messages),
                "evidence_span": service_candidate["evidence_span"],
                "confidence": float(
                    service_candidate.get("semantic_score")
                    or service_candidate.get("text_similarity") or 1
                ),
                "metadata": {
                    "confirmation": {
                        "kind": "service",
                        "capability": "branch_selector",
                        "candidate": service_candidate.get("slug"),
                        "candidate_title": service_candidate.get("title"),
                        "branch_anchor_node_id": service_candidate["branch_anchor_node_id"],
                        "branch_path_checksum": service_candidate["branch_path_checksum"],
                        "action": service_candidate.get("action") or "add",
                        "operation": service_candidate.get("action") or "add",
                        "operation_ambiguous": bool(
                            service_candidate.get("operation_ambiguous")
                        ),
                        "attempts": 1,
                        "replace_branch_node_id": service_candidate.get("replace_branch_node_id"),
                        "previous_active_branch_node_id": context.active_branch_node_id,
                        "previous_active_branch_node_ids": before_services,
                        "previous_fact": (
                            {
                                "field_key": previous_service_fact.get("field_key"),
                                "owner_node_id": previous_service_fact.get("owner_node_id"),
                                "status": previous_service_fact.get("status"),
                                "value": previous_service_fact.get("value"),
                                "metadata": previous_service_fact.get("metadata") or {},
                            }
                            if previous_service_fact else None
                        ),
                        "evidence_span": service_candidate["evidence_span"],
                        "method": service_candidate.get("resolution_method"),
                        "score": service_candidate.get("semantic_score")
                        or service_candidate.get("text_similarity"),
                        "margin": service_candidate.get("semantic_margin"),
                    },
                },
            })
            # A different candidate starts a fresh clarification ladder. Mark
            # older pending service candidates non-current in the same commit
            # so a later "sim" can never confirm the stale one.
            for stale in grouped_facts.get("servico", []):
                stale_confirmation = (
                    (stale.get("metadata") or {}).get("confirmation") or {}
                )
                if (
                    stale.get("status") == "needs_confirmation"
                    and _confirmation_capability(stale_confirmation)
                    in {"service", "branch_selector"}
                    and str(stale.get("owner_node_id") or "")
                    != str(service_candidate["branch_anchor_node_id"])
                ):
                    accepted_facts.append({
                        **stale,
                        "status": "invalid", "value": None,
                        "source_message_id": _source_message_id(context.messages),
                        "metadata": {
                            **dict(stale.get("metadata") or {}),
                            "confirmation": {
                                **stale_confirmation,
                                "transition": "superseded_by_new_candidate",
                            },
                        },
                    })
        accepted_facts = list({
            (str(fact.get("field_key") or ""), str(fact.get("owner_node_id") or "")): fact
            for fact in accepted_facts
        }.values())
        next_grouped = {
            str(key): list(values) for key, values in grouped_facts.items()
        }
        if not next_grouped:
            for field in contract.get("fields") or []:
                key = str(field.get("key") or "")
                fact = contract_facts.get(key)
                if key and fact:
                    next_grouped.setdefault(key, []).append(fact)
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
        if service_operations:
            active_branch_ids = list(service_proof["next_active_branch_node_ids"])
        committed_branch = (
            (context.retrieval_trace.get("service_resolution") or {}).get("focused_branch_node_id")
            if service_operations
            else context.active_branch_node_id
        )
        if active_branch_ids and committed_branch not in set(active_branch_ids):
            committed_branch = active_branch_ids[-1]
        if not active_branch_ids:
            committed_branch = None

        if active_branch_ids:
            aggregate_missing = graph_proof_checker_v3.aggregate_missing_fields(
                document.get("branch_contracts") or {}, active_branch_ids, next_grouped,
            )
            aggregate_askable = graph_proof_checker_v3.aggregate_askable_fields(
                document.get("branch_contracts") or {}, active_branch_ids, next_grouped,
            )
            aggregate_required_count = graph_proof_checker_v3.aggregate_required_field_count(
                document.get("branch_contracts") or {}, active_branch_ids, next_grouped,
            )
        else:
            preselection_contract = document.get("common_contract") or contract
            preselection_facts = _facts_for_contract(preselection_contract, next_grouped)
            aggregate_missing = graph_proof_checker_v3.pending_fields(
                preselection_contract, preselection_facts,
            )
            aggregate_askable = graph_proof_checker_v3.askable_pending_fields(
                preselection_contract, preselection_facts,
            )
            aggregate_required_count = graph_proof_checker_v3.required_field_count(
                preselection_contract, preselection_facts,
            )
        active_fields = _active_contract_fields(document, active_branch_ids, contract)
        terminal_unconfirmed = _dedupe_fields([
            *aggregate_missing,
            *_unknown_fields(active_fields, next_grouped),
        ])
        askable_question_ids = {
            str(field.get("question_node_id") or "")
            for field in aggregate_askable
            if field.get("question_node_id")
        }
        next_question_id = (
            proposal.next_question_node_id
            if str(proposal.next_question_node_id or "") in askable_question_ids
            else None
        )
        question_contract = next(
            (
                candidate for candidate in (document.get("branch_contracts") or {}).values()
                if next_question_id in (candidate.get("questions") or {})
            ),
            contract,
        )
        qualification_complete = not terminal_unconfirmed and not discovery_only
        qualification_incomplete = bool(
            terminal_unconfirmed and not aggregate_askable and not discovery_only
        )
        collection_complete = not aggregate_askable and not discovery_only
        # An active branch (offering -- service or product, no distinction
        # here) this ledger has never marked 'completed' still needs its own
        # confirmation cycle, even while the journey overall is already
        # post_qualification_support for whatever was confirmed first. This
        # is what lets a customer name and confirm a second/third offering in
        # the same still-open conversation instead of it being silently
        # absorbed as generic support chat (see graph_agent_runtime_v3.py's
        # plan doc / commit message for the incident this fixes).
        pending_branch_confirmation = bool(
            set(active_branch_ids) - set(context.completed_branch_node_ids)
        )
        post_support = bool(
            str(context.operational_mode) == "post_qualification_support"
            and not _explicit_change_requested(_latest_user_message(context))
            and not pending_branch_confirmation
        )
        confirmation_pending = bool(qualification_complete and not post_support)
        terminal_intent = "qualification_incomplete" if qualification_incomplete else None
        # Public language is model-owned in n8n_agents mode. Structured state
        # may be accepted, discarded or repaired independently, but a valid
        # grounded reply is never appended, summarized, normalized or swapped
        # for graph-authored copy.
        reply = proposal.reply
        pending_confirmation_fact = next(
            (
                fact for fact in accepted_facts
                if str(fact.get("status") or "") == "needs_confirmation"
                and isinstance((fact.get("metadata") or {}).get("confirmation"), dict)
            ),
            None,
        )
        field_confirmation = (
            ((pending_confirmation_fact or {}).get("metadata") or {}).get("confirmation")
            or {}
        )
        recent_replies = _assistant_replies(context.messages)
        question_text = str(
            ((question_contract.get("questions") or {}).get(next_question_id or "") or {}).get("text")
            or ""
        )
        repetition = conversation_repetition.assess_repetition(
            current_reply=reply,
            recent_replies=recent_replies,
            question_node_id=next_question_id,
            question_text=question_text,
            asked_question_node_ids=context.cart.get("asked_question_node_ids") or [],
            max_attempts=_question_repetition_max_attempts(question_contract),
            field_pending=any(
                field.get("question_node_id") == next_question_id
                for field in aggregate_askable
            ),
            terminal_intent=terminal_intent,
            previous_terminal_intent=str(
                ((context.cart.get("terminal_handoff") or {}).get("intent") or "")
            ) or None,
        )
        if not repetition["passed"]:
            repair_attempt = int(observation.get("repair_attempt") or 0)
            if repair_attempt < 1:
                return (
                    ConversationDecision(
                        classifier="graph_proof_checker_v3",
                        intent="repair_retrieval",
                        route=ConversationRoute.SDR,
                        confidence=0,
                        lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                    ),
                    AgentResponse(
                        reply_text=None,
                        role=ConversationRoute.SDR,
                        cart_state=context.cart,
                        handoff_required=False,
                        proposal=proposal,
                        proof={
                            **proof,
                            "valid": False,
                            "delivery_authorized": False,
                            "repair_required": True,
                            "repair_requirements": [{
                                "kind": "model_reply",
                                "issue": "semantic_repetition",
                                "instruction": (
                                    "Rewrite once without repeating a recent reply; "
                                    "preserve every grounded fact."
                                ),
                            }],
                            "repetition_audit": repetition,
                            "fallback_used": False,
                            "model_reply_preserved": True,
                        },
                    ),
                )
            return (
                ConversationDecision(
                    classifier="graph_proof_checker_v3",
                    intent="repetition_handoff",
                    route=ConversationRoute.HUMAN,
                    confidence=0,
                    lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                    handoff_reason="model_repetition_after_repair",
                ),
                AgentResponse(
                    reply_text=None,
                    role=ConversationRoute.HUMAN,
                    cart_state=context.cart,
                    handoff_required=True,
                    proposal=proposal,
                    proof={
                        **proof,
                        "valid": False,
                        "delivery_authorized": False,
                        "repair_required": False,
                        "repetition_audit": repetition,
                        "fallback_used": False,
                        "model_reply_preserved": True,
                        "handoff_observable": True,
                    },
                ),
            )
        projection_contract = (
            (document.get("branch_contracts") or {}).get(committed_branch)
            or document.get("common_contract")
            or contract
        )
        facts = _facts_for_contract(projection_contract, next_grouped)
        state = {
            **context.cart,
            "facts": facts,
            "facts_by_key": next_grouped,
            "active_branch_node_id": committed_branch,
            "active_branch_node_ids": active_branch_ids,
            "commercial_note_projection": _commercial_note_projection(
                document=document,
                active_branch_ids=active_branch_ids,
                focused_branch_id=committed_branch,
                facts_by_key=next_grouped,
            ),
            "asked_question_node_ids": [
                *(context.cart.get("asked_question_node_ids") or []),
                # Only a question the customer actually received counts against
                # the repetition budget. Recording a suppressed ask spends an
                # emission on an outbound that was never sent.
                *(
                    [next_question_id]
                    if next_question_id and repetition_action in {
                        "allowed", "repaired_never_acknowledge_only",
                    }
                    else []
                ),
            ],
            "sdr_state": (
                "handed_off" if terminal_intent
                else "awaiting_confirmation" if confirmation_pending
                else "handed_off" if post_support
                else "collecting"
            ),
            **({
                "terminal_handoff": {
                    "intent": terminal_intent,
                    "emitted": True,
                }
            } if terminal_intent else {}),
        }
        route = ConversationRoute.HUMAN if terminal_intent else ConversationRoute.SDR
        resolved_intent = (
            terminal_intent
            or ("awaiting_confirmation" if confirmation_pending else None)
            or ("post_qualification_support" if post_support else None)
            or "collect_graph_fields"
        )
        proof = {
            **proof,
            "missing_fields": [field.get("key") for field in terminal_unconfirmed],
            "required_field_count": aggregate_required_count,
            "aggregate_missing_fields": terminal_unconfirmed,
            "next_question_node_id": next_question_id,
            "asked_field_key": next(
                (field.get("key") for field in terminal_unconfirmed
                 if field.get("question_node_id") == next_question_id),
                None,
            ),
            "qualification_complete": qualification_complete,
            "qualification_incomplete": qualification_incomplete,
            "collection_complete": collection_complete,
            "explicit_confirmation": False,
            "confirmation_state": (
                "field_confirmation" if pending_confirmation_fact
                else "awaiting_confirmation" if confirmation_pending
                else "handed_off" if terminal_intent
                else "post_qualification_support" if post_support
                else "collecting"
            ),
            "accepted_facts": accepted_facts,
            "pending_confirmation": field_confirmation or None,
            "field_validation": proof.get("field_validation") or [],
            "previous_active_branch_node_ids": before_services,
            "next_active_branch_node_ids": active_branch_ids,
            "previous_active_branch_node_id": context.active_branch_node_id,
            "next_active_branch_node_id": committed_branch,
            "branch_focus_invariant": (
                (not active_branch_ids and committed_branch is None)
                or committed_branch in set(active_branch_ids)
            ),
            "repetition_audit": repetition,
            "repetition_action": repetition_action,
            "fallback_used": False,
            "delivery_authorized": True,
            "model_reply_preserved": reply == proposal.reply,
            "technical_pass": True,
            "quality_pass": repetition["passed"],
        }
        evidence_node_ids = list(dict.fromkeys([
            *proposal.cited_node_ids,
        ]))
        return (
            ConversationDecision(classifier="graph_proof_checker_v3",
                                 intent=resolved_intent,
                                 route=route, confidence=1, lead_stage="qualificado" if qualification_complete else "engajado",
                                 handoff_reason="graph_terminal_qualification" if terminal_intent else None,
                                 evidence_node_ids=evidence_node_ids),
            AgentResponse(reply_text=reply or None, role=route, evidence_node_ids=evidence_node_ids,
                          cart_state=state,
                          handoff_required=bool(terminal_intent),
                          proposal=proposal, proof=proof),
        )
    # A rejected proposal never crosses into graph-authored public copy.
    # One model repair is allowed; a second inconsistency becomes an
    # observable handoff with no outbound text.
    return _invalid_proposal_fallback(
        context,
        raw,
        [str(error) for error in proof.get("errors") or []],
        repair_attempt=int(observation.get("repair_attempt") or 0),
    )

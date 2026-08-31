"""Two-phase, branch-scoped GraphRAG context and proposal reconciliation."""
from __future__ import annotations

import json
import logging
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
    ContextCard,
    ConversationContext,
    ConversationDecision,
    ConversationFactStatus,
    ConversationProposal,
    ConversationRoute,
    ExtractedFact,
    InteractionKind,
    JourneyAction,
    SemanticInterpretation,
    ServiceOperation,
    ServiceOperationAction,
)
from services import (
    conversation_repetition,
    graph_compiler_v3,
    graph_proof_checker_v3,
    semantic_conversation_policy,
    semantic_interpretation_validator,
    shared_lead_memory,
    supabase_client,
)


logger = logging.getLogger("graph_agent_runtime_v3")

RUNTIME_VERSION = "graph_agent_runtime_v3"
CONTRACT_VERSION = "graph_agent_contract_v4"
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
# Last-resort operational copy. It contains no commercial fact and exists only
# so a globally untrusted proposal becomes an observable human handoff instead
# of a committed silent turn. Persona-specific wording should be published in
# conversation_policy.context_failure_handoff_reply.
CONTEXT_FAILURE_HANDOFF_REPLY = (
    "Não consegui confirmar o contexto com segurança. "
    "Vou encaminhar para o atendimento humano."
)


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
    """Repoint a mismatched branch-selector fact to the selected branch.

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
    selection_field = _service_selection_field(contract)
    selection_key = str((selection_field or {}).get("key") or "")
    if not selection_key:
        return proposal
    normalized_facts = [
        fact.model_copy(update={"owner_node_id": proposal.branch_anchor_node_id})
        if fact.field_key == selection_key and fact.owner_node_id != proposal.branch_anchor_node_id
        else fact
        for fact in proposal.extracted_facts
    ]
    if normalized_facts == proposal.extracted_facts:
        return proposal
    return proposal.model_copy(update={"extracted_facts": normalized_facts})


def _normalize_unique_published_field_owners(
    proposal: ConversationProposal, contract: dict[str, Any]
) -> ConversationProposal:
    """Treat a model-provided fact owner as a hint, never as authority.

    A field key that has exactly one owner in the materialized contract is
    unambiguous.  Repoint that fact to the graph-owned identity before proof
    validation; literal evidence, status and value validation still run
    unchanged.  Keys published for multiple owners remain fail-closed because
    choosing between branches would require inventing scope.
    """
    owners_by_key: dict[str, set[str]] = {}
    for field in contract.get("fields") or []:
        key = str(field.get("key") or "").strip()
        owner = str(field.get("owner_node_id") or "").strip()
        if key and owner:
            owners_by_key.setdefault(key, set()).add(owner)
    authoritative = {
        key: next(iter(owners))
        for key, owners in owners_by_key.items()
        if len(owners) == 1
    }
    normalized_facts = [
        fact.model_copy(update={"owner_node_id": authoritative[fact.field_key]})
        if fact.field_key in authoritative
        and fact.owner_node_id != authoritative[fact.field_key]
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
    context: ConversationContext, raw: Any, errors: list[str], *, repair_attempt: int = 0,
) -> tuple[ConversationDecision, AgentResponse]:
    model_errors = list(dict.fromkeys(errors))
    if repair_attempt < 1:
        # A malformed first response is a model-contract failure, not a
        # commercial handoff. Keep the already committed conversation state
        # untouched and let the single model-owned repair boundary regenerate
        # a complete semantic interpretation. No backend-authored question or
        # unproved fact is published while that repair is pending.
        proof = {
            "valid": False,
            "errors": model_errors,
            "gating_errors": [],
            "repair_required": True,
            "repair_requirements": [{
                "kind": "schema",
                "issue": "model_output_invalid",
                "instruction": (
                    "Return one complete semantic interpretation matching the "
                    "requested JSON contract. Preserve grounded meaning from "
                    "the customer message and do not repeat a prior question."
                ),
            }],
            "fallback_used": False,
            "mode": "model_output_repair",
            "model_proposal_errors": model_errors,
            "model_proposal": (
                raw if isinstance(raw, dict) else {"raw_type": type(raw).__name__}
            ),
            "accepted_facts": [],
            "question_component_invalid": False,
        }
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
                proof=proof,
            ),
        )

    # A second malformed response is a recoverable provider/model failure.
    # Never manufacture graph copy, handoff text or a deterministic question;
    # the same canonical inbound is returned to durable retry with no outbound.
    return (
        ConversationDecision(
            classifier="graph_proof_checker_v3",
            intent="model_format_retry_exhausted",
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
                "gating_errors": ["model_output_invalid_after_retry"],
                "repair_required": False,
                "durable_retry_required": True,
                "provider_failure_class": "invalid_json",
                "fallback_used": False,
                "model_reply_preserved": True,
                "evidence_status": "unknown",
                "quality_warnings": model_errors,
                "technical_pass": False,
                "quality_pass": False,
                "accepted_facts": [],
                "asked_field_keys": [],
                "asked_question_node_ids": [],
            },
        ),
    )

    contract = context.graph_contract or {}
    facts = context.cart.get("facts") or {}
    missing = graph_proof_checker_v3.pending_fields(contract, facts)
    pending = graph_proof_checker_v3.askable_pending_fields(contract, facts)
    question_id = next(
        (field.get("question_node_id") for field in pending if field.get("question_node_id")),
        None,
    )
    facts_by_key = context.cart.get("facts_by_key") or {
        key: [value] for key, value in facts.items()
    }
    unconfirmed = _dedupe_fields([
        *missing,
        *_unknown_fields(contract.get("fields") or [], facts_by_key),
    ])
    terminal_intent = None
    confirmation_pending = False
    if context.active_branch_node_id and contract.get("fields") and not pending:
        confirmation_pending = not unconfirmed
        terminal_intent = "qualification_incomplete" if unconfirmed else None
    if terminal_intent or confirmation_pending:
        # A malformed/unparseable model proposal must not collapse a
        # multi-service pedido back down to whichever single branch
        # happens to be focused this turn -- every other active branch's
        # already-confirmed facts would silently drop out of the summary.
        # Same active-branch union every other _terminal_reply call site
        # in this module already uses (e.g. the check_proposal-rejection
        # fallback below).
        active_branch_ids = list(dict.fromkeys([
            *([context.active_branch_node_id] if context.active_branch_node_id else []),
            *context.active_branch_node_ids,
        ]))
        if len(active_branch_ids) > 1:
            persona = supabase_client.get_persona(context.persona_slug) or {}
            publication = supabase_client.get_active_graph_publication(
                str(persona.get("id") or "")
            ) or {}
            document = publication.get("document_json") or {}
            document = {
                **document,
                "branch_contracts": {
                    **(document.get("branch_contracts") or {}),
                    context.active_branch_node_id: contract,
                },
            }
        else:
            document = {
                "branch_contracts": {context.active_branch_node_id: contract},
                "node_by_id": {},
            }
        reply = _terminal_reply(
            document=document,
            contract=contract,
            active_branch_ids=active_branch_ids or [context.active_branch_node_id],
            facts_by_key=facts_by_key,
            missing_fields=unconfirmed,
            qualification_complete=not unconfirmed,
        )
    else:
        # Invalid model output cannot authorize the backend to choose or append
        # a qualification question. End observably and leave every graph field
        # to a subsequent model-owned turn or human continuation.
        question_id = None
        reply = str(
            context.retrieval_trace.get("no_journey_fallback_reply") or ""
        ).strip() or CONTEXT_FAILURE_HANDOFF_REPLY
        terminal_intent = "invalid_model_output"
    recent_replies = _assistant_replies(context.messages)
    repetition = conversation_repetition.assess_repetition(
        current_reply=reply,
        recent_replies=recent_replies,
        question_node_id=question_id,
        question_text=str(
            ((contract.get("questions") or {}).get(question_id or "") or {}).get("text") or ""
        ),
        asked_question_node_ids=context.cart.get("asked_question_node_ids") or [],
        max_attempts=_question_repetition_max_attempts(contract),
        field_pending=bool(question_id),
        terminal_intent=terminal_intent,
        previous_terminal_intent=str(
            ((context.cart.get("terminal_handoff") or {}).get("intent") or "")
        ) or None,
    )
    repetition_action = "allowed"
    if not repetition["passed"]:
        reply = CONTEXT_FAILURE_HANDOFF_REPLY
        question_id = None
        terminal_intent = "invalid_model_output_repetition"
        repetition_action = "repetition_handoff"
    fallback_valid = bool(str(reply or "").strip())
    proof = {
        "valid": fallback_valid,
        "errors": [] if fallback_valid else model_errors,
        "repair_required": False,
        "fallback_used": True,
        "fallback_applied": (
            "published_invalid_proposal" if fallback_valid else None
        ),
        "mode": "model_output_handoff",
        "model_proposal_errors": model_errors,
        "model_proposal": raw if isinstance(raw, dict) else {"raw_type": type(raw).__name__},
        "missing_fields": [field["key"] for field in unconfirmed],
        "qualification_complete": not unconfirmed,
        "qualification_incomplete": bool(unconfirmed and not pending),
        "repetition_audit": repetition,
        "repetition_action": repetition_action,
        "explicit_confirmation": False,
        "confirmation_state": (
            "awaiting_confirmation" if confirmation_pending
            else "handed_off" if terminal_intent else "collecting"
        ),
    }
    route = ConversationRoute.HUMAN if terminal_intent else ConversationRoute.SDR
    state = {
        **context.cart,
        "sdr_state": (
            "awaiting_confirmation" if confirmation_pending
            else "handed_off" if terminal_intent else "collecting"
        ),
        "asked_question_node_ids": [
            *(context.cart.get("asked_question_node_ids") or []),
            *([question_id] if question_id else []),
        ],
        **({
            "terminal_handoff": {"intent": terminal_intent, "emitted": True}
        } if terminal_intent else {}),
    }
    return (
        ConversationDecision(
            classifier="graph_proof_checker_v3",
            intent=terminal_intent or (
                "awaiting_confirmation" if confirmation_pending else "model_output_handoff"
            ),
            route=route, confidence=0,
            lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            handoff_reason="graph_terminal_qualification" if terminal_intent else None,
            evidence_node_ids=[question_id] if question_id else [],
        ),
        AgentResponse(
            reply_text=reply or None, role=route,
            evidence_node_ids=[question_id] if question_id else [],
            cart_state=state, handoff_required=bool(terminal_intent), proof=proof,
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


# RAG keeps a relevance/cardinality bound for retrieval quality, but there is
# no runtime token ceiling. The provider owns its context and completion
# limits; the runtime records estimates only as telemetry.
RAG_CHUNK_TOKEN_BUDGET: int | None = None
RAG_CHUNK_LIMIT = 10
RAG_FAQ_CHUNK_RESERVE = 1


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


def _required_structural_chunks(
    rows: list[dict[str, Any]],
    required_node_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Keep one executable non-question chunk per required path node.

    ``get_graph_branch_package_v3`` returns both explicitly requested path
    nodes and vector-selected FAQ chunks.  Treating every returned source as
    structural made the whole FAQ candidate set mandatory and could reject a
    turn before the model ran.  Question wording is already represented by
    the published contract for audit; it is deliberately excluded from RAG so
    the model owns the natural phrasing instead of copying graph-authored copy.
    """
    kind_priority = {
        "claims": 5, "rule": 5, "rules": 5,
        "validators": 4, "structured_facts": 3, "content": 2,
    }
    required_scope = {
        str(node_id) for node_id in (required_node_ids or []) if node_id
    }
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("source_node_id") or row.get("source_graph_node_id") or "")
        chunk_kind = str(row.get("chunk_kind") or "")
        if (
            not source
            or (required_scope and source not in required_scope)
            or chunk_kind == "question"
        ):
            continue
        current = selected.get(source)
        score = kind_priority.get(chunk_kind, 1)
        current_score = kind_priority.get(str((current or {}).get("chunk_kind") or ""), 1)
        if current is None or score > current_score:
            selected[source] = row
    return list(selected.values())


def _optional_retrieval_chunk_slots(
    required_structural: list[dict[str, Any]],
    reserved_faq: list[dict[str, Any]],
) -> int:
    """Return optional MMR capacity without charging FAQ against structure.

    The branch contract can legitimately require all available structural
    slots. A current-turn FAQ is separately selected, graph-authorized
    evidence and therefore gets one explicit reserve.
    """
    if len(required_structural) > RAG_CHUNK_LIMIT:
        raise RuntimeError(
            f"required structural chunks exceed the {RAG_CHUNK_LIMIT}-chunk prompt limit"
        )
    if len(reserved_faq) > RAG_FAQ_CHUNK_RESERVE:
        raise RuntimeError("selected FAQ evidence exceeds its reserved chunk limit")
    return RAG_CHUNK_LIMIT - len(required_structural)


def _required_retrieval_node_ids(
    document: dict[str, Any],
    branch_node_id: str,
    contract: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    """Return the executable structural package for one turn.

    The published branch contract already carries pending question identity
    and handoff rules. Retrieval therefore reserves structural context for the
    active path and handoff only; relevant conversational knowledge comes from
    vector-selected FAQ chunks, never a forced first-pending question chunk.
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
        and str(row.get("chunk_kind") or "") != "question"
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
            "title": node.get("title"), "node_type": node.get("node_type"),
            "aliases": (node.get("data") or {}).get("aliases") or [],
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
    # The branch selector is never a "non-service field": answering it IS the
    # service selection. Resolve the field from the question actually asked,
    # not from list position; the model may choose any askable pending field.
    selection_field = _service_selection_field(contract) or {}
    selector_key = str(selection_field.get("key") or "servico")
    field = next(
        (
            row for row in contract.get("fields") or []
            if str(row.get("key") or "") in set(missing_fields)
            and str(row.get("question_node_id") or "")
            == str(asked_question_node_ids[-1] or "")
        ),
        None,
    )
    if not field:
        return False
    if str(field.get("key") or "") == selector_key:
        return False
    expected_question = str(field.get("question_node_id") or "")
    return bool(
        expected_question
        and str(asked_question_node_ids[-1] or "") == expected_question
    )


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
        "node_type": str(
            ((document.get("node_by_id") or {}).get(item["branch_anchor_node_id"]) or {})
            .get("node_type") or ""
        ),
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
                    "node_type": str(node.get("node_type") or ""),
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
        # A remaining active branch after a drop-only operation is state, not
        # fresh customer evidence. Only synthesize selection evidence when the
        # resolver actually selected the focus in this inbound.
        resolved_focus_this_turn = bool(focused_operation) or (
            str(service_resolution.get("status") or "") == "resolved"
            and not operations
        )
        evidence_span = str(
            focused_operation.get("evidence_span")
            or service_resolution.get("evidence_span")
            or next(
                (
                    item.get("span") or item.get("evidence_span")
                    for item in reversed(service_resolution.get("matches") or [])
                    if item.get("branch_anchor_node_id") == anchor
                ),
                "",
            )
            or (_latest_user_message(context) if resolved_focus_this_turn else "")
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
    """Bind the graph-declared branch selector to one published branch."""
    selection_key = branch_selection_field_key(document)
    service_facts = [
        fact for fact in proposal.extracted_facts
        if fact.field_key == selection_key
    ]
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
    kept = [
        fact for fact in proposal.extracted_facts
        if fact.field_key != selection_key
    ]
    if valid:
        kept.append(ExtractedFact(
            field_key=selection_key,
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
    if fact.field_key == branch_selection_field_key(document):
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


def _service_disambiguation_response(
    context: ConversationContext,
) -> tuple[ConversationDecision, AgentResponse]:
    contract = (
        context.retrieval_trace.get("common_contract")
        or context.graph_contract or {}
    )
    service_field = _service_selection_field(contract)
    question_id = str((service_field or {}).get("question_node_id") or "") or None
    resolution = context.retrieval_trace.get("service_resolution") or {}
    candidate_options = (
        (resolution.get("confirmation") or {}).get("options") or []
    )
    option_ids = list(dict.fromkeys(
        str(anchor)
        for ambiguity in [*(resolution.get("ambiguities") or []), *candidate_options]
        for anchor in (
            ambiguity.get("candidate_branch_node_ids")
            or [ambiguity.get("branch_anchor_node_id")]
        )
        if anchor
    ))
    labels = {
        str(item.get("branch_anchor_node_id") or item.get("slug") or ""):
        str(item.get("label") or "")
        for item in context.available_services
    }
    options = ", ".join(labels.get(anchor, anchor) for anchor in option_ids)
    disambiguation_template = str(
        (context.retrieval_trace.get("confirmation_templates") or {})
        .get("service_disambiguation") or ""
    ).strip()
    if not disambiguation_template:
        raise RuntimeError("published graph missing service_disambiguation template")
    validation = (service_field or {}).get("validation") or {}
    invalid_text = str(
        validation.get("invalid_response")
        or "Não consegui identificar exatamente qual serviço você quis dizer."
    ).strip()
    reply = disambiguation_template.replace("{options}", options)
    asked = list(context.cart.get("asked_question_node_ids") or [])
    if question_id:
        asked.append(question_id)
    proof = {
        "valid": True,
        "errors": [],
        "mode": "service_disambiguation",
        "service_resolution": resolution,
        "service_operations": [],
        "consumed_service_spans": resolution.get("consumed_spans") or [],
        "collection_complete": False,
        "qualification_complete": False,
        "accepted_facts": [],
        "field_validation": [],
        "next_question_node_id": question_id,
    }
    state = {
        **context.cart,
        "active_branch_node_id": context.active_branch_node_id,
        "active_branch_node_ids": list(context.active_branch_node_ids),
        "asked_question_node_ids": asked,
    }
    return (
        ConversationDecision(
            classifier="graph_service_resolver_v3",
            intent="service_disambiguation",
            route=ConversationRoute.SDR,
            confidence=1,
            lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            evidence_node_ids=[question_id] if question_id else [],
        ),
        AgentResponse(
            reply_text=reply or None,
            role=ConversationRoute.SDR,
            evidence_node_ids=[question_id] if question_id else [],
            cart_state=state,
            handoff_required=False,
            proof=proof,
        ),
    )


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


def _explicitly_defers_pending_field(message: str) -> bool:
    """Recognize a deictic request to continue without the pending answer.

    This is deliberately field- and persona-neutral.  A phrase such as
    ``podemos seguir sem essa informação?`` refers to the question the
    runtime just published; it is not an informational FAQ merely because it
    ends in a question mark.
    """
    normalized = _normalized_phrase(message)
    return bool(re.fullmatch(
        r"(?:podemos|pode|posso|vamos|quero|prefiro)\s+"
        r"(?:seguir|continuar|prosseguir)\s+sem\s+"
        r"(?:essa|esta|a)\s+(?:informacao|resposta|dado)(?:\s+agora)?",
        normalized,
    )) or bool(re.fullmatch(
        r"(?:can\s+we|could\s+we|may\s+we|i(?:d|\s+would)\s+prefer\s+to)\s+"
        r"(?:move\s+on|continue|proceed)\s+without\s+"
        r"(?:that|this|the\s+(?:information|answer|detail))",
        normalized,
    ))


def _coerce_direct_field_value(message: str, field: dict[str, Any]) -> Any:
    """Conservatively coerce a literal reply for one graph-declared field."""
    literal = str(message or "").strip()
    if not literal:
        return None
    validation = field.get("validation") or {}
    if str(validation.get("mode") or "") == "enum":
        folded_literal = f" {_normalized_phrase(literal)} "
        matches: list[tuple[int, Any]] = []
        for item in validation.get("values") or []:
            if not isinstance(item, dict):
                continue
            canonical = item.get("value")
            for published in [canonical, *(item.get("aliases") or [])]:
                folded = _normalized_phrase(str(published or ""))
                if folded and f" {folded} " in folded_literal:
                    matches.append((len(folded), canonical))
        if matches:
            longest = max(length for length, _value in matches)
            winners = {
                json.dumps(value, ensure_ascii=False, sort_keys=True): value
                for length, value in matches if length == longest
            }
            if len(winners) == 1:
                return next(iter(winners.values()))
    schema = field.get("value_schema") or {}
    candidates = schema.get("anyOf") or [schema]
    for candidate in candidates:
        raw_expected = candidate.get("type")
        if isinstance(raw_expected, str):
            expected_types = {raw_expected}
        elif isinstance(raw_expected, (list, tuple, set)):
            expected_types = {
                item for item in raw_expected if isinstance(item, str)
            }
        else:
            expected_types = set()
        value: Any = None
        if "string" in expected_types or not expected_types:
            value = literal
            enum = candidate.get("enum") or []
            if enum:
                folded = _normalized_phrase(literal)
                value = next(
                    (item for item in enum if _normalized_phrase(item) == folded),
                    None,
                )
        elif expected_types.intersection({"integer", "number"}) and re.fullmatch(
            r"[-+]?\d+(?:[.,]\d+)?", literal,
        ):
            expected = "integer" if "integer" in expected_types else "number"
            parsed = float(literal.replace(",", "."))
            value = int(parsed) if expected == "integer" and parsed.is_integer() else parsed
        elif "boolean" in expected_types:
            folded = _normalized_phrase(literal)
            if folded in {"sim", "yes", "verdadeiro"}:
                value = True
            elif folded in {"nao", "no", "falso"}:
                value = False
        if value is not None and graph_proof_checker_v3._schema_error(candidate, value) is None:
            canonical, error = graph_proof_checker_v3._canonical_field_value(
                field, value, literal,
            )
            if error is None:
                return canonical
    return None


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
    message = _message_without_consumed_services(
        _latest_user_message(context),
        context.retrieval_trace.get("service_resolution") or {},
    ).strip()
    if not message or _looks_like_customer_question(message):
        return proposal
    pending = graph_proof_checker_v3.askable_pending_fields(contract, ledger_facts)
    if not pending:
        return proposal
    asked = [str(value) for value in context.cart.get("asked_question_node_ids") or []]
    if not asked:
        return proposal
    field = next(
        (
            item for item in pending
            if str(item.get("question_node_id") or "") == asked[-1]
        ),
        None,
    )
    if field is None:
        return proposal
    key = str(field.get("key") or "")
    if not key or any(fact.field_key == key for fact in proposal.extracted_facts):
        return proposal
    value = _coerce_direct_field_value(message, field)
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
    max_attempts: int = 1,
    doubt_answered: bool = False,
) -> dict[str, Any] | None:
    """Mark an unanswered field unknown after initial ask plus allowed retries."""
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
    proposed = next(
        (
            fact
            for fact in proposal.extracted_facts
            if fact.field_key == key and fact.owner_node_id == owner
        ),
        None,
    )
    proposed_status = str(
        proposed.status.value if proposed and hasattr(proposed.status, "value")
        else proposed.status if proposed else ""
    )
    if proposed and proposed_status in accepted_statuses and proposed_status != "unknown":
        return None
    message = _message_without_consumed_services(
        _latest_user_message(context),
        context.retrieval_trace.get("service_resolution") or {},
    ).strip()
    explicit_unknown = bool(
        _EXPLICIT_UNKNOWN.fullmatch(message)
        or _explicitly_defers_pending_field(message)
    )
    if not explicit_unknown:
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
    allowed_emissions = 1 + max(0, min(int(max_attempts), 1))
    # The budget counts question emissions, not customer stonewalling, and the
    # contract asks the agent to answer a doubt *and* resume the question. So a
    # customer who asks two legitimate questions about the catalog exhausts the
    # budget without ever having refused to answer, and the field is given up
    # on. A turn that carried an answered doubt is not a non-answer.
    del asked, observed_attempts, allowed_emissions, doubt_answered
    return {
        "field_key": key,
        "owner_node_id": owner,
        "status": "unknown",
        "value": None,
        "source_message_id": _source_message_id(context.messages),
        "evidence_span": message,
        "confidence": 1.0,
        "reason": "explicit_unknown",
        "metadata": {"reason": "explicit_unknown"},
    }


def _drop_premature_unknown_for_pending_question(
    proposal: ConversationProposal,
    context: ConversationContext,
    contract: dict[str, Any],
    ledger_facts: dict[str, Any],
    *,
    max_attempts: int,
) -> ConversationProposal:
    """Do not let a model turn the first ignored answer into a terminal fact."""
    pending = graph_proof_checker_v3.askable_pending_fields(contract, ledger_facts)
    if not pending:
        return proposal
    field = pending[0]
    key = str(field.get("key") or "")
    owner = str(field.get("owner_node_id") or "")
    question_id = str(field.get("question_node_id") or "")
    question_text = str(
        ((contract.get("questions") or {}).get(question_id) or {}).get("text") or ""
    ).strip()
    asked = [str(value) for value in context.cart.get("asked_question_node_ids") or []]
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
    del asked, observed_attempts, max_attempts
    message = _message_without_consumed_services(
        _latest_user_message(context),
        context.retrieval_trace.get("service_resolution") or {},
    ).strip()
    explicit_unknown = bool(
        _EXPLICIT_UNKNOWN.fullmatch(message)
        or _explicitly_defers_pending_field(message)
    )
    if explicit_unknown:
        return proposal
    filtered = [
        fact
        for fact in proposal.extracted_facts
        if not (
            fact.field_key == key
            and fact.owner_node_id == owner
            and str(fact.status.value if hasattr(fact.status, "value") else fact.status)
            == "unknown"
        )
    ]
    if len(filtered) == len(proposal.extracted_facts):
        return proposal
    return proposal.model_copy(update={"extracted_facts": filtered})


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
    recent = [
        str(row.get("content") or row.get("texto") or "")
        for row in messages
        if str(row.get("role") or "") == "assistant"
        or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
    ][-3:]
    return any(conversation_repetition.is_semantic_repetition(previous, reply) for previous in recent)


def _question_repetition_max_attempts(contract: dict[str, Any]) -> int:
    """Compatibility reader for a retired publication knob.

    A field question is now single-emission. Older graphs may still carry
    ``question_repetition.max_attempts``; accepting the document must never
    turn that legacy value into permission to ask the same field again.
    """
    del contract
    return 0


def _assistant_replies(messages: Sequence[dict[str, Any]], limit: int = 4) -> list[str]:
    """The agent's own recent turns, the only baseline repetition compares to."""
    return [
        text
        for row in messages
        if str(row.get("role") or "") == "assistant"
        or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
        if (text := str(row.get("content") or row.get("texto") or "").strip())
    ][-limit:]


def _unrepeated_variant(
    variants: Sequence[str], recent_replies: Sequence[str] = ()
) -> str:
    """First published phrasing this conversation has not already heard.

    Step one of the repetition ladder. The graph is the sole author of every
    candidate, so adapting never invents copy -- it only declines to reuse a
    phrasing the customer just read. Rotating by lead_ref (the previous
    behaviour) kept a lead on one stable phrase forever, which is precisely
    what repeats inside a single conversation. Returns "" when every variant
    was already used, handing the turn to the next step of the ladder.
    """
    approved = [text for value in variants if (text := str(value or "").strip())]
    for candidate in approved:
        if not any(
            conversation_repetition.is_semantic_repetition(previous, candidate)
            for previous in recent_replies
        ):
            return candidate
    return ""


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


def _published_conversation_policies(
    document: dict[str, Any], contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    conversation_policy = contract.get("conversation_policy") or {}
    field_labels = contract.get("field_labels") or {}
    if conversation_policy and field_labels:
        return conversation_policy, field_labels
    persona = next(
        (
            node for node in (document.get("node_by_id") or {}).values()
            if str(node.get("node_type") or "") == "persona"
        ),
        {},
    )
    data = persona.get("data") or {}
    appointment_policy = data.get("appointment_policy") or {}
    return (
        conversation_policy or data.get("conversation_policy") or {},
        field_labels or appointment_policy.get("field_labels") or {},
    )


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
    (graph_proof_checker_v3.validate_natural_summary) would otherwise force
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


def _collected_field_facts(
    document: dict[str, Any],
    active_branch_ids: list[str],
    contract: dict[str, Any],
    facts_by_key: dict[str, list[dict[str, Any]]],
    *,
    merge_selector: bool = False,
) -> list[tuple[str, str]]:
    """(label, rendered value) for every required field already known.

    Shared by the deterministic terminal summary and the natural-summary
    grounding guard so both agree on exactly what counts as "collected".

    ``merge_selector`` is opt-in and only used by the deterministic terminal
    summary. The branch-selection field (e.g. "servico") is declared once per
    active branch by construction -- with 2+ active branches this loop would
    otherwise emit one ("Serviço", value) tuple per branch, which is what
    produced two disjoint "serviço:" clauses in the same confirmation
    sentence instead of one that treats every active offering as equally
    fundamental. The natural-summary grounding guard (validate_natural_summary)
    must keep seeing each title as its own independent substring, so it calls
    this with the default False.
    """
    _, labels = _published_conversation_policies(document, contract)
    fields = _active_contract_fields(document, active_branch_ids, contract)
    selection_key = branch_selection_field_key(document) if merge_selector else ""
    collected: list[tuple[str, str]] = []
    selector_emitted = False
    for field in fields:
        key = str(field.get("key") or "")
        owner = str(field.get("owner_node_id") or "")
        if merge_selector and key == selection_key and owner in active_branch_ids:
            if selector_emitted:
                continue
            titles = active_offering_titles(document, active_branch_ids, facts_by_key)
            if len(titles) >= 2:
                selector_emitted = True
                label = str(labels.get(key) or "") or _humanize_field_key(key)
                collected.append((label, ", ".join(titles)))
                continue
        # Match the same "already answered" bar _unanswered_fact_after_-
        # question_limit uses (accepted_statuses, not a hardcoded "known")
        # so a field the contract explicitly lets settle at
        # "needs_confirmation" (the branch selector) still surfaces in the
        # summary instead of vanishing from it while qualification is
        # already considered complete.
        accepted_statuses = set(field.get("accepted_statuses") or ["known"])
        fact = next(
            (
                row for row in facts_by_key.get(key) or []
                if str(row.get("owner_node_id") or "") == owner
                and row.get("status") in accepted_statuses
                and row.get("status") != "unknown"
                and row.get("value") not in (None, "")
            ),
            None,
        )
        if fact:
            label = str(labels.get(key) or "") or _humanize_field_key(key)
            collected.append((label, _render_field_value(field, fact.get("value"))))
    return collected


def _terminal_reply(
    *,
    document: dict[str, Any],
    contract: dict[str, Any],
    active_branch_ids: list[str],
    facts_by_key: dict[str, list[dict[str, Any]]],
    missing_fields: list[dict[str, Any]],
    qualification_complete: bool,
) -> str:
    """Render terminal copy exclusively from the published graph contract."""
    conversation_policy, labels = _published_conversation_policies(document, contract)
    qualification = conversation_policy.get("qualification") or {}
    collected = _collected_field_facts(
        document, active_branch_ids, contract, facts_by_key, merge_selector=True,
    )
    informed = [f"{label}: {value}" for label, value in collected]
    missing_labels = list(dict.fromkeys(
        str(labels.get(str(field.get("key") or "")) or "")
        or _humanize_field_key(str(field.get("key") or ""))
        for field in missing_fields
        if str(field.get("key") or "")
    ))
    replacements = {
        "{informed_fields}": "; ".join(informed),
        "{missing_fields}": ", ".join(missing_labels),
    }

    def render(template: Any) -> str:
        result = str(template or "").strip()
        for marker, value in replacements.items():
            result = result.replace(marker, value)
        return result.strip()

    if qualification_complete:
        parts = [
            render(qualification.get("summary_template")),
            render(qualification.get("confirmation_question")),
        ]
        reply = "\n\n".join(part for part in parts if part)
    else:
        reply = render(qualification.get("incomplete_handoff_template"))
    if reply:
        return reply

    facts = {
        key: rows[-1] for key, rows in facts_by_key.items() if rows
    }
    for branch_id in active_branch_ids:
        candidate = (document.get("branch_contracts") or {}).get(branch_id) or {}
        rule = next(
            (
                row for row in candidate.get("handoff_rules") or []
                if row.get("text") and graph_proof_checker_v3.handoff_rule_matches(
                    row, facts=facts, qualification_complete=qualification_complete,
                )
            ),
            None,
        )
        if rule:
            return str(rule["text"]).strip()
    raise RuntimeError("published graph missing terminal qualification copy")


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
            "node_type": item.get("node_type"),
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


def _greeting_policy(
    document: dict[str, Any], *, contract: dict[str, Any], facts: dict[str, Any],
    lead_ref: int = 0, recent_replies: Sequence[str] = (), message: str = "",
) -> dict[str, Any] | None:
    persona = _persona_node(document)
    persona_data = persona.get("data") or {}
    policy = persona_data.get("conversation_policy") or {}
    greeting = ((policy.get("intents") or {}).get("greeting") or {})
    # A customer the agent already knows must not be introduced from scratch
    # again. The graph publishes the two sets separately; when it only
    # publishes the first-contact set, that one keeps serving both cases.
    returning = bool(facts) and bool(
        greeting.get("response_node_ids_returning")
        or greeting.get("responses_returning")
    )
    node_ids = (
        greeting.get("response_node_ids_returning")
        if returning else greeting.get("response_node_ids")
    ) or []
    node_by_id = document.get("node_by_id") or {
        str(node.get("id") or ""): node for node in document.get("nodes") or []
    }
    node_responses: list[tuple[str, str, list[str]]] = []
    for value in node_ids:
        node_id = str(value or "").strip()
        node = node_by_id.get(node_id) or {}
        node_data = node.get("data") or {}
        role = str(
            node_data.get("role")
            or ((node_data.get("metadata") or {}).get("role") or "")
        )
        answer = str(node_data.get("answer") or "").strip()
        if node.get("node_type") == "faq" and role == "greeting_response" and answer:
            triggers = [
                str(trigger).strip()
                for trigger in node_data.get("triggers") or []
                if str(trigger).strip()
            ]
            node_responses.append((node_id, answer, triggers))
    normalized_message = _normalized_phrase(message)
    matching_node_responses = [
        item for item in node_responses
        if normalized_message and any(
            re.search(
                rf"(?<!\w){re.escape(_normalized_phrase(trigger))}(?!\w)",
                normalized_message,
            )
            for trigger in item[2]
        )
    ]
    selectable_node_responses = matching_node_responses or node_responses
    direct_responses = [
        text
        for value in (
            greeting.get("responses_returning") if returning else greeting.get("responses")
        ) or []
        if isinstance(value, str) and (text := value.strip())
    ]
    response = _unrepeated_variant(
        [text for _node_id, text, _triggers in selectable_node_responses]
        or direct_responses,
        recent_replies,
    ) or str(greeting.get("response") or "").strip()
    response_node_id = next(
        (
            node_id for node_id, text, _triggers in selectable_node_responses
            if text == response
        ),
        None,
    )
    if not response:
        return None
    pending = graph_proof_checker_v3.pending_fields(contract, facts) if contract else []
    return {
        "response": response,
        "response_node_id": response_node_id,
        "question": "",
        "question_node_id": None,
        "asked_field_key": None,
        "missing_fields": [field.get("key") for field in pending]
        if pending else [],
    }


SYSTEM_PROMPT = (
    "Interprete a mensagem inteira e converse como uma pessoa prestativa no WhatsApp. "
    "O modelo decide a linguagem, a resposta e se existe uma proxima pergunta util; "
    "o grafo limita fatos comerciais e o backend apenas prova evidencia, estado e "
    "idempotencia. Responda primeiro toda duvida do cliente e extraia todos os fatos "
    "sustentados por trechos literais, mesmo quando ele responder fora da ordem. "
    "Use somente conhecimento publicado para precos, estoque, prazo, politica e agenda. "
    "Preserve o foco da jornada e a memoria compartilhada; nao reinicie a descoberta, "
    "troque de branch nem aplique uma confirmacao sem evidencia explicita da mensagem "
    "atual e o alvo pendente correspondente. "
    "Nunca pergunte um fato conhecido nem um topico ja perguntado. Campo faltante nao "
    "obriga pergunta: quando nao houver um novo topico util, responda sem pergunta. "
    "Separe resposta e pergunta no contrato estruturado e identifique a pergunta somente "
    "pela chave semantica do campo, nunca por id de node. Nao solicite handoff por falha "
    "de pergunta ou por falta de roteiro; use handoff apenas quando o cliente pedir, a "
    "politica publicada exigir ou a qualificacao estiver realmente concluida. Seja "
    "natural, breve e varie a linguagem sem inventar informacao. Retorne apenas o JSON "
    "do schema fornecido."
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


def _no_journey_fallback_reply(document: dict[str, Any]) -> str:
    persona = _persona_node(document) or {}
    policy = ((persona.get("data") or {}).get("conversation_policy") or {})
    return str(policy.get("no_journey_fallback_reply") or "").strip()


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


def _field_feedback(document: dict[str, Any], key: str) -> str:
    """Published copy for what the agent says when a value does not fit.

    Persona-owned, because it is commercial copy: `AGENTS.md` §26 forbids
    production code from carrying a sentence a customer will read. A persona
    that publishes nothing here says nothing extra -- the runtime never
    invents the wording.
    """
    persona = _persona_node(document) or {}
    policy = ((persona.get("data") or {}).get("conversation_policy") or {})
    feedback = policy.get("field_feedback") or {}
    return str(feedback.get(key) or "").strip()


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


def _pending_confirmation_ref(
    operational_mode: str, ledger: dict[str, Any], journey_id: str | None,
) -> str | None:
    """Stable id for whatever this turn is asking the customer to confirm.

    The model must echo this back in `confirmation.target_ref`, which is what
    binds a yes to a specific question. Derived from state the turn already
    has, so nothing new is persisted, and scoped per journey+revision so a
    stale yes from an older exchange cannot close a newer one.

    A pending fact confirmation (a name, a service candidate) outranks the
    journey-level qualification summary, because that is the narrower thing
    actually on the table.
    """
    for rows in (ledger.get("facts_by_key") or {}).values():
        for fact in rows if isinstance(rows, list) else []:
            if not isinstance(fact, dict) or fact.get("status") != "needs_confirmation":
                continue
            if isinstance((fact.get("metadata") or {}).get("confirmation"), dict):
                return f"fact:{fact.get('field_key')}:{fact.get('owner_node_id')}"
    if operational_mode == "confirmation":
        return f"qualification:{journey_id or 'current'}:{ledger.get('revision') or 0}"
    return None


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
            persona_id=str(persona["id"]), lead_ref=lead_ref, message_limit=6,
        )
    except Exception:
        # Rolling-deploy compatibility while migration 114 is being applied.
        batch = {}
    context_batch_ms = round((time.perf_counter() - context_batch_started) * 1000, 3)
    publication = batch.get("publication") or supabase_client.get_active_graph_publication(str(persona["id"]))
    if not publication:
        raise RuntimeError("active GraphRAG v3 publication not found")
    document = publication.get("document_json") or {}
    messages = batch.get("messages") or supabase_client.get_messages(str(lead_ref), limit=6) or []
    # The buffer can canonically coalesce several physical messages. Use that
    # ordered text for this decision/proof without rewriting persisted history
    # or changing the canonical inbound identity.
    messages = _overlay_canonical_inbound(messages, message, message_id)
    shared_memory = shared_lead_memory.project_shared_lead_memory(
        batch=batch, document=document, messages=messages,
    )
    ledger = batch.get("ledger") or None
    if ledger:
        ledger["facts_by_key"] = _facts_by_key(batch.get("facts") or [])
    ledger = ledger or supabase_client.get_conversation_ledger(str(persona["id"]), lead_ref) or {
        "active_branch_node_id": None, "publication_id": publication["id"],
        "graph_checksum": publication["checksum"], "revision": 0,
        "asked_question_node_ids": [], "facts": {}, "facts_by_key": {},
    }
    journey = batch.get("journey") or supabase_client.get_current_conversation_journey(
        str(persona["id"]), lead_ref,
    ) or {}
    latest_journey: dict[str, Any] = {}
    if not journey:
        latest_journey = supabase_client.get_latest_conversation_journey(
            str(persona["id"]), lead_ref,
        ) or {}
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
    try:
        asked_field_keys = (
            supabase_client.get_conversation_asked_field_keys(
                ledger_id,
                publication_id=str(publication.get("id") or "") or None,
                journey_sequence=int(journey.get("sequence") or 1),
            )
            if ledger_id else []
        )
    except Exception:
        # Rolling compatibility while proof producers still emit only graph
        # question ids. The v3 template consumes this empty semantic list and
        # the legacy id list remains available separately for v2 consumers.
        asked_field_keys = []
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
    last_asked_question_id = str(
        ((ledger.get("asked_question_node_ids") or [""])[-1]) or ""
    )
    pending_field = next(
        (
            field for field in pending_fields
            if str(field.get("question_node_id") or "") == last_asked_question_id
        ),
        {},
    )
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
    deterministic_candidates = _deterministic_branch_candidates(document, message)
    greeting_eligible = _is_greeting(message)
    greeting_prefix = _greeting_policy(
        document, contract=active_contract, facts=ledger.get("facts") or {},
        lead_ref=lead_ref, recent_replies=_assistant_replies(messages), message=message,
    ) if greeting_eligible else None
    if greeting_prefix and operational_mode == "post_qualification_support":
        greeting_prefix = {
            **greeting_prefix,
            "question": "",
            "question_node_id": None,
            "asked_field_key": None,
            "missing_fields": [],
        }
    # Only a greeting that asks nothing and names no service skips the model.
    # Anything else -- a doubt, a service, both -- has to be answered, with
    # the greeting riding along as a prefix instead.
    # Greeting copy may prefix the model context, but never short-circuits the
    # RAG/model/proof path or chooses a qualification question itself.
    greeting = None
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
            "focus_derived_in_memory": focus_derived_in_memory,
            "common_contract": common_contract,
            "pending_field": pending_field or None,
            "confirmation_templates": document.get("confirmation_templates") or {},
            "service_resolution_policy": document.get("service_resolution_policy") or {},
            "no_journey_fallback_reply": _no_journey_fallback_reply(document),
            "post_sale_operation_route": _post_sale_route(document),
            "deterministic_intent": "greeting",
            "deterministic_reply": reply,
            "greeting_response_node_id": greeting.get("response_node_id"),
            "asked_field_key": greeting.get("asked_field_key"),
            "next_question_node_id": greeting.get("question_node_id"),
            "missing_fields": greeting.get("missing_fields") or [],
            "journey_state": journey_state,
            "journey_sequence": int(journey.get("sequence") or 1),
            "operational_mode": operational_mode,
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
                  "asked_field_keys": asked_field_keys,
                  "_ledger_revision": ledger.get("revision") or 0},
            rag_nodes=[persona_node] if persona_node else [], rag_paths=[], rag_chunks=[],
            context_cards=[], system_prompt="", available_services=[{
                "branch_anchor_node_id": anchor,
                "slug": document["node_by_id"][anchor]["slug"],
                "label": document["node_by_id"][anchor]["title"],
            } for anchor in document.get("branch_anchors") or []],
            active_branch_node_id=active_branch, active_branch_node_ids=active_branches,
            completed_branch_node_ids=completed_branch_node_ids, ledger_id=ledger_id or None,
            active_path_checksum=((document.get("coordinates") or {}).get(active_branch) or {}).get("path_checksum"),
            branch_node_ids=active_contract.get("closure_node_ids") or [],
            graph_contract=active_contract, publication_id=publication["id"],
            runtime_version=RUNTIME_VERSION, retrieval_trace=trace,
            known_facts=_known_facts_payload(
                ledger.get("facts_by_key") or ledger.get("facts") or {}, message_id,
            ),
            time_since_last_client_message=_time_since_last_client_message(messages, message_id),
            pending_reconfirmation=bool((lead.get("metadata") or {}).get("pending_reconfirmation")),
            journey_id=str(journey.get("id") or "") or None,
            journey_sequence=int(journey.get("sequence") or 1),
            journey_state=journey_state,
            pending_field_key=str(pending_field.get("key") or "") or None,
            pending_question_node_id=str(pending_field.get("question_node_id") or "") or None,
            pending_confirmation_ref=_pending_confirmation_ref(
                operational_mode, ledger, str(journey.get("id") or "") or None,
            ),
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
    embedding_started = time.perf_counter()
    # Deterministic branch resolution only decides which published branch is
    # in scope.  It must not disable semantic knowledge retrieval: compound
    # messages frequently select an audience/product and ask a catalog
    # question in the same turn (for example, "uso próprio; quais opções?").
    # The vector remains available to RAG even when branch ranking itself can
    # be skipped because an exact selector already won.
    embedding = graph_compiler_v3.query_embeddings([message])[0]
    embedding_ms = round((time.perf_counter() - embedding_started) * 1000, 3)
    if (
        service_resolution.get("resolution_method") == "none"
        and embedding is not None
        and not pending_field_answer
        and not _is_social_or_non_service_value(message)
    ):
        semantic_rows = supabase_client.rank_graph_services_v3(
            persona_id=str(persona["id"]),
            publication_id=str(publication["id"]),
            query_embedding=embedding,
            limit=8,
        )
        semantic_ranking = [
            {
                "branch_anchor_node_id": str(row.get("branch_anchor_node_id") or ""),
                "chunk_id": str(row.get("chunk_id") or ""),
                "score": round(float(row.get("score") or 0), 6),
                "snippet": str(row.get("snippet") or "")[:240],
            }
            for row in semantic_rows
            if row.get("branch_anchor_node_id")
        ]
        service_resolution = {
            **service_resolution,
            "semantic_ranking": semantic_ranking,
            "semantic_threshold": SERVICE_SEMANTIC_MIN_SCORE,
            "semantic_margin_threshold": SERVICE_SEMANTIC_MIN_MARGIN,
        }
        if (
            len(semantic_ranking) >= 2
            and semantic_ranking[0]["score"] >= SERVICE_SEMANTIC_MIN_SCORE
            and semantic_ranking[1]["score"] >= SERVICE_SEMANTIC_MIN_SCORE
            and semantic_ranking[0]["score"] - semantic_ranking[1]["score"]
            < SERVICE_SEMANTIC_MIN_MARGIN
        ):
            service_resolution = {
                **service_resolution,
                "status": "ambiguous",
                "resolution_method": "semantic_anchor_ranking",
                "confirmation": {
                    "kind": "service_disambiguation",
                    "options": semantic_ranking[:2],
                },
            }
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
    branch_package_started = time.perf_counter()
    # A customer can have two branches open at once ("é pra mim e também quero
    # revender"). Retrieving only the focused one left the second branch's
    # knowledge invisible for the whole turn, so the agent could not answer
    # about something it had just agreed to talk about.
    #
    # The focused branch keeps priority: only ITS structural content is
    # required, so a second branch can never displace the knowledge the next
    # question depends on. The extra branches contribute optional candidates
    # that compete for whatever slots and tokens remain, which is the
    # per-branch pruning the shared prompt budget needs.
    secondary_branches = _secondary_retrieval_branches(
        retrieval_branch,
        active_branch_node_id=active_branch,
        active_branch_node_ids=active_branches,
        branch_anchors=document.get("branch_anchors") or [],
    )

    def _search(anchor: str) -> list[dict[str, Any]]:
        return supabase_client.search_graph_rag_v3(
            persona_id=str(persona["id"]), publication_id=publication["id"],
            branch_node_id=anchor, query=message, query_embedding=embedding,
            active_path_node_ids=((document.get("coordinates") or {}).get(anchor) or {}).get("path_node_ids") or [],
            missing_fields=missing, limit=48,
            agent_slug=str((persona.get("config") or {}).get("agent_slug") or "agent"),
        )

    rows = list(_search(retrieval_branch))
    seen_chunk_ids = {
        str(row.get("chunk_id") or row.get("id")) for row in rows
    }
    for anchor in secondary_branches:
        for row in _search(anchor):
            chunk_id = str(row.get("chunk_id") or row.get("id"))
            if chunk_id and chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk_id)
                rows.append({**row, "retrieved_from_branch_node_id": anchor})
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
    merged = {
        str(row.get("chunk_id") or row.get("id")): row
        for row in [*rows, *structural]
    }
    required_structural = _required_structural_chunks(
        structural, required_node_ids=required_nodes,
    )
    reserved: list[dict[str, Any]] = []
    reserved_ids: set[str] = set()
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
        "pending_field": pending_field or None,
        "confirmation_templates": document.get("confirmation_templates") or {},
        "service_resolution_policy": document.get("service_resolution_policy") or {},
        "no_journey_fallback_reply": _no_journey_fallback_reply(document),
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
        # Reached only when the deterministic greeting turn did not return
        # above, so any eligible greeting here is one that must be prefixed
        # onto a model reply -- whether it named a service or asked a doubt.
        "greeting_response": (
            greeting_prefix.get("response") if greeting_prefix else None
        ),
        "retrieval_branch_node_id": retrieval_branch,
        "interrogative_clause": interrogative_clause or None,
        "faq_selection_method": "vector_rag",
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
                                      "asked_field_keys": asked_field_keys,
                                      "_ledger_revision": ledger.get("revision") or 0},
        rag_nodes=[document["node_by_id"][node_id] for node_id in by_source if node_id in document["node_by_id"]],
        rag_paths=[card.path for card in cards],
        rag_chunks=[_compact_prompt_chunk(row) for row in package],
        context_cards=cards,
        # Every published anchor, with the graph's own alias vocabulary, so the
        # model can map "é pra mim" onto a real anchor id. The aliases are
        # graph data travelling to the model -- the backend itself no longer
        # matches on them.
        system_prompt=prompt, available_services=[{
            "branch_anchor_node_id": anchor,
            "slug": document["node_by_id"][anchor]["slug"],
            "label": document["node_by_id"][anchor]["title"],
            "aliases": [
                str(alias) for alias in
                ((document["node_by_id"][anchor].get("data") or {}).get("aliases") or [])
            ],
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
        pending_field_key=str(pending_field.get("key") or "") or None,
        pending_question_node_id=str(pending_field.get("question_node_id") or "") or None,
        pending_confirmation_ref=_pending_confirmation_ref(
            operational_mode, ledger, str(journey.get("id") or "") or None,
        ),
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


def _publication_document_and_contract(
    context: ConversationContext,
    model_observation: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The live graph document and this turn's contract, for validation.

    Returns empties when the turn carries no interpretation, so a legacy
    proposal turn never pays for a publication fetch.
    """
    if not isinstance((model_observation or {}).get("interpretation"), dict):
        return {}, {}
    # Built from what the turn already carries rather than re-fetching the
    # publication: `available_services` is every published anchor and
    # `branch_node_ids` is the branch closure, so the ids the validator checks
    # against are the same ones this turn was actually built from -- and the
    # check costs no round trip.
    anchors = [
        str(service.get("branch_anchor_node_id") or "")
        for service in context.available_services
        if service.get("branch_anchor_node_id")
    ]
    known_ids = dict.fromkeys([
        *anchors,
        *[str(node_id) for node_id in context.branch_node_ids if node_id],
        *[str(card.id) for card in context.context_cards],
        *([context.active_branch_node_id] if context.active_branch_node_id else []),
        *context.active_branch_node_ids,
    ])
    document = {
        "branch_anchors": anchors,
        "node_by_id": {node_id: {"id": node_id} for node_id in known_ids},
        "coordinates": {},
    }
    return document, context.graph_contract or {}


def _secondary_retrieval_branches(
    retrieval_branch: str,
    *,
    active_branch_node_id: str | None,
    active_branch_node_ids: Sequence[str],
    branch_anchors: Sequence[str],
) -> list[str]:
    """Active branches whose knowledge the turn should also see.

    The focused branch is excluded because it is retrieved first and keeps
    priority: only its content is required, so a second branch can never
    displace the knowledge the next question depends on.

    An anchor no longer published is dropped rather than queried -- a stale
    ledger row from a rolled-back publication must not resurrect its content.
    """
    published = set(branch_anchors)
    return [
        anchor for anchor in dict.fromkeys([
            *([active_branch_node_id] if active_branch_node_id else []),
            *active_branch_node_ids,
        ])
        if anchor and anchor != retrieval_branch and anchor in published
    ]


def _validated_interpretation(
    context: ConversationContext,
    model_observation: dict[str, Any] | None,
    document: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> semantic_interpretation_validator.ValidationResult | None:
    """Parse and prove the model's structured reading of this inbound.

    Returns None when the turn carried no interpretation at all (a repair
    call, a contract probe, or a workflow still on the previous contract), so
    callers keep their existing behaviour instead of inventing one.

    Validation happens in two stages because the graph document is not loaded
    until later in the turn. Called WITHOUT a document -- as `decide()` does,
    to reach the confirmation short-circuits before paying for a publication
    fetch -- everything that needs only the message and the pending state is
    proved, and anything graph-scoped (branch anchors above all) is dropped
    for lack of a graph to check against. Callers that hold a real document
    must therefore re-prove graph-scoped elements against it; passing a
    document here does the whole job in one pass.
    """
    raw = semantic_conversation_policy.adapt_model_envelope(
        (model_observation or {}).get("interpretation")
    )
    if not isinstance(raw, dict):
        return None
    try:
        interpretation = SemanticInterpretation.model_validate(raw)
    except ValidationError:
        return None
    return semantic_interpretation_validator.validate_interpretation(
        interpretation,
        message=_latest_user_message(context),
        document=document or {},
        contract=contract or {},
        context=context,
    )


def _product_interest_nodes_from_validation(
    result: semantic_interpretation_validator.ValidationResult | None,
    document: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project validated product/group entities into the existing cart JSON."""
    if result is None:
        return []
    node_by_id = document.get("node_by_id") or {}
    projected: list[dict[str, Any]] = []
    for entity in result.interpretation.entities:
        if entity.kind.value != "product" or not entity.node_id:
            continue
        node = node_by_id.get(str(entity.node_id)) or {}
        if str(node.get("node_type") or "") not in {"product", "product_group"}:
            continue
        projected.append({
            "node_id": str(entity.node_id),
            "node_type": str(node.get("node_type")),
            "value": entity.value,
            "evidence_span": entity.evidence_span,
        })
    return projected


def _merge_product_interest_nodes(
    existing: Any, additions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dedupe graph-backed product interests without inventing state."""
    merged: dict[str, dict[str, Any]] = {}
    for row in existing if isinstance(existing, list) else []:
        if isinstance(row, dict) and row.get("node_id"):
            merged[str(row["node_id"])] = row
    for row in additions:
        if row.get("node_id"):
            merged[str(row["node_id"])] = row
    return list(merged.values())


def _with_semantic_branch_fallback(
    context: ConversationContext,
    model_observation: dict[str, Any] | None,
    document: dict[str, Any],
) -> ConversationContext:
    """Let the model's proved branch reading stand in for a literal miss.

    Only fills a gap: if the literal resolver already resolved or flagged an
    ambiguity, its result wins untouched. Returns a copy -- no persisted state
    is mutated here.
    """
    existing = context.retrieval_trace.get("service_resolution") or {}
    # `needs_confirmation` is the literal matcher saying it is NOT sure -- a
    # fuzzy or merely-mentioned candidate. Treating that as settled is what
    # kept "uso próprio mesmo" looping: the model had already read it exactly
    # right, with a span from the message and a real anchor, and was ignored in
    # favour of the matcher's hesitation. A proved semantic reading outranks
    # uncertainty; it never overrides a confident `resolved`, and never
    # silences a genuine `ambiguous` between two anchors, which still deserves
    # a question rather than a guess.
    if existing.get("status") in {"resolved", "ambiguous"}:
        return context
    validation = _validated_interpretation(context, model_observation, document)
    if validation is None:
        return context
    resolution = semantic_conversation_policy.semantic_service_resolution(
        validation.interpretation, context, document,
    )
    if not resolution:
        return context
    return context.model_copy(update={
        "retrieval_trace": {
            **context.retrieval_trace,
            "service_resolution": resolution,
        },
    })


def _deterministic_confirmation_decision(
    context: ConversationContext,
    interpretation: SemanticInterpretation | None = None,
) -> tuple[ConversationDecision, AgentResponse] | None:
    """Close or correct a pending qualification from the model's reading.

    Confirmation used to be decided by exact membership in a fixed phrase set,
    so "sim, tá correto" left a qualified lead un-handed-off in production
    (audit 2026-08-21). The wording no longer decides anything: the model says
    what the customer did, the validator proves the span and the pending ref,
    and this function still owns every consequence -- route, stage, handoff
    reason, and the `confirmed_branch_node_ids` stamp that
    commit_graph_turn_and_outbox_v3 (migration 128) consumes to close ledger
    branches.
    """
    if str(context.operational_mode) != "confirmation":
        return None
    if interpretation is None:
        return None
    # A confirmation may share the same message with a product/service doubt.
    # In that case the model must answer the doubt before any terminal handoff;
    # treating the single confirmation component as the whole turn caused a
    # correct catalog question to be silently replaced in production.
    if interpretation.questions:
        return None
    if (
        semantic_conversation_policy.confirms_pending(interpretation, context)
        and interpretation.handoff_requested
        and interpretation.recommended_next_action.value in {"handoff", "close"}
    ):
        # The runtime owns the state transition, never the wording. Proof has
        # validated the model envelope already, so preserve the reply exactly.
        reply = semantic_conversation_policy.interpretation_reply(interpretation)
        if not str(reply or "").strip():
            return None
        state = {
            **context.cart,
            "sdr_state": "handed_off",
            "terminal_handoff": {
                "intent": "qualification_confirmed",
                "emitted": True,
            },
        }
        proof = {
            "valid": True,
            "errors": [],
            "mode": "model_confirmation_handoff",
            "explicit_confirmation": True,
            "missing_fields": [],
            "qualification_complete": True,
            "qualification_incomplete": False,
            "accepted_facts": [],
            "confirmation_state": "qualified_confirmed",
            "model_calls": 1,
            # Every offering (service or product) active on this ledger just
            # had its confirmation cycle accepted -- stamped 'completed' by
            # commit_graph_turn_and_outbox_v3 (migration 128) so a later
            # support turn about the same item never re-opens confirmation,
            # while a genuinely new offering added afterward still can.
            "confirmed_branch_node_ids": list(dict.fromkeys([
                *([context.active_branch_node_id] if context.active_branch_node_id else []),
                *context.active_branch_node_ids,
            ])),
        }
        return (
            ConversationDecision(
                classifier="graph_confirmation_v1",
                intent="qualification_confirmed",
                route=ConversationRoute.HUMAN,
                confidence=1,
                lead_stage="qualificado",
                handoff_reason="graph_qualification_confirmed",
            ),
            AgentResponse(
                reply_text=reply,
                role=ConversationRoute.HUMAN,
                cart_state=state,
                handoff_required=True,
                proof=proof,
                token_usage={
                    "model_calls": 1, "repair_calls": 0, "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0,
                },
            ),
        )
    if semantic_conversation_policy.rejects_pending(interpretation, context):
        reply = semantic_conversation_policy.interpretation_reply(interpretation)
        if not str(reply or "").strip():
            return None
        state = {**context.cart, "sdr_state": "collecting"}
        return (
            ConversationDecision(
                classifier="graph_confirmation_v1",
                intent="qualification_correction_requested",
                route=ConversationRoute.SDR,
                confidence=1,
                lead_stage=str(context.cart.get("_lead_stage") or "engajado"),
            ),
            AgentResponse(
                reply_text=reply,
                role=ConversationRoute.SDR,
                cart_state=state,
                handoff_required=False,
                proof={
                    "valid": True,
                    "errors": [],
                    "mode": "deterministic_confirmation_rejection",
                    "explicit_confirmation": False,
                    "missing_fields": [],
                    "accepted_facts": [],
                    "confirmation_state": "correction_requested",
                    "model_calls": 0,
                },
                token_usage={
                    "model_calls": 0, "repair_calls": 0, "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0,
                },
            ),
        )
    return None


def _restates_pending_candidate(message: str, fact: dict[str, Any]) -> bool:
    """The customer repeating the value is confirming it.

    Asking "Allan Rodrigues is your full name?" and getting "allan
    rodrigues" back is agreement in any human reading of the exchange. The
    runtime used to accept only a short list of literal confirmation
    phrases, so a customer restating the exact value read as a non-answer
    and the same question came back turn after turn.
    """
    confirmation = (fact.get("metadata") or {}).get("confirmation") or {}
    candidate = _normalized_phrase(
        confirmation.get("candidate_title") or confirmation.get("candidate")
    )
    if not candidate:
        return False
    normalized = _normalized_phrase(message)
    return normalized == candidate or any(
        normalized == f"{token} {candidate}" for token in _EXPLICIT_CONFIRMATIONS
    )


def _pending_confirmation_fact(context: ConversationContext) -> dict[str, Any] | None:
    for rows in (context.cart.get("facts_by_key") or {}).values():
        for fact in rows if isinstance(rows, list) else []:
            confirmation = (fact.get("metadata") or {}).get("confirmation")
            if fact.get("status") == "needs_confirmation" and isinstance(confirmation, dict):
                return fact
    return None


def _service_clarification_policy(document: dict[str, Any]) -> dict[str, Any]:
    persona = _persona_node(document) or {}
    conversation_policy = ((persona.get("data") or {}).get("conversation_policy") or {})
    return dict(conversation_policy.get("service_clarification") or {})


def _render_service_clarification(
    document: dict[str, Any], key: str, *, candidate: str = "",
    service_titles: Sequence[str] = (),
) -> str:
    template = str(_service_clarification_policy(document).get(key) or "").strip()
    if not template:
        raise RuntimeError(f"published graph missing service clarification text: {key}")
    return (
        template.replace("{candidate}", candidate)
        .replace("{services}", ", ".join(service_titles))
    ).strip()


def _service_titles(document: dict[str, Any], branch_ids: Sequence[str]) -> list[str]:
    nodes = document.get("node_by_id") or {}
    return [
        str((nodes.get(branch_id) or {}).get("title") or branch_id)
        for branch_id in dict.fromkeys(str(value) for value in branch_ids if value)
    ]


def _service_request_summary(
    document: dict[str, Any], branch_ids: Sequence[str],
) -> str:
    titles = _service_titles(document, branch_ids)
    if not titles:
        return ""
    policy = _service_clarification_policy(document)
    template = str(policy.get("summary_template") or "").strip()
    return template.replace("{services}", ", ".join(titles)).strip() if template else ""


def _deterministic_pending_service_clarification(
    context: ConversationContext,
    interpretation: SemanticInterpretation | None = None,
) -> tuple[ConversationDecision, AgentResponse] | None:
    """Advance the graph-owned add/switch ambiguity ladder without a model.

    The pending fact is the ledger: candidate, proposed operation and attempt
    count all live in its metadata, so retries and resume remain idempotent and
    no schema change is needed.

    This runs only while the ambiguity is still unresolved. Whether the
    customer just resolved it -- by confirming, rejecting, or naming a branch
    -- is read from the interpretation, not from phrase and regex markers, so
    an answer phrased in any ordinary way hands off to the confirmation path
    instead of being re-asked.
    """
    pending = _pending_confirmation_fact(context)
    if not pending:
        return None
    confirmation = dict((pending.get("metadata") or {}).get("confirmation") or {})
    if (
        _confirmation_capability(confirmation) not in {"service", "branch_selector"}
        or not confirmation.get("operation_ambiguous")
    ):
        return None
    message = _latest_user_message(context)
    current_candidate = str(confirmation.get("branch_anchor_node_id") or "")
    current_resolution = context.retrieval_trace.get("service_resolution") or {}
    new_candidate = str(
        ((current_resolution.get("candidate") or {}).get("branch_anchor_node_id")) or ""
    )
    if new_candidate and new_candidate != current_candidate:
        return None
    if interpretation is not None and (
        semantic_conversation_policy.confirmation_state(interpretation, context).value
        in {"affirm", "reject", "partial"}
        or bool(interpretation.branch_selections)
    ):
        return None

    persona = supabase_client.get_persona(context.persona_slug) or {}
    publication = supabase_client.get_active_graph_publication(
        str(persona.get("id") or "")
    ) or {}
    if (
        str(publication.get("id") or "") != str(context.publication_id or "")
        or str(publication.get("checksum") or "") != str(context.graph_checksum)
    ):
        raise RuntimeError("GraphRAG publication changed during service clarification")
    document = publication.get("document_json") or {}
    attempts = int(confirmation.get("attempts") or 1)
    candidate_title = str(
        confirmation.get("candidate_title") or confirmation.get("candidate") or ""
    )
    possible = _service_titles(
        document,
        [*context.active_branch_node_ids, current_candidate],
    )
    if attempts >= 2:
        reply = _render_service_clarification(
            document, "handoff_message", candidate=candidate_title,
            service_titles=possible,
        )
        proof = {
            "valid": True, "errors": [],
            "mode": "deterministic_service_clarification_handoff",
            "accepted_facts": [], "missing_fields": [],
            "pending_confirmation": confirmation,
            "clarification_attempts": attempts,
            "possible_service_node_ids": list(dict.fromkeys([
                *context.active_branch_node_ids, current_candidate,
            ])),
            "confirmation_state": "clarification_handoff",
            "model_calls": 0,
        }
        return (
            ConversationDecision(
                classifier="graph_service_clarification_v1",
                intent="service_clarification_exhausted",
                route=ConversationRoute.HUMAN, confidence=1,
                lead_stage="engajado", handoff_reason="service_clarification_exhausted",
            ),
            AgentResponse(
                reply_text=reply, role=ConversationRoute.HUMAN,
                cart_state={**context.cart, "sdr_state": "handed_off"},
                handoff_required=True, proof=proof,
                token_usage={"model_calls": 0, "repair_calls": 0},
            ),
        )

    next_confirmation = {**confirmation, "attempts": attempts + 1}
    next_fact = {
        **pending,
        "source_message_id": _source_message_id(context.messages),
        "evidence_span": message.strip(),
        "metadata": {
            **dict(pending.get("metadata") or {}),
            "confirmation": next_confirmation,
        },
    }
    grouped = {
        str(key): list(values)
        for key, values in (context.cart.get("facts_by_key") or {}).items()
    }
    key = str(next_fact.get("field_key") or "")
    owner = str(next_fact.get("owner_node_id") or "")
    grouped[key] = [
        fact for fact in grouped.get(key, [])
        if str(fact.get("owner_node_id") or "") != owner
    ] + [next_fact]
    reply = _render_service_clarification(
        document, "retry_question", candidate=candidate_title,
        service_titles=possible,
    )
    proof = {
        "valid": True, "errors": [],
        "mode": "deterministic_service_clarification_retry",
        "accepted_facts": [next_fact], "missing_fields": [key],
        "pending_confirmation": next_confirmation,
        "clarification_attempts": attempts + 1,
        "confirmation_state": "field_confirmation",
        "model_calls": 0,
    }
    return (
        ConversationDecision(
            classifier="graph_service_clarification_v1",
            intent="service_clarification_retry",
            route=ConversationRoute.SDR, confidence=1, lead_stage="engajado",
        ),
        AgentResponse(
            reply_text=reply, role=ConversationRoute.SDR,
            cart_state={**context.cart, "facts_by_key": grouped},
            handoff_required=False, proof=proof,
            token_usage={"model_calls": 0, "repair_calls": 0},
        ),
    )


def _confirmation_prompt_for_fact(
    document: dict[str, Any], fact: dict[str, Any],
    active_branch_node_ids: list[str],
    recent_replies: Sequence[str] = (),
) -> tuple[str, dict[str, Any]]:
    """Render only graph-published copy for one persisted candidate."""
    confirmation = dict((fact.get("metadata") or {}).get("confirmation") or {})
    capability = _confirmation_capability(confirmation)
    if capability in {"name", "common_fact"}:
        return _confirmation_template(
            document, str(
                confirmation.get("template_key")
                or ("name" if capability == "name" else "fact")
            ),
            candidate=str(confirmation.get("candidate") or ""),
            recent_replies=recent_replies,
        ), confirmation
    if capability in {"service", "branch_selector"}:
        return _confirmation_template(
            document,
            _service_candidate_template_key(confirmation, active_branch_node_ids),
            candidate=str(
                confirmation.get("candidate_title")
                or confirmation.get("candidate") or ""
            ),
            recent_replies=recent_replies,
        ), confirmation
    raise RuntimeError("unsupported persisted confirmation candidate")


def _confirmation_capability(confirmation: dict[str, Any]) -> str:
    return str(
        confirmation.get("capability") or confirmation.get("kind") or "common_fact"
    )


def _aggregate_confirmation_state(
    document: dict[str, Any], active: list[str], grouped: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, dict[str, Any]]:
    if active:
        missing = graph_proof_checker_v3.aggregate_missing_fields(
            document.get("branch_contracts") or {}, active, grouped,
        )
        askable = graph_proof_checker_v3.aggregate_askable_fields(
            document.get("branch_contracts") or {}, active, grouped,
        )
        required = graph_proof_checker_v3.aggregate_required_field_count(
            document.get("branch_contracts") or {}, active, grouped,
        )
        question_contract = next(
            (
                contract for contract in (document.get("branch_contracts") or {}).values()
                if any(
                    field.get("question_node_id") == (askable[0].get("question_node_id") if askable else None)
                    for field in contract.get("fields") or []
                )
            ),
            (document.get("branch_contracts") or {}).get(active[-1]) or {},
        )
        return missing, askable, required, question_contract
    contract = document.get("common_contract") or {}
    scoped = _facts_for_contract(contract, grouped)
    return (
        graph_proof_checker_v3.pending_fields(contract, scoped),
        graph_proof_checker_v3.askable_pending_fields(contract, scoped),
        graph_proof_checker_v3.required_field_count(contract, scoped),
        contract,
    )


def _deterministic_pending_fact_confirmation(
    context: ConversationContext,
    interpretation: SemanticInterpretation | None = None,
) -> tuple[ConversationDecision, AgentResponse] | None:
    """Apply the customer's answer to a pending fact/service confirmation.

    Accept/reject now comes from the model's proved reading rather than from
    phrase and regex markers. Everything downstream is unchanged and still
    deterministic: the publication re-check, `check_service_operations`, the
    stale-focus guard on a confirmed switch, and evidence provenance all still
    trace back to the literal inbound.
    """
    pending = _pending_confirmation_fact(context)
    if not pending or interpretation is None:
        return None
    # Evidence provenance stays the literal inbound, never the model's
    # paraphrase -- the spans persisted below must be the customer's words.
    message = _latest_user_message(context)
    rejected_confirmation = semantic_conversation_policy.rejects_pending(
        interpretation, context
    )
    accepted_confirmation = (
        not rejected_confirmation
        and semantic_conversation_policy.confirms_pending(interpretation, context)
    )
    if not (accepted_confirmation or rejected_confirmation):
        return None

    persona = supabase_client.get_persona(context.persona_slug) or {}
    publication = supabase_client.get_active_graph_publication(str(persona.get("id") or "")) or {}
    if (
        str(publication.get("id") or "") != str(context.publication_id or "")
        or str(publication.get("checksum") or "") != str(context.graph_checksum)
    ):
        raise RuntimeError("GraphRAG publication changed during pending confirmation")
    document = publication.get("document_json") or {}
    confirmation = dict((pending.get("metadata") or {}).get("confirmation") or {})
    capability = _confirmation_capability(confirmation)
    selection_key = branch_selection_field_key(document)
    source_message_id = _source_message_id(context.messages)
    grouped = {
        str(key): list(values)
        for key, values in (context.cart.get("facts_by_key") or {}).items()
    }
    previous_active = list(dict.fromkeys([
        *([context.active_branch_node_id] if context.active_branch_node_id else []),
        *context.active_branch_node_ids,
    ]))
    active = list(previous_active)
    focus = context.active_branch_node_id
    accepted_facts: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    consumed_spans: list[dict[str, Any]] = []

    def replace_fact(fact: dict[str, Any]) -> None:
        key = str(fact.get("field_key") or "")
        owner = str(fact.get("owner_node_id") or "")
        grouped[key] = [
            current for current in grouped.get(key, [])
            if str(current.get("owner_node_id") or "") != owner
        ] + [fact]
        accepted_facts.append(fact)

    if capability in {"name", "common_fact"}:
        fact = {
            "field_key": str(confirmation.get("field_key") or pending.get("field_key") or ""),
            "owner_node_id": str(confirmation.get("owner_node_id") or pending.get("owner_node_id") or ""),
            "status": "known" if accepted_confirmation else "invalid",
            "value": str(confirmation.get("candidate") or "") if accepted_confirmation else None,
            "source_message_id": source_message_id,
            "evidence_span": message.strip(),
            "confidence": 1.0,
            "metadata": {
                "confirmation": {
                    **confirmation,
                    "transition": "confirmed" if accepted_confirmation else "rejected",
                    "confirmed_by_message_id": source_message_id,
                },
            },
        }
        replace_fact(fact)
    elif capability in {"service", "branch_selector"}:
        anchor = str(confirmation.get("branch_anchor_node_id") or pending.get("owner_node_id") or "")
        action = str(confirmation.get("action") or "add")
        if accepted_confirmation:
            # The customer may confirm AND redirect in one breath ("yes, but
            # switch it to the other one"). The anchor is re-proved against the
            # publication loaded above -- decide() validates the interpretation
            # before the document is known, so a branch selection can only be
            # trusted here, where the real anchor set exists.
            # This ladder confirms ONE pending candidate, so only the first
            # proved redirect applies here; a turn that opens several branches
            # at once is resolved by the service resolution path instead.
            published_anchors = set(document.get("branch_anchors") or [])
            selection = next(
                (
                    item for item in interpretation.branch_selections
                    if str(item.branch_anchor_node_id or "") in published_anchors
                    and item.action.value != "none"
                ),
                None,
            )
            if selection is not None:
                action = selection.action.value
                if action == "select":
                    action = "add"
                anchor = str(selection.branch_anchor_node_id)
            if action == "add" and anchor in active:
                action = "keep"
            replace_anchor = str(
                confirmation.get("replace_branch_node_id")
                or (focus if action == "switch" else "") or ""
            )

            def confirmed_operation(operation_action: str, operation_anchor: str) -> dict[str, Any]:
                return {
                    "action": operation_action,
                    "branch_anchor_node_id": operation_anchor,
                    "branch_path_checksum": str(
                        ((document.get("coordinates") or {}).get(operation_anchor) or {})
                        .get("path_checksum") or ""
                    ),
                    "evidence_span": message.strip(),
                    "evidence_type": "confirmed_candidate",
                    "resolution_method": str(
                        confirmation.get("method") or "confirmed_candidate"
                    ),
                    "score": confirmation.get("score"),
                    "margin": confirmation.get("margin"),
                }

            if action == "switch":
                if not replace_anchor or replace_anchor not in active:
                    raise RuntimeError("confirmed service switch has stale previous focus")
                operations = [
                    confirmed_operation("drop", replace_anchor),
                    confirmed_operation("add", anchor),
                ]
            else:
                operations = [confirmed_operation(action, anchor)]
            consumed_spans = [
                {
                    "text": message.strip(), "start": 0, "end": len(message.strip()),
                    "branch_anchor_node_id": operation["branch_anchor_node_id"],
                    "evidence_type": "confirmed_candidate",
                }
                for operation in operations
            ]
            service_proof = graph_proof_checker_v3.check_service_operations(
                document=document,
                message=message,
                operations=operations,
                active_branch_node_ids=active,
                consumed_service_spans=consumed_spans,
            )
            if not service_proof["valid"]:
                raise RuntimeError("confirmed service candidate failed backend proof")
            active = list(service_proof["next_active_branch_node_ids"])
            focus = anchor if action in {"add", "keep", "switch"} else (
                active[-1] if active else None
            )
            if action in {"add", "keep", "switch"}:
                if action == "switch":
                    replace_fact({
                        "field_key": selection_key, "owner_node_id": replace_anchor,
                        "status": "invalid", "value": None,
                        "source_message_id": source_message_id,
                        "evidence_span": message.strip(), "confidence": 1.0,
                        "metadata": {"confirmation": {
                            **confirmation, "transition": "confirmed_switch_drop",
                        }},
                    })
                node = (document.get("node_by_id") or {}).get(anchor) or {}
                replace_fact({
                    "field_key": selection_key, "owner_node_id": anchor,
                    "status": "known",
                    "value": str(node.get("slug") or node.get("title") or anchor),
                    "source_message_id": source_message_id,
                    "evidence_span": message.strip(), "confidence": 1.0,
                    "metadata": {
                        "source": "service_confirmation",
                        "confirmation": {**confirmation, "transition": "confirmed"},
                    },
                })
            else:
                replace_fact({
                    "field_key": selection_key, "owner_node_id": anchor,
                    "status": "invalid", "value": None,
                    "source_message_id": source_message_id,
                    "evidence_span": message.strip(), "confidence": 1.0,
                    "metadata": {"confirmation": {**confirmation, "transition": "confirmed_removal"}},
                })
        else:
            previous_fact = confirmation.get("previous_fact")
            if isinstance(previous_fact, dict) and previous_fact.get("status") == "known":
                replace_fact({
                    **previous_fact,
                    "field_key": selection_key, "owner_node_id": anchor,
                    "source_message_id": source_message_id,
                    "evidence_span": message.strip(), "confidence": 1.0,
                    "metadata": {
                        **(previous_fact.get("metadata") or {}),
                        "confirmation": {**confirmation, "transition": "rejected"},
                    },
                })
            else:
                replace_fact({
                    "field_key": selection_key, "owner_node_id": anchor,
                    "status": "invalid", "value": None,
                    "source_message_id": source_message_id,
                    "evidence_span": message.strip(), "confidence": 1.0,
                    "metadata": {"confirmation": {**confirmation, "transition": "rejected"}},
                })
    else:
        return None

    remaining_pending = next(
        (
            fact
            for rows in grouped.values()
            for fact in rows
            if fact.get("status") == "needs_confirmation"
            and isinstance((fact.get("metadata") or {}).get("confirmation"), dict)
        ),
        None,
    )
    next_confirmation: dict[str, Any] = {}

    missing, askable, required_count, question_contract = _aggregate_confirmation_state(
        document, active, grouped,
    )
    askable_question_ids = {
        str(field.get("question_node_id") or "")
        for field in askable if field.get("question_node_id")
    }
    _, _, requested_field_key, requested_legacy_question_id = (
        semantic_conversation_policy.interpretation_segments(interpretation)
    )
    requested_question_id = requested_legacy_question_id or next(
        (
            str(field.get("question_node_id") or "")
            for field in askable
            if str(field.get("key") or "") == str(requested_field_key or "")
            and field.get("question_node_id")
        ),
        None,
    )
    next_question_id = (
        requested_question_id
        if requested_question_id in askable_question_ids
        else None
    )
    complete = bool(active and not missing and not remaining_pending)
    final_confirmation_pending = complete and accepted_confirmation
    if remaining_pending:
        next_confirmation = dict(
            ((remaining_pending.get("metadata") or {}).get("confirmation") or {})
        )
        next_question_id = None
    # This path consumes confirmation metadata, not conversational authorship.
    # Preserve the model's grounded wording byte-for-byte; terminal state,
    # branch state and the next-question id remain independently auditable.
    reply = semantic_conversation_policy.interpretation_reply(interpretation)
    if not reply:
        return None
    asked = list(context.cart.get("asked_question_node_ids") or [])
    if next_question_id:
        asked.append(next_question_id)
    projection = (
        (document.get("branch_contracts") or {}).get(focus)
        or document.get("common_contract") or {}
    )
    state = {
        **context.cart,
        "facts": _facts_for_contract(projection, grouped),
        "facts_by_key": grouped,
        "active_branch_node_id": focus,
        "active_branch_node_ids": active,
        "asked_question_node_ids": asked,
        "sdr_state": "awaiting_confirmation" if final_confirmation_pending else "collecting",
    }
    proof = {
        "valid": True, "errors": [], "mode": "deterministic_field_confirmation",
        "explicit_confirmation": False,
        "field_confirmation_transition": "confirmed" if accepted_confirmation else "rejected",
        "resolved_confirmation": confirmation,
        "pending_confirmation": next_confirmation or None,
        "accepted_facts": accepted_facts,
        "missing_fields": [str(field.get("key") or "") for field in missing],
        "required_field_count": required_count,
        "next_question_node_id": next_question_id,
        "qualification_complete": complete,
        "collection_complete": complete,
        "confirmation_state": (
            "field_confirmation" if remaining_pending
            else "awaiting_confirmation" if final_confirmation_pending
            else "collecting"
        ),
        "service_operations": operations,
        "applied_service_operations": operations,
        "service_operation_proof": (
            graph_proof_checker_v3.check_service_operations(
                document=document, message=message, operations=operations,
                active_branch_node_ids=previous_active,
                consumed_service_spans=consumed_spans,
            ) if operations else {"valid": True, "errors": [], "operations": []}
        ),
        "consumed_service_spans": consumed_spans,
        "previous_active_branch_node_ids": previous_active,
        "next_active_branch_node_ids": active,
        "previous_active_branch_node_id": context.active_branch_node_id,
        "next_active_branch_node_id": focus,
        "branch_focus_invariant": (not active and focus is None) or focus in set(active),
        "model_calls": 0,
    }
    return (
        ConversationDecision(
            classifier="graph_field_confirmation_v1",
            intent="field_confirmation_resolved",
            route=ConversationRoute.SDR,
            confidence=1,
            lead_stage="engajado",
        ),
        AgentResponse(
            reply_text=reply or None,
            role=ConversationRoute.SDR,
            cart_state=state,
            handoff_required=False,
            proof=proof,
            token_usage={
                "model_calls": 0, "repair_calls": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "total_tokens": 0,
            },
        ),
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
    selection_key = str(
        ((_service_selection_field(context.graph_contract) or {}).get("key") or "servico")
    )
    service_fact = (state.get("facts") or {}).get(selection_key) or {}
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


def _no_journey_reply(context: ConversationContext, response: AgentResponse) -> str:
    proved_doubt = (
        response.proof.get("text")
        if response.proof.get("doubt_resolution") == "answered" else None
    )
    candidates = [proved_doubt]
    if response.proof.get("valid"):
        candidates.extend([
            response.proposal.reply if response.proposal else None,
            str(response.reply_text or ""),
        ])
    candidates.append(context.retrieval_trace.get("no_journey_fallback_reply"))
    reply = next((str(value).strip() for value in candidates if str(value or "").strip()), "")
    if not reply:
        raise RuntimeError("published graph missing no-journey fallback reply")
    return reply


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
        "reply_text": _no_journey_reply(context, response),
        "cart_state": dict(context.cart),
        "handoff_required": False,
        "proposal": proposal,
        "proof": {
            **response.proof,
            "model_proposal_errors": response.proof.get("errors") or [],
            "valid": True, "errors": [], "fallback_used": True,
            "fallback_applied": "no_journey_policy_v4",
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
    deterministic_intent = str(
        context.retrieval_trace.get("deterministic_intent") or ""
    ).strip()
    deterministic_classifier = decision.classifier
    deterministic_cart_state = response.cart_state
    deterministic_confirmation_state = response.proof.get("confirmation_state")
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
    # A graph-owned deterministic decision is already stronger evidence than
    # the model interaction observation. In particular, a greeting after a
    # terminal journey legitimately uses journey_action=none, but the generic
    # no-journey policy used to overwrite only final_decision.intent with
    # ``unclear``. The proof still said deterministic_greeting/greeting, so
    # the durable envelope contradicted itself. Preserve the authoritative
    # decision while still applying the no-journey mutation guard.
    if deterministic_intent:
        decision = decision.model_copy(update={
            "classifier": deterministic_classifier,
            "intent": deterministic_intent,
        })
        response = response.model_copy(update={
            "cart_state": deterministic_cart_state,
            "proof": {
                **response.proof,
                "confirmation_state": deterministic_confirmation_state,
            },
        })
        interaction_observation = {
            "kind": deterministic_intent,
            "evidence_span": _latest_user_message(context),
            "confidence": 1,
            "authority": "deterministic_graph_policy",
        }
    else:
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
    context: ConversationContext, *, model_observation: dict[str, Any] | None
) -> tuple[ConversationDecision, AgentResponse]:
    # Validated against the live graph, not in a vacuum: without a document and
    # a contract every anchor and field key is "unknown" and the model's whole
    # reading is discarded -- which is exactly the failure this layer exists to
    # remove. The publication is only fetched for a turn that actually carries
    # an interpretation.
    validation = _validated_interpretation(
        context, model_observation,
        *_publication_document_and_contract(context, model_observation),
    )
    interpretation = validation.interpretation if validation else None
    # n8n/model-owned turns never take a deterministic dialogue shortcut.
    # These handlers remain available only to the manually selected
    # deterministic engine, whose call carries no model observation.
    # Confirmation reconciliation consumes model metadata but never authors
    # public copy. It remains active for both engines; the graph-authored
    # clarification utterance is a real deterministic shortcut and stays
    # exclusive to the manually selected deterministic engine.
    deterministic = (
        _deterministic_pending_fact_confirmation(context, interpretation)
        or _deterministic_confirmation_decision(context, interpretation)
    )
    if deterministic is None and model_observation is None:
        deterministic = _deterministic_pending_service_clarification(
            context, interpretation
        )
    decision, response = deterministic or _decide(
        context, model_observation=model_observation,
    )
    if validation is not None:
        response = response.model_copy(update={
            "proof": {**response.proof, **validation.as_proof()},
        })
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
    return _apply_journey_policy(
        context, decision, audited, model_observation=model_observation,
    )


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
        or (
            str(operation.get("evidence_span") or "").strip()
            and str(operation.get("branch_path_checksum") or "").strip()
        )
    ]
    return {**raw, "service_operations": operations}


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
    selection_key = str(
        ((_service_selection_field(context.graph_contract) or {}).get("key") or "servico")
    )
    if resolution.get("candidate"):
        candidate = dict(resolution["candidate"])
        message = _latest_user_message(context)
        interval = _fact_span_interval(message, candidate.get("evidence_span"))
        reserved = [
            other
            for fact in proposal.extracted_facts
            if fact.field_key != selection_key
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
        if fact.field_key != selection_key
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


def _confirmation_template(
    document: dict[str, Any], key: str, *, candidate: str = "", options: str = "",
    recent_replies: Sequence[str] = (),
) -> str:
    """Published confirmation copy, in a wording this conversation has not heard.

    A persona may publish one string or a list of equivalent phrasings. The
    list matters because a confirmation that comes back word for word is
    exactly what a customer reads as a stuck agent -- and the repetition
    guard, seeing a duplicate, would otherwise strip the question and leave
    only the acknowledgement.
    """
    published = (document.get("confirmation_templates") or {}).get(key)
    if published is None:
        published = _service_clarification_policy(document).get(key)
    variants = published if isinstance(published, list) else [published]
    rendered = [
        text.replace("{candidate}", candidate).replace("{options}", options)
        for value in variants
        if (text := str(value or "").strip())
    ]
    if not rendered:
        raise RuntimeError(f"published graph missing confirmation template: {key}")
    return _unrepeated_variant(rendered, recent_replies) or rendered[0]


def _service_candidate_template_key(
    candidate: dict[str, Any], active_branch_node_ids: list[str],
) -> str:
    if candidate.get("operation_ambiguous") and active_branch_node_ids:
        return "add_or_switch_question"
    action = str(candidate.get("action") or "add")
    if action == "drop":
        return "service_removal"
    if action == "switch":
        return "service_switch"
    if action == "keep":
        return "service_selection"
    if active_branch_node_ids:
        return "service_addition"
    return "service_selection"


def _decide(
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
    manual_deterministic = model_observation is None
    if manual_deterministic and context.retrieval_trace.get("deterministic_intent") == "greeting":
        question_id = context.retrieval_trace.get("next_question_node_id")
        greeting_node_id = context.retrieval_trace.get("greeting_response_node_id")
        evidence_node_ids = list(dict.fromkeys(
            node_id for node_id in (greeting_node_id, question_id) if node_id
        ))
        asked = list(context.cart.get("asked_question_node_ids") or [])
        if question_id and question_id not in asked:
            asked.append(question_id)
        state = {
            **context.cart,
            "asked_question_node_ids": asked,
            "active_branch_node_id": context.active_branch_node_id,
            "active_branch_node_ids": list(context.active_branch_node_ids),
            "sdr_state": (
                "handed_off"
                if str(context.operational_mode) == "post_qualification_support"
                else str(context.journey_state)
            ),
        }
        proof = {
            "valid": True,
            "errors": [],
            "mode": "deterministic_greeting",
            "accepted_facts": [],
            "missing_fields": context.retrieval_trace.get("missing_fields") or [],
            "asked_field_key": context.retrieval_trace.get("asked_field_key"),
            "model_calls": 0,
            "confirmation_state": (
                "post_qualification_support"
                if str(context.operational_mode) == "post_qualification_support"
                else str(context.journey_state)
            ),
        }
        return (
            ConversationDecision(
                classifier="graph_intent_v3", intent="greeting",
                route=ConversationRoute.SDR, confidence=1,
                lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                evidence_node_ids=evidence_node_ids,
            ),
            AgentResponse(
                reply_text=str(context.retrieval_trace.get("deterministic_reply") or "") or None,
                role=ConversationRoute.SDR,
                evidence_node_ids=evidence_node_ids,
                cart_state=state, handoff_required=False, proof=proof,
                token_usage={"model_calls": 0, "repair_calls": 0, "prompt_tokens": 0,
                             "completion_tokens": 0, "total_tokens": 0},
            ),
        )
    if manual_deterministic and (
        (context.retrieval_trace.get("service_resolution") or {}).get("status")
        == "ambiguous"
    ):
        return _service_disambiguation_response(context)
    parse_errors = [
        str(value) for value in (
            observation.get("proposal_parse_errors")
            or observation.get("interpretation_parse_errors")
            or []
        )
    ]
    # A turn on the semantic contract carries `interpretation`, never a
    # `proposal`. Translating it keeps ONE decision path: everything below --
    # branch resolution, fact reconciliation, proof, commit -- is the same
    # well-covered machinery, now sourced from the model's proved reading.
    #
    # The graph has to be loaded before validating, because without a document
    # and a contract every fact and anchor is dropped as unknown. It is loaded
    # only on this path, so a malformed legacy proposal still fails fast
    # without paying for a publication fetch.
    document: dict[str, Any] = {}
    publication: dict[str, Any] = {}
    if isinstance(observation.get("interpretation"), dict):
        persona = supabase_client.get_persona(context.persona_slug) or {}
        publication = supabase_client.get_active_graph_publication(str(persona.get("id") or "")) or {}
        if str(publication.get("id")) != str(context.publication_id) or publication.get("checksum") != context.graph_checksum:
            raise RuntimeError("GraphRAG publication changed during turn")
        document = publication.get("document_json") or {}
    validation = _validated_interpretation(
        context, observation, document, context.graph_contract,
    )
    validated_product_interest_nodes = _product_interest_nodes_from_validation(
        validation, document,
    )
    if validation is not None:
        proposal = semantic_conversation_policy.interpretation_to_proposal(
            validation.interpretation
        )
        raw = proposal.model_dump(mode="json")
        parse_errors = [*parse_errors, *validation.errors]
        if parse_errors:
            return _invalid_proposal_fallback(
                context,
                raw,
                parse_errors,
                repair_attempt=int(observation.get("repair_attempt") or 0),
            )
    else:
        raw = observation.get("proposal") if isinstance(observation.get("proposal"), dict) else observation
        raw = _sanitize_untrusted_service_operations(raw)
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
    if not publication:
        persona = supabase_client.get_persona(context.persona_slug) or {}
        publication = supabase_client.get_active_graph_publication(str(persona.get("id") or "")) or {}
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
    # The literal alias matcher only ever sees phrasings someone published in
    # advance, so "uso próprio mesmo" resolved to nothing and the turn repeated
    # its own question forever (audit 2026-08-21). When it finds nothing, fall
    # back to the model's reading -- already proved by the validator to name a
    # real anchor of THIS graph with a span really present in the message.
    context = _with_semantic_branch_fallback(context, model_observation, document)
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
    proposal = _normalize_referential_service_fact(proposal, context, document)
    proposal = _normalize_servico_owner(proposal, contract)
    owner_scope_branch_ids = list(dict.fromkeys([
        *context.active_branch_node_ids,
        *([context.active_branch_node_id] if context.active_branch_node_id else []),
        *([proposal.branch_anchor_node_id] if proposal.branch_anchor_node_id else []),
    ]))
    owner_scope_contract = {
        "fields": _active_contract_fields(
            document, owner_scope_branch_ids, contract,
        ),
    }
    reconciliation_contract = {
        **contract,
        "fields": owner_scope_contract["fields"],
    }
    reconciliation_facts = (
        _facts_for_contract(reconciliation_contract, grouped_facts)
        if grouped_facts else contract_facts
    )
    proposal = _normalize_unique_published_field_owners(
        proposal, owner_scope_contract,
    )
    proposal = _normalize_fact_source_message_ids(proposal, context)
    proposal, name_field_validation = _reconcile_human_full_name_facts(
        proposal, context=context, contract=reconciliation_contract,
    )
    proposal, consumed_field_validation = _remove_consumed_service_facts(
        proposal, context=context, document=document,
    )
    proposal, invalid_field_validation = _remove_invalid_declared_facts(
        proposal, reconciliation_contract,
    )
    rejected_field_validation = [
        *name_field_validation,
        *consumed_field_validation,
        *invalid_field_validation,
    ]
    proposal = _drop_premature_unknown_for_pending_question(
        proposal,
        context,
        contract,
        contract_facts,
        max_attempts=_question_repetition_max_attempts(contract),
    )
    proposal = _reconcile_direct_answer_to_pending_field(
        proposal, context, reconciliation_contract, reconciliation_facts,
    )
    model_proposed_next_question_node_id = proposal.next_question_node_id
    model_proposed_next_question_field_key = proposal.next_question_field_key
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
    # Branch-operation metadata is an independently discardable component.
    # The legacy wire name says "service", but anchors also represent products
    # and audiences. An invalid operation must not erase a grounded model reply
    # or turn an otherwise valid inbound into silence.
    applied_service_operations = (
        list(service_proof.get("operations") or [])
        if service_proof.get("valid") else []
    )
    service_component_errors = list(service_proof.get("errors") or [])
    proof.update({
        "service_resolution": context.retrieval_trace.get("service_resolution") or {},
        "service_operations": service_operations,
        "model_proposed_service_operations": model_proposed_service_operations,
        "model_service_observations": model_service_observations,
        "applied_service_operations": applied_service_operations,
        "service_operation_rejection_reason": (
            "model_operations_replaced_by_backend_resolver"
            if model_proposed_service_operations != service_operations else None
        ),
        "service_candidate": service_candidate,
        "service_candidate_rejection_reason": service_candidate_rejection,
        "service_operation_proof": service_proof,
        "component_errors": [
            *(proof.get("component_errors") or []),
            *service_component_errors,
        ],
        "errors": [
            *(proof.get("errors") or []),
            *service_component_errors,
        ],
        "consumed_service_spans": (
            (context.retrieval_trace.get("service_resolution") or {})
            .get("consumed_spans") or []
        ),
        "field_validation": [
            *(proof.get("field_validation") or []),
            *rejected_field_validation,
        ],
    })
    package_node_ids = {card.id for card in context.context_cards} | {
        str(value) for value in observation.get("repair_context_node_ids") or [] if value
    } | persona_root_ids
    # FAQ selection and wording belong to vector retrieval + the model. Proof
    # below validates cited published evidence; it never substitutes a
    # canonical FAQ answer for a grounded model response.
    doubt = None
    # An explicit switch/add is only a Phase-A decision on the first pass.
    # Force one directed Phase-B retrieval for the selected branch before
    # any reply or fact can be committed, even if an anchor snippet
    # happened to suffice.
    if (
        int(observation.get("repair_attempt") or 0) == 0
        and proposal.branch_action.value in {"select", "switch", "add"}
        and proposal.branch_anchor_node_id
        != context.retrieval_trace.get("retrieval_branch_node_id")
        and not [
            error for error in proof.get("gating_errors") or []
            if "outside_package" not in error
        ]
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
            "gating_errors": [
                *(proof.get("gating_errors") or []),
                "selected_branch_requires_phase_b",
            ],
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
        retrieval_requirements = [
            item for item in requirements
            if item.get("kind") in {"node", "chunk"} and item.get("id")
        ]
        if retrieval_requirements:
            rows = supabase_client.get_graph_rag_repair_chunks(
                publication_id=publication["id"], branch_node_id=proposal.branch_anchor_node_id,
                requirements=retrieval_requirements,
            )
            repair_chunks = _repair_chunks(rows, retrieval_requirements)
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
    if proof["repair_required"]:
        # One model-owned repair was already attempted. Do not publish the
        # invalid component and do not let the backend synthesize a question.
        proof = {
            **proof,
            "valid": False,
            "gating_errors": [
                *(proof.get("gating_errors") or []),
                "model_repair_exhausted",
            ],
            "errors": [
                *(proof.get("errors") or []),
                "model_repair_exhausted",
            ],
        }
    # Nao existe verbo para "estou so conversando sobre isto". Sem galho ativo e
    # sem nenhuma operacao para aplicar, `keep` e a escolha honesta do modelo, e
    # nao um defeito -- entao ele nao pode, sozinho, custar o turno. Comparar a
    # lista inteira por igualdade tornava a recuperacao refem da ordem e de
    # duplicatas; o que importa e nao sobrar nenhum outro erro.
    discovery_only = (
        context.active_branch_node_id is None
        and proposal.branch_action.value == "none"
        and not applied_service_operations
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
    proof_gates_turn = bool(gating_errors)
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
            operations=applied_service_operations,
            document=document,
            grouped_facts=grouped_facts,
            source_message_id=_source_message_id(context.messages),
        ))
        selection_key = branch_selection_field_key(document)
        if service_candidate and not applied_service_operations:
            previous_service_fact = next(
                (
                    fact for fact in grouped_facts.get(selection_key, [])
                    if str(fact.get("owner_node_id") or "")
                    == str(service_candidate["branch_anchor_node_id"])
                    and fact.get("status") == "known"
                ),
                None,
            )
            accepted_facts.append({
                "field_key": selection_key,
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
                        "kind": "branch",
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
            for stale in grouped_facts.get(selection_key, []):
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
        unanswered_fact = _unanswered_fact_after_question_limit(
            context=context,
            contract=contract,
            ledger_facts=contract_facts,
            proposal=proposal,
            max_attempts=_question_repetition_max_attempts(contract),
            # A customer question is a conversational detour, not refusal to
            # answer the pending field. The model answers it from retrieved
            # knowledge and the qualification budget remains unchanged.
            doubt_answered=(
                _looks_like_customer_question(_latest_user_message(context))
                and not _explicitly_defers_pending_field(
                    _latest_user_message(context)
                )
            ),
        )
        if unanswered_fact:
            accepted_facts = [
                fact
                for fact in accepted_facts
                if not (
                    str(fact.get("field_key") or "") == unanswered_fact["field_key"]
                    and str(fact.get("owner_node_id") or "")
                    == unanswered_fact["owner_node_id"]
                )
            ]
            accepted_facts.append(unanswered_fact)
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
        if applied_service_operations:
            active_branch_ids = list(service_proof["next_active_branch_node_ids"])
        committed_branch = (
            (context.retrieval_trace.get("service_resolution") or {}).get("focused_branch_node_id")
            if applied_service_operations
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
            aggregate_all_askable = graph_proof_checker_v3.aggregate_askable_fields(
                document.get("branch_contracts") or {}, active_branch_ids, next_grouped,
            )
            aggregate_askable = graph_proof_checker_v3.exclude_asked_questions(
                aggregate_all_askable,
                context.cart.get("asked_question_node_ids") or [],
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
            aggregate_all_askable = graph_proof_checker_v3.askable_pending_fields(
                preselection_contract, preselection_facts,
            )
            aggregate_askable = graph_proof_checker_v3.exclude_asked_questions(
                aggregate_all_askable,
                context.cart.get("asked_question_node_ids") or [],
            )
            aggregate_required_count = graph_proof_checker_v3.required_field_count(
                preselection_contract, preselection_facts,
            )
        active_fields = _active_contract_fields(document, active_branch_ids, contract)
        terminal_unconfirmed = _dedupe_fields([
            *aggregate_missing,
            *_unknown_fields(active_fields, next_grouped),
        ])
        # Proof has already established membership, dependencies and pending
        # state for the model's choice. No backend ordering or first-missing
        # fallback is applied here.
        proved_question_id = proof.get("next_question_node_id")
        next_question_id = proved_question_id if any(
            str(field.get("question_node_id") or "")
            == str(proved_question_id or "")
            for field in aggregate_askable
        ) else None
        audit_question_id = (
            next_question_id or model_proposed_next_question_node_id
        )
        question_contract = next(
            (
                candidate for candidate in (document.get("branch_contracts") or {}).values()
                if audit_question_id in (candidate.get("questions") or {})
            ),
            contract,
        )
        qualification_complete = not terminal_unconfirmed and not discovery_only
        qualification_incomplete = bool(
            terminal_unconfirmed and not aggregate_all_askable and not discovery_only
        )
        collection_complete = qualification_complete
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
        # The backend publishes the model's single reply byte-for-byte. It
        # never slices a question, appends graph copy or swaps in fallback
        # prose because an advisory component failed validation.
        reply_seed = str(proposal.reply or "")
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
        reply = reply_seed
        if pending_confirmation_fact:
            next_question_id = None
            confirmation_pending = False
            qualification_complete = False
            qualification_incomplete = False
            collection_complete = False
            terminal_intent = None
        # The model owns every word of the reply. Question metadata is audited
        # below, never converted into backend-authored copy.
        recent_replies = _assistant_replies(context.messages)
        question_text = str(
            ((question_contract.get("questions") or {}).get(audit_question_id or "") or {}).get("text")
            or ""
        )
        repetition = conversation_repetition.assess_repetition(
            current_reply=reply,
            recent_replies=recent_replies,
            question_node_id=audit_question_id,
            question_text=question_text,
            asked_question_node_ids=context.cart.get("asked_question_node_ids") or [],
            max_attempts=_question_repetition_max_attempts(question_contract),
            field_pending=any(
                field.get("question_node_id") == audit_question_id
                for field in aggregate_askable
            ),
            terminal_intent=terminal_intent,
            previous_terminal_intent=str(
                ((context.cart.get("terminal_handoff") or {}).get("intent") or "")
            ) or None,
        )
        # Exactly-once handles duplicate processing. Semantic repetition is a
        # quality observation for the next prompt/evaluator, never permission
        # to rewrite or suppress a valid response.
        repetition_action = (
            "allowed" if repetition["passed"] else "observed_only"
        )
        # Repetition and style belong to production telemetry/WA Validator.
        # They never trigger a model rewrite or deterministic replacement.
        quality_repair_required = False
        repetition_repair_exhausted = False
        empty_model_reply = not str(reply or "").strip()

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
            "product_interest_nodes": _merge_product_interest_nodes(
                context.cart.get("product_interest_nodes"),
                validated_product_interest_nodes,
            ),
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
                    if next_question_id and repetition_action == "allowed"
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
            "repair_required": bool(proof.get("repair_required")) or (
                empty_model_reply and int(observation.get("repair_attempt") or 0) == 0
            ),
            "repair_requirements": [
                *(proof.get("repair_requirements") or []),
                *(
                    [{
                        "kind": "provider",
                        "issue": "empty_response",
                        "instruction": "Return the compact v3 envelope with a non-empty reply.",
                    }]
                    if empty_model_reply and int(observation.get("repair_attempt") or 0) == 0
                    else []
                ),
            ],
            "model_proposed_next_question_node_id": (
                model_proposed_next_question_node_id
                if model_proposed_next_question_node_id != next_question_id
                else None
            ),
            "model_proposed_next_question_field_key": (
                model_proposed_next_question_field_key
            ),
            "fallback_used": False,
            "context_failure_handoff": False,
            "delivery_authorized": bool(
                proof.get("delivery_authorized", proof.get("valid"))
            ) and not empty_model_reply,
            "durable_retry_required": bool(
                empty_model_reply and int(observation.get("repair_attempt") or 0) >= 1
            ),
            "provider_failure_class": "empty_response" if empty_model_reply else None,
            "model_reply_preserved": reply == proposal.reply,
            "quality_warnings": list(dict.fromkeys([
                *(proof.get("quality_warnings") or []),
                *(repetition.get("failures") or []),
            ])),
            "technical_pass": bool(
                proof.get("delivery_authorized", proof.get("valid"))
            ) and not empty_model_reply,
            "quality_pass": bool(proof.get("quality_pass", True))
            and repetition["passed"],
            "model_proposal_errors": [
                *(proof.get("model_proposal_errors") or []),
                *(["empty_model_reply"] if empty_model_reply else []),
            ],
            **(doubt or {}),
        }
        evidence_node_ids = list(dict.fromkeys([
            *proposal.cited_node_ids,
            *((doubt or {}).get("doubt_node_ids") or []),
        ]))
        return (
            ConversationDecision(classifier="graph_proof_checker_v3",
                                 intent=resolved_intent,
                                 route=route, confidence=1, lead_stage="qualificado" if qualification_complete else "engajado",
                                 handoff_reason=(
                                     "graph_terminal_qualification"
                                     if terminal_intent else None
                                 ),
                                 evidence_node_ids=evidence_node_ids),
            AgentResponse(reply_text=reply if not empty_model_reply else None,
                          role=route, evidence_node_ids=evidence_node_ids,
                          cart_state=state,
                          handoff_required=bool(terminal_intent),
                          proposal=proposal, proof=proof),
        )
    # A rejected model proposal may preserve accepted facts, but it never
    # authorizes the backend to choose or append a qualification question.
    # It also never authorizes deterministic fallback copy. A first unsafe
    # commercial confirmation gets one model repair; a persistent violation
    # or publication-identity failure produces no outbound.
    gating_errors = [str(value) for value in proof.get("gating_errors") or []]
    safety_violation = any(
        value == "premature_final_confirmation" for value in gating_errors
    )
    return (
        ConversationDecision(
            classifier="graph_proof_checker_v3",
            intent="delivery_not_authorized",
            route=ConversationRoute.SDR,
            confidence=0,
            lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            handoff_reason=(
                "unsafe_commercial_confirmation" if safety_violation else None
            ),
            evidence_node_ids=[],
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
                "fallback_used": False,
                "context_failure_handoff": False,
                "model_reply_preserved": True,
                "technical_pass": False,
                "quality_pass": False,
                "provider_failure_class": (
                    "other" if safety_violation else None
                ),
                "durable_retry_required": False,
            },
        ),
    )

    proof_facts = (proof.get("ledger") or {}).get("facts") or contract_facts
    fallback_askable = graph_proof_checker_v3.askable_pending_fields(
        contract, proof_facts,
    )
    fallback_id = None
    fallback_missing = graph_proof_checker_v3.pending_fields(contract, proof_facts)

    fallback_grouped = {
        str(key): list(values)
        for key, values in (context.cart.get("facts_by_key") or {}).items()
    }
    if not fallback_grouped:
        for field in contract.get("fields") or []:
            key = str(field.get("key") or "")
            fact = proof_facts.get(key)
            if key and fact:
                fallback_grouped.setdefault(key, []).append(fact)
    for fact in proof.get("accepted_facts") or []:
        key = str(fact.get("field_key") or "")
        owner = str(fact.get("owner_node_id") or "")
        fallback_grouped[key] = [
            current for current in fallback_grouped.get(key, [])
            if str(current.get("owner_node_id") or "") != owner
        ] + [fact]

    fallback_unconfirmed = _dedupe_fields([
        *fallback_missing,
        *_unknown_fields(contract.get("fields") or [], fallback_grouped),
    ])
    proposal_errors = [str(error) for error in proof.get("errors") or []]
    global_proof_errors = [
        str(error) for error in proof.get("gating_errors") or []
    ]
    context_failure_handoff = True
    # What remains after the model repair boundary is a global proof failure.
    # End observably and never select a field on the model's behalf.
    fallback_id = None
    fallback_complete = not fallback_unconfirmed
    fallback_incomplete = bool(fallback_unconfirmed and not fallback_askable)

    fallback_confirmation_pending = False
    fallback_post_support = False
    fallback_terminal_intent = "context_proof_failed"
    persona_policy = (
        ((_persona_node(document) or {}).get("data") or {})
        .get("conversation_policy") or {}
    )
    fallback = str(
        persona_policy.get("context_failure_handoff_reply") or ""
    ).strip() or CONTEXT_FAILURE_HANDOFF_REPLY
    deterministic_fallback_valid = bool(fallback)
    fallback_proof = {
        **proof,
        "valid": deterministic_fallback_valid,
        "errors": [] if deterministic_fallback_valid else proof.get("errors") or [],
        "model_proposal_errors": proof.get("errors") or [],
        "mode": "model_repair_exhausted_handoff",
        "repair_required": False,
        "fallback_used": True,
        "context_failure_handoff": context_failure_handoff,
        "missing_fields": [field.get("key") for field in fallback_unconfirmed],
        "aggregate_missing_fields": fallback_unconfirmed,
        "qualification_complete": fallback_complete,
        "qualification_incomplete": fallback_incomplete,
        "explicit_confirmation": False,
        "confirmation_state": (
            "awaiting_confirmation" if fallback_confirmation_pending
            else "handed_off" if fallback_terminal_intent
            else "post_qualification_support" if fallback_post_support
            else "collecting"
        ),
    }
    fallback_facts = dict(context.cart.get("facts") or {})
    for fact in proof.get("accepted_facts") or []:
        fallback_facts[str(fact.get("field_key") or "")] = fact
    branch_safe = not global_proof_errors
    fallback_branch = context.active_branch_node_id
    if branch_safe and proposal.branch_action.value in {"select", "switch", "keep", "add"}:
        fallback_branch = proposal.branch_anchor_node_id
    fallback_active_branches = list(context.active_branch_node_ids)
    if proposal.branch_action.value == "add" and branch_safe and proposal.branch_anchor_node_id not in fallback_active_branches:
        fallback_active_branches.append(proposal.branch_anchor_node_id)
    fallback_state = {
        **context.cart,
        "facts": fallback_facts,
        "facts_by_key": fallback_grouped,
        "product_interest_nodes": _merge_product_interest_nodes(
            context.cart.get("product_interest_nodes"),
            validated_product_interest_nodes,
        ),
        "active_branch_node_id": fallback_branch,
        "active_branch_node_ids": fallback_active_branches,
        "sdr_state": (
            "awaiting_confirmation" if fallback_confirmation_pending
            else "handed_off" if fallback_terminal_intent or fallback_post_support
            else "collecting"
        ),
        "asked_question_node_ids": [
            *(context.cart.get("asked_question_node_ids") or []),
            *([fallback_id] if fallback_id else []),
        ],
        **({
            "terminal_handoff": {
                "intent": fallback_terminal_intent,
                "emitted": True,
            }
        } if fallback_terminal_intent else {}),
    }
    fallback_repetition = conversation_repetition.assess_repetition(
        current_reply=fallback,
        recent_replies=[
            str(row.get("content") or row.get("texto") or "")
            for row in context.messages
            if str(row.get("role") or "") == "assistant"
            or str(row.get("sender_type") or "") in {"agent", "assistant", "ai"}
        ][-4:],
        question_node_id=fallback_id,
        question_text="",
        asked_question_node_ids=context.cart.get("asked_question_node_ids") or [],
        max_attempts=_question_repetition_max_attempts(contract),
        field_pending=bool(fallback_id),
        terminal_intent=fallback_terminal_intent,
        previous_terminal_intent=str(
            ((context.cart.get("terminal_handoff") or {}).get("intent") or "")
        ) or None,
    )
    fallback_proof["repetition_audit"] = fallback_repetition
    fallback_proof["repetition_action"] = (
        "allowed" if fallback_repetition["passed"] else "observed_only"
    )
    fallback_route = (
        ConversationRoute.HUMAN if fallback_terminal_intent else ConversationRoute.SDR
    )
    return (
        ConversationDecision(classifier="graph_proof_checker_v3",
                             intent=fallback_terminal_intent or (
                                 "awaiting_confirmation"
                                 if fallback_confirmation_pending
                                 else "post_qualification_support"
                                 if fallback_post_support
                                 else "model_repair_exhausted_handoff"
                             ),
                             route=fallback_route, confidence=0,
                             lead_stage=str(context.cart.get("_lead_stage") or "novo"),
                             handoff_reason=(
                                 "graph_context_proof_failed"
                                 if context_failure_handoff
                                 else "graph_terminal_qualification"
                                 if fallback_terminal_intent else None
                             ),
                             evidence_node_ids=[fallback_id] if fallback_id else []),
        AgentResponse(reply_text=fallback or None, role=fallback_route,
                      evidence_node_ids=[fallback_id] if fallback_id else [], cart_state=fallback_state,
                      handoff_required=bool(fallback_terminal_intent), proposal=proposal, proof=fallback_proof),
    )

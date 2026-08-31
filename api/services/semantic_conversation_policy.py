"""Bridge from a validated SemanticInterpretation to runtime decisions.

The runtime used to answer three questions with phrase lists:

  * did the customer confirm what we asked?      -> `_EXPLICIT_CONFIRMATIONS`
  * which branch did they pick?                  -> alias/title literal matcher
  * is this message a question or a field value? -> interrogative prefixes

A live production audit (2026-08-21) showed all three failing on ordinary
WhatsApp phrasing while the model had already read the message correctly. This
module answers the same three questions from the model's validated
interpretation instead, and keeps every policy consequence -- routing, required
fields, next question, handoff -- with the deterministic caller.

Nothing here inspects raw customer text. By the time an interpretation reaches
this module `semantic_interpretation_validator` has already proved every span
against the literal message and every id against the published graph.
"""
from __future__ import annotations

from typing import Any

from schemas.conversation import (
    ConfirmationState,
    ConversationContext,
    ConversationProposal,
    CustomerQuestionKind,
    InteractionKind,
    SemanticInterpretation,
)

# How a customer act maps onto the interaction vocabulary the proof checker and
# journey policy already speak. Anything unlisted stays UNCLEAR, which is the
# conservative reading -- it never opens a journey on its own.
_INTENT_TO_INTERACTION = {
    "commercial_question": InteractionKind.POST_COMPLETION_QUESTION,
    "product_change": InteractionKind.NEW_DEMAND,
    "audience_change": InteractionKind.NEW_DEMAND,
    "resume": InteractionKind.CONTINUE_CURRENT,
    "answer_pending_field": InteractionKind.CONTINUE_CURRENT,
    "confirmation": InteractionKind.CONTINUE_CURRENT,
    "correction": InteractionKind.CONTINUE_CURRENT,
    "spontaneous_info": InteractionKind.CONTINUE_CURRENT,
    "small_talk": InteractionKind.COURTESY_CLOSE,
}


def adapt_model_envelope(raw: Any) -> Any:
    """Adapt the compact v3 model envelope to the internal v2 structure.

    The public model contract has one customer-facing string.  The richer
    ``SemanticInterpretation`` remains an internal compatibility shape while
    the installed v2 and v3 workflows overlap during blue/green.
    """
    if not isinstance(raw, dict) or str(raw.get("envelope_version") or "") != "3":
        return raw
    branch_selections = list(raw.get("branch_selections") or [])
    state_relation = (
        "new_demand"
        if any(
            str(item.get("action") or "none") in {"select", "switch", "add"}
            for item in branch_selections
            if isinstance(item, dict)
        )
        else "continue"
    )
    asked_field_key = str(raw.get("asked_field_key") or "").strip() or None
    reply = raw.get("reply") if isinstance(raw.get("reply"), str) else ""
    return {
        "intents": [],
        "state_relation": state_relation,
        "answers_field_key": None,
        "confirmation": raw.get("confirmation") or {
            "state": "none",
            "target_ref": None,
            "evidence_span": "",
            "correction_field_key": None,
            "correction_value": None,
        },
        "branch_selections": branch_selections,
        "facts": list(raw.get("facts") or []),
        "invalidated_facts": [],
        "entities": [],
        "questions": list(raw.get("customer_questions") or []),
        "claims": list(raw.get("claims") or []),
        "recommended_next_action": (
            "handoff" if raw.get("handoff_requested") is True
            else "ask_field" if asked_field_key
            else "answer_question"
        ),
        "cited_node_ids": list(raw.get("cited_node_ids") or []),
        "cited_chunk_ids": list(raw.get("cited_chunk_ids") or []),
        "response": {
            "answer": reply,
            "question": None,
            "question_field_key": asked_field_key,
        },
        "next_question_field_key": asked_field_key,
        "next_question_node_id": None,
        "reply": reply,
        "handoff_requested": raw.get("handoff_requested") is True,
    }


def interpretation_segments(
    interpretation: SemanticInterpretation,
) -> tuple[str, str, str | None, str | None]:
    """Return the public reply, a legacy question segment and audit metadata.

    The flat fields are accepted only for rolling compatibility. The canonical
    workflow emits the complete public message in ``response.answer`` and
    never asks the model for graph node ids. ``response.question`` is only a
    fallback for an older installed workflow whose answer is empty; it is
    never appended to an answer that may already contain the same question.
    """
    answer = str(interpretation.response.answer or "")
    legacy_question = str(interpretation.response.question or "")
    field_key = str(
        interpretation.response.question_field_key
        or interpretation.next_question_field_key
        or ""
    ).strip() or None
    node_id = str(interpretation.next_question_node_id or "").strip() or None
    if not answer.strip() and legacy_question.strip():
        answer = legacy_question
        legacy_question = ""
    if not answer.strip():
        answer = str(interpretation.reply or "")
    return answer, legacy_question, field_key, node_id


def interpretation_reply(interpretation: SemanticInterpretation) -> str:
    """Return one model-authored public message; never compose question copy."""
    answer, _, _, _ = interpretation_segments(interpretation)
    return answer


def interpretation_to_proposal(
    interpretation: SemanticInterpretation,
    *,
    service_operations: list[dict[str, Any]] | None = None,
) -> ConversationProposal:
    """Express a validated interpretation in the proposal shape `_decide` speaks.

    The runtime's decision machinery -- multi-branch service operations, fact
    reconciliation, proof checking, commit -- is built around
    ``ConversationProposal`` and well covered by tests. Rather than grow a
    second decision path beside it, the semantic contract becomes its source:
    the model's reading is translated here, once, after validation.

    Only fields the interpretation actually carries are set. Branch routing is
    deliberately NOT derived here -- the backend re-resolves it against the
    graph and overwrites it in ``_apply_authoritative_branch_resolution``.
    """
    intent_kinds = [str(intent.kind.value) for intent in interpretation.intents]
    interaction = next(
        (
            _INTENT_TO_INTERACTION[kind]
            for kind in intent_kinds
            if kind in _INTENT_TO_INTERACTION
        ),
        InteractionKind.UNCLEAR,
    )
    evidence = next(
        (intent.evidence_span for intent in interpretation.intents), ""
    )
    answer, _, question_field_key, legacy_question_node_id = (
        interpretation_segments(interpretation)
    )
    return ConversationProposal(
        interaction_observation={
            "kind": interaction,
            "evidence_span": evidence,
            # The contract carries no numeric confidence by design; the proof
            # checker only ever compares this against zero, so a proved
            # observation reports full certainty and the evidence span is what
            # actually explains it.
            "confidence": 1.0 if interpretation.intents else 0.0,
        },
        service_operations=service_operations or [],
        extracted_facts=[fact.model_dump() for fact in interpretation.facts],
        claims=[claim.model_dump() for claim in interpretation.claims],
        cited_node_ids=list(interpretation.cited_node_ids),
        cited_chunk_ids=list(interpretation.cited_chunk_ids),
        answer_text=answer,
        # The canonical envelope is deliberately monolithic: proof inspects
        # the public message itself and may request one model repair, but the
        # backend never guesses where prose ends and a question begins.
        question_text="",
        next_question_field_key=question_field_key,
        next_question_node_id=legacy_question_node_id,
        reply=answer,
        qualification_complete=(
            interpretation.recommended_next_action.value in {"handoff", "close"}
        ),
        handoff_requested=interpretation.handoff_requested,
    )

# Questions whose answer is a published commercial commitment. The runtime may
# never answer one from the model's own words -- only from an approved node, or
# by deferring to the team. The kinds come from the contract enum, not from any
# per-persona list.
COMMERCIAL_QUESTION_KINDS = frozenset({
    CustomerQuestionKind.AVAILABILITY,
    CustomerQuestionKind.PRICE,
    CustomerQuestionKind.STOCK,
    CustomerQuestionKind.SCHEDULE,
    CustomerQuestionKind.DEADLINE,
    CustomerQuestionKind.POLICY,
})


def confirmation_state(
    interpretation: SemanticInterpretation, context: ConversationContext
) -> ConfirmationState:
    """What the customer did with the confirmation we actually had pending.

    Returns NONE whenever nothing was pending, so a positive-sounding message
    can never confirm something the turn never asked about. The validator has
    already checked ``target_ref`` against ``pending_confirmation_ref``; this
    re-check keeps the function honest if it is ever called with a raw
    interpretation.
    """
    pending_ref = str(context.pending_confirmation_ref or "")
    confirmation = interpretation.confirmation
    if not pending_ref or str(confirmation.target_ref or "") != pending_ref:
        return ConfirmationState.NONE
    return confirmation.state


def confirms_pending(
    interpretation: SemanticInterpretation, context: ConversationContext
) -> bool:
    """A full or partial yes. Partial still confirms -- it also corrects."""
    return confirmation_state(interpretation, context) in {
        ConfirmationState.AFFIRM,
        ConfirmationState.PARTIAL,
    }


def rejects_pending(
    interpretation: SemanticInterpretation, context: ConversationContext
) -> bool:
    return confirmation_state(interpretation, context) is ConfirmationState.REJECT


def is_ambiguous_confirmation(
    interpretation: SemanticInterpretation, context: ConversationContext
) -> bool:
    """"acho que sim" -- ask once, do not guess and do not repeat the question."""
    return confirmation_state(interpretation, context) is ConfirmationState.AMBIGUOUS


def pending_correction(
    interpretation: SemanticInterpretation, context: ConversationContext
) -> tuple[str, Any] | None:
    """The correction rider on a partial yes: "yes, but change X to Y"."""
    if confirmation_state(interpretation, context) is not ConfirmationState.PARTIAL:
        return None
    confirmation = interpretation.confirmation
    if not confirmation.correction_field_key:
        return None
    return str(confirmation.correction_field_key), confirmation.correction_value


def semantic_service_resolution(
    interpretation: SemanticInterpretation,
    context: ConversationContext,
    document: dict[str, Any],
) -> dict[str, Any] | None:
    """Model-read branch selection, shaped like the literal resolver's output.

    Returned only when the model actually selected a branch. The caller uses it
    as the resolution for the turn when the literal matcher found nothing --
    which is precisely the case that used to loop the same question forever.
    ``None`` means "the model did not select a branch", never "the wording was
    unfamiliar".
    """
    selections = [
        item for item in interpretation.branch_selections
        if item.branch_anchor_node_id and item.action.value != "none"
    ]
    if not selections:
        return None

    before = list(dict.fromkeys([
        *([context.active_branch_node_id] if context.active_branch_node_id else []),
        *context.active_branch_node_ids,
    ]))
    coordinates = document.get("coordinates") or {}
    node_by_id = document.get("node_by_id") or {}

    after = list(before)
    operations: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    consumed: list[dict[str, Any]] = []
    focus: str | None = None

    def operation(kind: str, target: str, evidence: str) -> dict[str, Any]:
        return {
            "action": kind,
            "branch_anchor_node_id": target,
            "branch_path_checksum": str(
                (coordinates.get(target) or {}).get("path_checksum") or ""
            ),
            "evidence_span": evidence,
            "evidence_type": "confirmed_candidate",
            "resolution_method": "semantic_interpretation",
        }

    # Applied in the order the customer said them, so a switch followed by an
    # add composes the way it reads rather than by rule precedence.
    for selection in selections:
        anchor = str(selection.branch_anchor_node_id)
        action = selection.action.value
        evidence = selection.evidence_span
        node = node_by_id.get(anchor) or {}
        matches.append({
            "branch_anchor_node_id": anchor,
            "branch_path_checksum": str(
                (coordinates.get(anchor) or {}).get("path_checksum") or ""
            ),
            "title": node.get("title"),
            "slug": node.get("slug"),
            "span": evidence,
        })
        consumed.append({
            "text": evidence,
            "branch_anchor_node_id": anchor,
            "evidence_type": "semantic_interpretation",
        })
        if action == "drop":
            if anchor in after:
                after.remove(anchor)
                operations.append(operation("drop", anchor, evidence))
            continue
        if action == "switch":
            for previous in list(after):
                if previous != anchor:
                    after.remove(previous)
                    operations.append(operation("drop", previous, evidence))
        if anchor in after:
            operations.append(operation("keep", anchor, evidence))
        else:
            after.append(anchor)
            operations.append(operation("add", anchor, evidence))
        focus = anchor

    return {
        "status": "resolved",
        "resolution_method": "semantic_interpretation",
        "matches": matches,
        "ambiguities": [],
        "consumed_spans": consumed,
        "operations": operations,
        "previous_active_branch_node_ids": before,
        "next_active_branch_node_ids": after,
        # The last branch the customer opened leads the reply; if the turn only
        # closed branches, whatever is still open leads it.
        "focused_branch_node_id": focus or (after[-1] if after else None),
        "direct_answer_to_service_question": True,
        "explicit_service_intent": True,
    }


def commercial_questions(
    interpretation: SemanticInterpretation,
) -> list[dict[str, Any]]:
    """Questions the turn owes an answer to and may not answer by inventing.

    Kept separate from facts so an availability question is never absorbed as
    the raw value of whatever field happened to be pending -- the third
    production defect the audit found.
    """
    return [
        {
            "kind": question.kind.value,
            "topic": question.topic,
            "entity_node_ids": list(question.entity_node_ids),
            "evidence_span": question.evidence_span,
            "requires_published_evidence": question.kind in COMMERCIAL_QUESTION_KINDS,
        }
        for question in interpretation.questions
    ]


def unanswerable_commercial_questions(
    interpretation: SemanticInterpretation,
) -> list[dict[str, Any]]:
    """Commercial questions with no published node behind them.

    The turn must acknowledge these and defer to the team. It must never
    answer them, and it must never silently drop them.
    """
    supported = {
        node_id
        for claim in interpretation.claims
        for node_id in claim.evidence_node_ids
    }
    return [
        question for question in commercial_questions(interpretation)
        if question["requires_published_evidence"]
        and not (set(question["entity_node_ids"]) & supported)
    ]

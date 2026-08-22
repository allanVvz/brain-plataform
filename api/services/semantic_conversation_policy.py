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
    CustomerQuestionKind,
    SemanticInterpretation,
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
    selection = interpretation.branch_selection
    anchor = str(selection.branch_anchor_node_id or "")
    action = selection.action.value
    if not anchor or action == "none":
        return None

    before = list(dict.fromkeys([
        *([context.active_branch_node_id] if context.active_branch_node_id else []),
        *context.active_branch_node_ids,
    ]))
    checksum = str(
        ((document.get("coordinates") or {}).get(anchor) or {}).get("path_checksum") or ""
    )
    evidence = selection.evidence_span

    after = list(before)
    operations: list[dict[str, Any]] = []

    def operation(kind: str, target: str) -> dict[str, Any]:
        return {
            "action": kind,
            "branch_anchor_node_id": target,
            "branch_path_checksum": str(
                ((document.get("coordinates") or {}).get(target) or {})
                .get("path_checksum") or ""
            ),
            "evidence_span": evidence,
            "evidence_type": "confirmed_candidate",
            "resolution_method": "semantic_interpretation",
        }

    if action == "drop":
        if anchor in after:
            after.remove(anchor)
            operations.append(operation("drop", anchor))
    else:
        if action == "switch":
            for previous in list(after):
                if previous != anchor:
                    after.remove(previous)
                    operations.append(operation("drop", previous))
        if anchor in after:
            operations.append(operation("keep", anchor))
        else:
            after.append(anchor)
            operations.append(operation("add", anchor))

    node = (document.get("node_by_id") or {}).get(anchor) or {}
    return {
        "status": "resolved",
        "resolution_method": "semantic_interpretation",
        "matches": [{
            "branch_anchor_node_id": anchor,
            "branch_path_checksum": checksum,
            "title": node.get("title"),
            "slug": node.get("slug"),
            "span": evidence,
        }],
        "ambiguities": [],
        "consumed_spans": [{
            "text": evidence,
            "branch_anchor_node_id": anchor,
            "evidence_type": "semantic_interpretation",
        }],
        "operations": operations,
        "previous_active_branch_node_ids": before,
        "next_active_branch_node_ids": after,
        "focused_branch_node_id": anchor if action != "drop" else (after[-1] if after else None),
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

"""Deterministic safety validation of one model-supplied SemanticInterpretation.

This module is the whole deterministic half of the semantic-first runtime. It
deliberately does NOT interpret language: there is no phrase list, no alias
table, no regex over customer text, and nothing here knows what any persona
sells. Interpretation is the model's job. This module only proves that what
the model claimed is supported by the literal message and permitted by the
published graph, and it strips whatever fails.

Rejecting an element never rewrites it into a different meaning -- an element
either survives with the meaning the model gave it, or it is dropped and the
caller asks a short clarifying question. That is what keeps a valid semantic
reading (``"uso proprio mesmo"`` -> the retail anchor) from being thrown away
just because it was phrased in a way no fixed list anticipated.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from schemas.conversation import (
    ConfirmationState,
    ConversationContext,
    SemanticInterpretation,
)


def _fold(value: Any) -> str:
    """Case/accent-fold to a comparable token string.

    Punctuation and diacritics are dropped so an evidence span still matches
    when the customer wrote "tá" and the model echoed "ta", or when the span
    ends before a comma.
    """
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def _is_grounded(span: Any, folded_message: str) -> bool:
    folded_span = _fold(span)
    return bool(folded_span) and folded_span in folded_message


@dataclass
class ValidationResult:
    """What survived validation, plus why anything did not.

    ``errors`` are hard contract breaches (the interpretation as a whole
    cannot be trusted). ``dropped`` are individual elements removed for lack
    of grounding or graph backing -- the turn continues without them.
    """

    valid: bool
    interpretation: SemanticInterpretation
    errors: list[str] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)

    def as_proof(self) -> dict[str, Any]:
        return {
            "semantic_validation": {
                "valid": self.valid,
                "errors": list(self.errors),
                "dropped": list(self.dropped),
                "policy": "semantic_interpretation_validator_v1",
            }
        }


def _contract_field_specs(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(spec.get("key")): spec
        for spec in (contract.get("fields") or [])
        if spec.get("key")
    }


def _allowed_values(spec: dict[str, Any]) -> set[str] | None:
    """Folded set of values a field accepts, or None when it is free text.

    Values and their aliases come from the graph's own field validation
    block, never from this module.
    """
    validation = spec.get("validation")
    if not isinstance(validation, dict) or validation.get("mode") != "enum":
        return None
    allowed: set[str] = set()
    for option in validation.get("values") or []:
        if isinstance(option, dict):
            allowed.add(_fold(option.get("value")))
            allowed.update(_fold(alias) for alias in option.get("aliases") or [])
        else:
            allowed.add(_fold(option))
    return {value for value in allowed if value} or None


def validate_interpretation(
    interpretation: SemanticInterpretation,
    *,
    message: str,
    document: dict[str, Any],
    contract: dict[str, Any],
    context: ConversationContext,
) -> ValidationResult:
    """Prove one interpretation against the message and the published graph."""
    folded_message = _fold(message)
    node_by_id = document.get("node_by_id") or {}
    branch_anchors = {str(anchor) for anchor in document.get("branch_anchors") or []}
    field_specs = _contract_field_specs(contract)

    errors: list[str] = []
    dropped: list[dict[str, Any]] = []
    data = interpretation.model_dump()

    def drop(kind: str, reason: str, detail: Any) -> None:
        dropped.append({"kind": kind, "reason": reason, "detail": detail})

    # -- intents ---------------------------------------------------------
    surviving_intents: list[dict[str, Any]] = []
    for intent in data.get("intents") or []:
        if _is_grounded(intent.get("evidence_span"), folded_message):
            surviving_intents.append(intent)
        else:
            drop("intent", "evidence_not_in_message", intent)
    data["intents"] = surviving_intents

    intent_kinds = {str(intent.get("kind")) for intent in data["intents"]}
    if {"confirmation", "rejection"} <= intent_kinds:
        errors.append("contradiction_confirmation_and_rejection")

    # -- confirmation ----------------------------------------------------
    confirmation = dict(data.get("confirmation") or {})
    state = str(confirmation.get("state") or ConfirmationState.NONE.value)
    if state != ConfirmationState.NONE.value:
        pending_ref = str(context.pending_confirmation_ref or "")
        if not pending_ref:
            # "sim" with nothing pending must not confirm something arbitrary.
            drop("confirmation", "no_pending_confirmation", confirmation)
            confirmation = {"state": ConfirmationState.NONE.value, "target_ref": None,
                            "evidence_span": "", "correction_field_key": None,
                            "correction_value": None}
        elif str(confirmation.get("target_ref") or "") != pending_ref:
            drop("confirmation", "target_ref_mismatch", confirmation)
            confirmation = {"state": ConfirmationState.NONE.value, "target_ref": None,
                            "evidence_span": "", "correction_field_key": None,
                            "correction_value": None}
        elif not _is_grounded(confirmation.get("evidence_span"), folded_message):
            drop("confirmation", "evidence_not_in_message", confirmation)
            confirmation = {"state": ConfirmationState.NONE.value, "target_ref": None,
                            "evidence_span": "", "correction_field_key": None,
                            "correction_value": None}
    correction_key = confirmation.get("correction_field_key")
    if correction_key and str(correction_key) not in field_specs:
        drop("confirmation_correction", "unknown_field_key", correction_key)
        confirmation["correction_field_key"] = None
        confirmation["correction_value"] = None
    data["confirmation"] = confirmation

    # -- branch selection ------------------------------------------------
    selection = dict(data.get("branch_selection") or {})
    if str(selection.get("action") or "none") != "none":
        anchor = str(selection.get("branch_anchor_node_id") or "")
        if anchor not in branch_anchors:
            drop("branch_selection", "unknown_branch_anchor", selection)
            selection = {"action": "none", "branch_anchor_node_id": None,
                         "evidence_span": ""}
        elif not _is_grounded(selection.get("evidence_span"), folded_message):
            drop("branch_selection", "evidence_not_in_message", selection)
            selection = {"action": "none", "branch_anchor_node_id": None,
                         "evidence_span": ""}
    data["branch_selection"] = selection

    # -- answered field --------------------------------------------------
    answers_key = data.get("answers_field_key")
    if answers_key and str(answers_key) not in field_specs:
        drop("answers_field_key", "unknown_field_key", answers_key)
        data["answers_field_key"] = None

    # -- facts -----------------------------------------------------------
    surviving_facts: list[dict[str, Any]] = []
    for fact in data.get("facts") or []:
        key = str(fact.get("field_key") or "")
        spec = field_specs.get(key)
        if spec is None:
            drop("fact", "unknown_field_key", fact)
            continue
        if str(fact.get("owner_node_id") or "") not in node_by_id:
            drop("fact", "unknown_owner_node", fact)
            continue
        if not _is_grounded(fact.get("evidence_span"), folded_message):
            drop("fact", "evidence_not_in_message", fact)
            continue
        allowed = _allowed_values(spec)
        if allowed is not None and _fold(fact.get("value")) not in allowed:
            drop("fact", "value_not_allowed_by_graph", fact)
            continue
        surviving_facts.append(fact)
    data["facts"] = surviving_facts

    # -- invalidations ---------------------------------------------------
    surviving_invalidations: list[dict[str, Any]] = []
    for item in data.get("invalidated_facts") or []:
        if str(item.get("field_key") or "") not in field_specs:
            drop("invalidated_fact", "unknown_field_key", item)
        elif not _is_grounded(item.get("evidence_span"), folded_message):
            drop("invalidated_fact", "evidence_not_in_message", item)
        else:
            surviving_invalidations.append(item)
    data["invalidated_facts"] = surviving_invalidations

    # -- entities --------------------------------------------------------
    surviving_entities: list[dict[str, Any]] = []
    for entity in data.get("entities") or []:
        node_id = entity.get("node_id")
        if node_id and str(node_id) not in node_by_id:
            drop("entity", "unknown_node", entity)
            continue
        if not _is_grounded(entity.get("evidence_span"), folded_message):
            drop("entity", "evidence_not_in_message", entity)
            continue
        surviving_entities.append(entity)
    data["entities"] = surviving_entities

    # -- customer questions ----------------------------------------------
    surviving_questions: list[dict[str, Any]] = []
    for question in data.get("questions") or []:
        if not _is_grounded(question.get("evidence_span"), folded_message):
            drop("question", "evidence_not_in_message", question)
            continue
        question = {
            **question,
            "entity_node_ids": [
                node_id for node_id in question.get("entity_node_ids") or []
                if str(node_id) in node_by_id
            ],
        }
        surviving_questions.append(question)
    data["questions"] = surviving_questions

    # -- commercial claims -----------------------------------------------
    # A claim about price/stock/schedule/deadline/policy only survives with a
    # published node backing it. This is what stops invention; the reply-side
    # proof checker still runs afterwards.
    surviving_claims: list[dict[str, Any]] = []
    for claim in data.get("claims") or []:
        evidence = [
            node_id for node_id in claim.get("evidence_node_ids") or []
            if str(node_id) in node_by_id
        ]
        if not evidence:
            drop("claim", "no_published_evidence", claim)
            continue
        surviving_claims.append({**claim, "evidence_node_ids": evidence})
    data["claims"] = surviving_claims

    # -- citations -------------------------------------------------------
    # Persona isolation: a node id from another persona's graph is simply not
    # in this document, so it cannot be cited.
    data["cited_node_ids"] = [
        node_id for node_id in data.get("cited_node_ids") or []
        if str(node_id) in node_by_id
    ]

    # -- handoff ---------------------------------------------------------
    if data.get("handoff_requested") and not (
        contract.get("handoff_rule_node_ids") or contract.get("confirmation_required")
    ):
        drop("handoff", "handoff_not_permitted_by_graph", True)
        data["handoff_requested"] = False

    return ValidationResult(
        valid=not errors,
        interpretation=SemanticInterpretation.model_validate(data),
        errors=errors,
        dropped=dropped,
    )


def needs_clarification(result: ValidationResult) -> bool:
    """True when the turn has nothing it can safely act on.

    Used by the caller to ask ONE short clarifying question instead of
    mechanically repeating the previous question -- the failure mode the
    literal matcher produced.
    """
    interpretation = result.interpretation
    return not (
        interpretation.facts
        or interpretation.questions
        or interpretation.branch_selection.action.value != "none"
        or interpretation.confirmation.state.value != "none"
        or interpretation.invalidated_facts
    )

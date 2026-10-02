"""Reconcile model question metadata without authorizing or editing public text."""
from __future__ import annotations

from typing import Any


def _fold(value: str) -> str:
    return " ".join(value.casefold().split()).strip(" ?!.¿")


def reconcile_question_metadata(
    *, reply: str, question_kind: str | None, asked_field_key: str | None,
    eligible_fields: list[dict[str, Any]], contract: dict[str, Any],
    handoff_required: bool = False,
) -> dict[str, Any]:
    """Model meaning wins; literal examples only recover a missing pointer.

    Question punctuation, wording similarity and field eligibility never decide
    delivery. An uncertain pointer is detached so it cannot consume a field's
    ask-once attempt. Facts and public text remain untouched.
    """
    original = {"question_kind": question_kind, "asked_field_key": asked_field_key}
    kind, key = question_kind, asked_field_key or None
    warnings: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for field in eligible_fields:
        if field.get("key"):
            grouped.setdefault(str(field["key"]), []).append(field)
    eligible = {key: fields[0] for key, fields in grouped.items()}
    ambiguous = {key for key, fields in grouped.items() if len({
        (f.get("owner_node_id"), f.get("question_node_id")) for f in fields
    }) > 1}
    if kind not in {None, "none", "qualification", "consultative", "confirmation"}:
        kind = None
        warnings.append("reply_metadata_invalid:question_kind")
    if key and key not in eligible:
        warnings.append("question_field_not_eligible")
        key = None
    if key in ambiguous:
        warnings.append("question_field_owner_ambiguous")
        key = None
    if kind == "confirmation" and key:
        key = None
        warnings.append("confirmation_field_pointer_detached")
    if handoff_required:
        key = None
        if kind == "qualification":
            kind = "none"
            warnings.append("qualification_metadata_on_handoff")
    elif key:
        # The model has named a published eligible field. Do not reinterpret
        # it with lexical heuristics or require a question mark.
        if kind != "qualification":
            warnings.append("question_kind_corrected_from_eligible_field")
        kind = "qualification"
    elif not asked_field_key and kind in {None, "none", "qualification", "consultative"}:
        # Exact authored examples are a compatibility aid for missing metadata,
        # never a classifier that overrides the model or a delivery guard.
        sentences = {_fold(part) for part in reply.split("?")[:-1]}
        matches = set()
        for field_key, field in eligible.items():
            if field_key in ambiguous:
                continue
            question = (contract.get("questions") or {}).get(str(field.get("question_node_id") or "")) or {}
            for example in [question.get("text"), *(question.get("paraphrases") or [])]:
                if isinstance(example, str) and _fold(example) and _fold(example) in sentences:
                    matches.add(field_key)
        if len(matches) == 1:
            key, kind = next(iter(matches)), "qualification"
        elif len(matches) > 1:
            warnings.append("question_metadata_ambiguous")
    if not key and kind == "qualification":
        kind = "consultative"
        warnings.append("qualification_pointer_detached")
    if kind is None or (kind == "none" and "?" in reply):
        kind = "consultative" if "?" in reply else "none"
    normalized = {"question_kind": kind, "asked_field_key": key}
    corrections = [name for name in normalized if normalized[name] != original[name]]
    if corrections:
        warnings.append("reply_question_metadata_normalized")
    return {
        **normalized,
        "warnings": list(dict.fromkeys(warnings)),
        "audit": {"original": original, "normalized": normalized,
                  "corrections": corrections, "status": "corrected" if corrections else "preserved",
                  "candidate_reply": reply},
    }

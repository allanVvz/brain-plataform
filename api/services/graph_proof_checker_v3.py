"""Generic proof checker for structured GraphRAG model proposals."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError:  # local bootstrap before requirements are rebuilt
    Draft202012Validator = None  # type: ignore[assignment]


VALID_STATUSES = {"known", "unknown", "declined", "needs_confirmation", "invalid"}
_CORRECTION_MARKER = re.compile(
    r"\b(corrig|corre[cç][aã]o|na verdade|retific|correction|actually|i meant)\w*\b",
    re.IGNORECASE,
)
_FINAL_CONFIRMATION = re.compile(
    r"\b(confirmad[oa]|reservad[oa]|agendad[oa]|fechad[oa]|booked|confirmed)\b",
    re.IGNORECASE,
)


def _literal_span(message: str, span: Any) -> bool:
    value = str(span or "")
    return bool(value and value in (message or ""))


def _condition_matches(condition: Any, facts: dict[str, Any]) -> bool:
    if condition in (None, {}, []):
        return True
    if "all" in condition:
        return all(_condition_matches(item, facts) for item in condition["all"])
    if "any" in condition:
        return any(_condition_matches(item, facts) for item in condition["any"])
    fact = facts.get(str(condition.get("field") or "")) or {}
    exists = fact.get("status") in {"known", "unknown", "declined"}
    actual = fact.get("value")
    expected = condition.get("value")
    operator = condition.get("operator") or "equals"
    if operator == "exists":
        return exists
    if operator == "not_exists":
        return not exists
    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "in":
        return actual in (expected or [])
    if operator == "not_in":
        return actual not in (expected or [])
    try:
        return {
            "greater_than": actual > expected,
            "greater_than_or_equal": actual >= expected,
            "less_than": actual < expected,
            "less_than_or_equal": actual <= expected,
        }[operator]
    except (KeyError, TypeError):
        return False


def field_resolved(field: dict[str, Any], fact: dict[str, Any] | None) -> bool:
    if not fact:
        return False
    status = str(fact.get("status") or "")
    if status not in set(field.get("accepted_statuses") or ["known"]):
        return False
    return status != "known" or fact.get("value") not in (None, "")


def fact_compatible(field: dict[str, Any], fact: dict[str, Any] | None) -> bool:
    """Check whether a stored fact remains valid under a new publication."""
    if not fact or fact.get("owner_node_id") != field.get("owner_node_id"):
        return False
    if not field_resolved(field, fact):
        return False
    if fact.get("status") == "known":
        return _schema_error(field.get("value_schema") or {}, fact.get("value")) is None
    return fact.get("value") is None


def pending_fields(contract: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        field for field in contract.get("fields") or []
        if field.get("required", True)
        and _condition_matches(field.get("condition"), facts)
        and not field_resolved(field, facts.get(field["key"]))
    ]


def _claim_policy(contract: dict[str, Any], claim_type: str) -> list[dict[str, Any]]:
    return [
        policy for policy in contract.get("claims") or []
        if str(policy.get("claim_type") or policy.get("type") or "other") == claim_type
    ]


def _handoff_rule_matches(
    rule: dict[str, Any], *, facts: dict[str, Any], qualification_complete: bool
) -> bool:
    condition = rule.get("condition")
    if condition in (None, {}, []):
        return True
    if condition == "qualification_complete":
        return qualification_complete
    if condition == "qualification_incomplete":
        return not qualification_complete
    return isinstance(condition, dict) and _condition_matches(condition, facts)


def _schema_error(schema: dict[str, Any], value: Any) -> str | None:
    """Use Draft 2020-12 in runtime; keep local bootstrap import-safe."""
    if Draft202012Validator is not None:
        errors = list(Draft202012Validator(schema).iter_errors(value))
        return errors[0].message if errors else None
    for candidate in schema.get("anyOf") or []:
        if _schema_error(candidate, value) is None:
            return None
    if schema.get("anyOf"):
        return "value does not match anyOf"
    expected = schema.get("type")
    accepted = expected if isinstance(expected, list) else [expected] if expected else []
    type_map = {
        "string": str, "number": (int, float), "integer": int,
        "boolean": bool, "object": dict, "array": list, "null": type(None),
    }
    if accepted and not any(isinstance(value, type_map[kind]) and not (
        kind in {"number", "integer"} and isinstance(value, bool)
    ) for kind in accepted if kind in type_map):
        return f"value is not of type {accepted}"
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength") or 0):
            return "string is too short"
        if schema.get("pattern") and not re.search(str(schema["pattern"]), value):
            return "string does not match pattern"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return "number is below minimum"
        if "maximum" in schema and value > schema["maximum"]:
            return "number is above maximum"
    if "enum" in schema and value not in schema["enum"]:
        return "value is not in enum"
    return None


def check(
    *,
    publication: dict[str, Any],
    contract: dict[str, Any],
    ledger: dict[str, Any],
    proposal: dict[str, Any],
    message: str,
    source_message_id: str,
    package_node_ids: set[str],
    package_chunk_ids: set[str],
    active_branch_node_id: str | None,
    branch_selection_allowed: bool,
    branch_switch_allowed: bool,
    package_chunk_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    repair: list[dict[str, Any]] = []
    document = publication.get("document_json") or {}
    branch = str(proposal.get("branch_anchor_node_id") or "")
    action = str(proposal.get("branch_action") or "keep")
    anchors = set(document.get("branch_anchors") or [])
    if publication.get("status") != "active":
        errors.append("publication_not_active")
    if publication.get("checksum") != ledger.get("graph_checksum"):
        errors.append("publication_checksum_mismatch")
    if branch not in anchors:
        errors.append("branch_not_published")
    if proposal.get("branch_path_checksum") != contract.get("branch_path_checksum"):
        errors.append("branch_path_checksum_mismatch")
    branch_span = proposal.get("branch_evidence_span")
    if action == "keep":
        if active_branch_node_id and branch != active_branch_node_id:
            errors.append("keep_changed_branch")
    elif action == "select":
        if not branch_selection_allowed or active_branch_node_id:
            errors.append("branch_select_not_authorized")
        if not _literal_span(message, branch_span):
            errors.append("branch_evidence_not_literal")
    elif action == "switch":
        if not branch_switch_allowed or not active_branch_node_id or branch == active_branch_node_id:
            errors.append("branch_switch_not_authorized")
        if not _literal_span(message, branch_span):
            errors.append("branch_evidence_not_literal")
    else:
        errors.append("invalid_branch_action")

    closure = set(contract.get("closure_node_ids") or [])
    chunk_sources = package_chunk_sources or {}
    for node_id in proposal.get("cited_node_ids") or []:
        if node_id not in closure:
            errors.append(f"cited_node_outside_branch:{node_id}")
        elif node_id not in package_node_ids:
            errors.append(f"cited_node_outside_package:{node_id}")
            repair.append({"kind": "node", "id": node_id})
    for chunk_id in proposal.get("cited_chunk_ids") or []:
        if chunk_id not in package_chunk_ids:
            errors.append(f"cited_chunk_outside_package:{chunk_id}")
            repair.append({"kind": "chunk", "id": chunk_id})
        elif chunk_sources.get(chunk_id) and chunk_sources[chunk_id] not in closure:
            errors.append(f"cited_chunk_outside_branch:{chunk_id}")

    next_ledger = deepcopy(ledger)
    facts = next_ledger.setdefault("facts", {})
    fields = {field["key"]: field for field in contract.get("fields") or []}
    accepted_facts: list[dict[str, Any]] = []
    proposal_facts = proposal.get("extracted_facts") or []
    duplicate_keys = {
        str(fact.get("field_key") or "") for fact in proposal_facts
        if sum(
            str(candidate.get("field_key") or "") == str(fact.get("field_key") or "")
            for candidate in proposal_facts
        ) > 1
    }
    errors.extend(f"duplicate_extracted_fact:{key}" for key in sorted(duplicate_keys) if key)
    field_order = {key: index for index, key in enumerate(fields)}
    for fact in sorted(
        proposal_facts,
        key=lambda value: field_order.get(str(value.get("field_key") or ""), len(field_order)),
    ):
        key = str(fact.get("field_key") or "")
        if key in duplicate_keys:
            continue
        fact_error_count = len(errors)
        field = fields.get(key)
        if not field:
            errors.append(f"undeclared_field:{key}")
            continue
        if fact.get("owner_node_id") != field.get("owner_node_id"):
            errors.append(f"field_owner_mismatch:{key}")
            continue
        if fact.get("source_message_id") != source_message_id:
            errors.append(f"fact_source_message_mismatch:{key}")
        if not _literal_span(message, fact.get("evidence_span")):
            errors.append(f"fact_evidence_not_literal:{key}")
        status = str(fact.get("status") or "")
        if status not in VALID_STATUSES or status not in set(field.get("accepted_statuses") or ["known"]):
            errors.append(f"fact_status_not_accepted:{key}:{status}")
        value = fact.get("value")
        if status == "known":
            schema_error = _schema_error(field.get("value_schema") or {}, value)
            if schema_error:
                errors.append(f"fact_schema_invalid:{key}:{schema_error}")
        elif value is not None:
            errors.append(f"non_known_fact_has_value:{key}")
        previous = facts.get(key)
        if previous and (previous.get("value"), previous.get("status")) != (value, status):
            policy = field.get("overwrite_policy") or "explicit_correction"
            if policy == "never":
                errors.append(f"fact_overwrite_forbidden:{key}")
            elif policy == "explicit_correction" and not _CORRECTION_MARKER.search(message or ""):
                errors.append(f"fact_correction_not_explicit:{key}")
            elif policy == "higher_confidence" and float(fact.get("confidence") or 0) <= float(previous.get("confidence") or 0):
                errors.append(f"fact_overwrite_confidence_too_low:{key}")
        for dependency in field.get("depends_on") or []:
            dependency_field = fields.get(dependency) or {}
            if not field_resolved(dependency_field, facts.get(dependency)):
                errors.append(f"fact_dependency_unsatisfied:{key}:{dependency}")
        if not _condition_matches(field.get("condition"), facts):
            errors.append(f"fact_condition_not_met:{key}")
        if len(errors) != fact_error_count:
            continue
        accepted = {
            **fact, "field_key": key, "source_message_id": source_message_id,
            "confidence": float(fact.get("confidence") or 0),
        }
        facts[key] = accepted
        accepted_facts.append(accepted)

    missing = pending_fields(contract, facts)
    missing_keys = [field["key"] for field in missing]
    question_id = proposal.get("next_question_node_id")
    questions = contract.get("questions") or {}
    if missing:
        question = questions.get(str(question_id or ""))
        if not question or question.get("field_key") not in missing_keys:
            errors.append("next_question_not_for_pending_field")
        else:
            if any(dependency in missing_keys for dependency in question.get("depends_on") or []):
                errors.append("next_question_dependencies_unsatisfied")
            if question_id not in package_node_ids:
                errors.append(f"question_outside_package:{question_id}")
                repair.append({"kind": "node", "id": question_id})
    elif question_id:
        errors.append("question_after_completion")
    if bool(proposal.get("qualification_complete")) != (not missing):
        errors.append("qualification_completion_mismatch")

    for claim in proposal.get("claims") or []:
        claim_type = str(claim.get("claim_type") or "other")
        evidence_nodes = set(claim.get("evidence_node_ids") or [])
        evidence_chunks = set(claim.get("evidence_chunk_ids") or [])
        policies = _claim_policy(contract, claim_type)
        if not policies:
            errors.append(f"claim_not_authorized:{claim_type}")
        if not evidence_nodes and not evidence_chunks:
            errors.append(f"claim_without_evidence:{claim_type}")
        if not evidence_nodes.issubset(package_node_ids & closure):
            errors.append(f"claim_node_evidence_outside_package:{claim_type}")
            repair.extend({"kind": "node", "id": value} for value in evidence_nodes - package_node_ids)
        if not evidence_chunks.issubset(package_chunk_ids):
            errors.append(f"claim_chunk_evidence_outside_package:{claim_type}")
            repair.extend({"kind": "chunk", "id": value} for value in evidence_chunks - package_chunk_ids)
        authorized_nodes = {
            str(value) for policy in policies
            for value in policy.get("evidence_node_ids") or []
        }
        authorized_chunks = {
            str(value) for policy in policies
            for value in policy.get("evidence_chunk_ids") or []
        }
        unsupported_nodes = evidence_nodes - authorized_nodes
        unsupported_chunks = {
            chunk_id for chunk_id in evidence_chunks
            if chunk_id not in authorized_chunks
            and chunk_sources.get(chunk_id) not in authorized_nodes
        }
        if unsupported_nodes or unsupported_chunks:
            errors.append(f"claim_evidence_not_authorized:{claim_type}")

    handoff_rules = contract.get("handoff_rules") or []
    handoff_required = any(
        _handoff_rule_matches(
            rule, facts=facts, qualification_complete=not missing
        ) for rule in handoff_rules
    )
    if proposal.get("handoff_requested") is True and not handoff_required:
        errors.append("handoff_not_authorized")
    if proposal.get("handoff_requested") is not True and handoff_required:
        errors.append("handoff_required_by_rule")
    if _FINAL_CONFIRMATION.search(str(proposal.get("reply") or "")) and missing:
        errors.append("premature_final_confirmation")

    repair = list({(item["kind"], item["id"]): item for item in repair if item.get("id")}.values())
    repair_only = bool(errors) and all("outside_package" in error for error in errors)
    return {
        "valid": not errors, "errors": errors,
        "repair_required": repair_only and bool(repair),
        "repair_requirements": repair, "ledger": next_ledger,
        "accepted_facts": accepted_facts, "missing_fields": missing_keys,
        "next_question_node_id": question_id,
    }


def compose_published_question(
    *, reply: str, next_question_node_id: str | None, contract: dict[str, Any]
) -> str:
    """Emit the published speech act without requiring verbatim model output."""
    text = str(reply or "").strip()
    if not next_question_node_id:
        return text
    question = str(((contract.get("questions") or {}).get(next_question_node_id) or {}).get("text") or "").strip()
    if not question or question.casefold() in text.casefold():
        return text
    return f"{text}\n\n{question}".strip()

"""Question authoring, field requirements and compiler-respected ordering."""
from __future__ import annotations
import copy
import re
import unicodedata
from typing import Any
from services import graph_bundle, graph_compiler_v3
from services.graph_editor_model import (
    GraphEditorError, EDITOR_SOURCE, QUESTION_STAGES, _EDITABLE_KNOWLEDGE_TYPES,
    _persona_node, _stage, journey_view, _NAME_KEYS,
)

from services.graph_editor_operations import (
    QUESTION_MODES, VALIDATION_MODES, MAX_QUESTION_CHARS, MAX_TEXT_CHARS, MAX_LABEL_CHARS, _FIELDS_KEY, _PLAIN_FIELDS_KEY, _FIELD_LIST_KEYS, _COMPLETION_KEYS, _QUESTION_KEY, _CONTENT_QUESTION_KEY, _MODES_KEY, _APPOINTMENT_MODES_KEY, _LABELS_KEY, _APPOINTMENT_LABELS_KEY, _TEXT_KEYS, _NEW_QUESTION_PREFIX, _Draft, _update, _declaring_nodes, _rewrite_fields, _declared, _boolean, _valid_text, _get_dotted, _mode_maps, _question_modes, _field_lists, _validation_mode, _declared_field_keys, _is_question_node, apply_operations,
)

def _set_active(draft: _Draft, key: str, active: bool) -> list[dict[str, Any]]:
    _declared(draft, key)
    appointment, qualification = _mode_maps(draft.bundle)
    patch: dict[str, Any] = {}
    if not active:
        if {**appointment, **qualification}.get(key) != "disabled":
            patch[_MODES_KEY] = {**qualification, key: "disabled"}
    else:
        if qualification.get(key) == "disabled":
            qualification.pop(key)
            patch[_MODES_KEY] = qualification
        if key not in qualification and appointment.get(key) == "disabled":
            appointment.pop(key)
            patch[_APPOINTMENT_MODES_KEY] = appointment
    return [_update(_persona_node(draft.bundle)["id"], patch)] if patch else []


def _set_essential(draft: _Draft, key: str, essential: bool, branch: str | None) -> list[dict[str, Any]]:
    nodes = _declared(draft, key)
    targets = {node["id"] for node in nodes}
    if branch:
        document = draft.document
        anchors = document.get("branch_anchors") or []
        if branch not in anchors:
            raise GraphEditorError(f"essential_branch_unknown:{key}:{branch}")
        memberships = document.get("branch_memberships") or {}
        elsewhere = {node_id for anchor in anchors if anchor != branch for node_id in memberships.get(anchor) or {}}
        # Only declarations that no other path compiles may change for one path.
        targets = {node_id for node_id in targets if node_id in (memberships.get(branch) or {}) and node_id not in elsewhere}
        if not targets:
            raise GraphEditorError(f"essential_branch_shared:{key}:{branch}")
    operations: list[dict[str, Any]] = []
    appointment, qualification = _mode_maps(draft.bundle)
    forced = {**appointment, **qualification}.get(key)
    if forced in {"required", "optional"}:
        # An explicit mode overrides every declaration. Fold it into the
        # declarations so the declarations alone decide from now on.
        patch = {}
        for path, modes in ((_MODES_KEY, qualification), (_APPOINTMENT_MODES_KEY, appointment)):
            if key in modes:
                modes.pop(key)
                patch[path] = modes
        operations.append(_update(_persona_node(draft.bundle)["id"], patch))
    for node in nodes:
        if node["id"] in targets:
            required = essential
        elif forced in {"required", "optional"}:
            required = forced == "required"
        else:
            continue
        operations += _rewrite_fields(node, key, lambda field, value=required: {**field, "required": value})
    return operations


def _set_tracking(draft: _Draft, key: str, tracking: bool) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for node in _declared(draft, key):
        operations += _rewrite_fields(
            node, key, lambda field: field if bool(field.get("tracking")) == tracking else {**field, "tracking": tracking},
        )
    return operations


def _set_question_text(draft: _Draft, key: str, text: Any) -> list[dict[str, Any]]:
    declarations = [
        field for node in _declared(draft, key) for _, fields in _field_lists(node)
        for field in fields if isinstance(field, dict) and field.get("key") == key
    ]
    if not _valid_text(text, MAX_QUESTION_CHARS):
        raise GraphEditorError(f"question_text_invalid:{key}")
    nodes = {node["id"]: node for node in draft.bundle["nodes"]}
    question_ids = list(dict.fromkeys(str(f["question_node_id"]) for f in declarations if f.get("question_node_id")))
    if not question_ids or any(question_id not in nodes for question_id in question_ids):
        raise GraphEditorError(f"question_node_missing:{key}")
    operations = []
    for question_id in question_ids:
        content = (nodes[question_id].get("data") or {}).get("content")
        # The compiler reads data.content.question before data.question.
        path = _CONTENT_QUESTION_KEY if isinstance(content, dict) and content.get("question") else _QUESTION_KEY
        operations.append(_update(question_id, {path: text.strip()}))
    return operations


def _new_question_key(bundle: dict[str, Any], label: str) -> str:
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "_", ascii_label).strip("_")[:48].strip("_")
    if not base:
        raise GraphEditorError("add_question_label_invalid")
    taken = _declared_field_keys(bundle) | {
        node["id"][len(_NEW_QUESTION_PREFIX):] for node in bundle["nodes"]
        if str(node.get("id") or "").startswith(_NEW_QUESTION_PREFIX)
    }
    key, suffix = base, 2
    while key in taken:
        key, suffix = f"{base}_{suffix}", suffix + 1
    return key


def _priority_below(priorities: list[float]) -> float:
    lowest = min(priorities) if priorities else 0.5
    # The compiler reads priority 0 as 0.5, so stay strictly positive.
    return round(lowest - 0.1, 4) if lowest > 0.15 else round(lowest / 2, 6)


def _add_question(draft: _Draft, change: dict[str, Any]) -> list[dict[str, Any]]:
    stage = change.get("stage")
    if stage not in QUESTION_STAGES:
        raise GraphEditorError(f"add_question_stage_invalid:{stage}")
    label = change.get("label")
    if not _valid_text(label, MAX_LABEL_CHARS):
        raise GraphEditorError("add_question_label_invalid")
    label = label.strip()
    key = _new_question_key(draft.bundle, label)
    text = change.get("text")
    if not _valid_text(text, MAX_QUESTION_CHARS):
        raise GraphEditorError(f"question_text_invalid:{key}")
    essential = _boolean(change, "essential", key)
    tracking = change.get("tracking", False)
    if not isinstance(tracking, bool):
        raise GraphEditorError(f"change_value_invalid:{key}:tracking")
    persona = _persona_node(draft.bundle)
    nodes = {node["id"]: node for node in draft.bundle["nodes"]}
    document = draft.document
    stage_keys = {question["key"] for question in _stage(draft.journey, stage)["questions"]}
    if stage == "service":
        branch_ids = change.get("branch_node_ids")
        if not isinstance(branch_ids, list) or not branch_ids:
            raise GraphEditorError(f"add_question_branches_required:{key}")
        anchors = document.get("branch_anchors") or []
        unknown = [branch for branch in branch_ids if branch not in anchors]
        if unknown:
            raise GraphEditorError(f"add_question_branch_unknown:{key}:{unknown[0]}")
        owners, scope = [nodes[branch] for branch in dict.fromkeys(branch_ids)], "branch"
        contract_fields = [
            field for anchor in dict.fromkeys(branch_ids)
            for field in (document["branch_contracts"][anchor].get("fields") or [])
        ]
    else:
        owners, scope = [persona], "persona"
        tracking = tracking or stage == "classification"
        contract_fields = list((document.get("common_contract") or {}).get("fields") or [])
    in_stage = [float(f.get("priority") or 0.5) for f in contract_fields if f["key"] in stage_keys]
    priority = _priority_below(in_stage or [float(f.get("priority") or 0.5) for f in contract_fields])
    question_id = f"{_NEW_QUESTION_PREFIX}{key}"
    operations: list[dict[str, Any]] = [
        {"op": "add_node", "node": {"id": question_id, "node_type": "faq", "title": label,
                                    "data": {"role": "qualification_question", "question": text.strip()}}},
        {"op": "add_edge", "edge": {"source": persona["id"], "target": question_id, "relation_type": "contains"}},
    ]
    for owner in owners:
        field = {
            "key": key, "required": essential, "priority": priority, "scope": scope,
            "owner_node_id": owner["id"], "question_node_id": question_id, "depends_on": [],
            "accepted_statuses": ["known"], "overwrite_policy": "explicit_correction",
            "validation": {"mode": "schema"}, "value_schema": {"type": "string", "minLength": 1},
            "tracking": tracking,
        }
        path, fields = (_field_lists(owner) or [(_FIELDS_KEY, [])])[-1]
        operations.append(_update(owner["id"], {path: [*fields, field]}))
    # The journey shows the label the compiler publishes: conversation
    # field_labels, or the appointment ones when that map is empty.
    labels_path = _LABELS_KEY
    if not _get_dotted(persona, _LABELS_KEY) and _get_dotted(persona, _APPOINTMENT_LABELS_KEY):
        labels_path = _APPOINTMENT_LABELS_KEY
    labels = dict(_get_dotted(persona, labels_path) or {})
    operations.append(_update(persona["id"], {labels_path: {**labels, key: label}}))
    return operations


def _new_priorities(order: list[str], current: dict[str, float]) -> dict[str, float]:
    """Reuse the stage's priority values in the new order; spread them if tied."""
    slots = sorted((current[key] for key in order), reverse=True)
    if len(set(slots)) < len(slots):
        high, low, count = slots[0], slots[-1], len(slots)
        if high == low:
            slots = [round(high + 0.01 * (count - 1 - index), 4) for index in range(count)]
        else:
            slots = [round(high - (high - low) * index / (count - 1), 4) for index in range(count)]
    return dict(zip(order, slots))


def _move_question(draft: _Draft, change: dict[str, Any]) -> list[dict[str, Any]]:
    stage, key, direction = change.get("stage"), str(change.get("key") or ""), change.get("direction")
    if stage not in QUESTION_STAGES or direction not in (-1, 1) or isinstance(direction, bool):
        raise GraphEditorError(f"change_value_invalid:{key}:move")
    if stage == "service":
        # Service questions are shown by how many paths ask them; each path
        # keeps its own compiled order, so there is no single order to move.
        raise GraphEditorError(f"move_service_order_fixed:{key}")
    order = [question["key"] for question in _stage(draft.journey, stage)["questions"]]
    if key not in order:
        raise GraphEditorError(f"move_question_not_in_stage:{key}:{stage}")
    index = order.index(key)
    if not 0 <= index + direction < len(order):
        raise GraphEditorError(f"move_out_of_range:{key}")
    order[index], order[index + direction] = order[index + direction], order[index]
    current = {
        field["key"]: float(field.get("priority") or 0.5)
        for field in (draft.document.get("common_contract") or {}).get("fields") or []
    }
    priorities = _new_priorities(order, current)
    operations: list[dict[str, Any]] = []
    for field_key in order:  # coherent priority on every declaration of the stage
        for node in _declaring_nodes(draft.bundle, field_key):
            operations += _rewrite_fields(
                node, field_key, lambda field, value=priorities[field_key]: {**field, "priority": value},
            )
    moved = journey_view(graph_bundle.compile_bundle(apply_operations(draft.bundle, operations)))["journey"]
    if [question["key"] for question in _stage(moved, stage)["questions"]] != order:
        raise GraphEditorError(f"move_not_honored:{key}")
    return operations



def _set_question(draft: _Draft, change: dict[str, Any]) -> list[dict[str, Any]]:
    """One attribute at a time; the caller splits multi-attribute changes."""
    key = str(change.get("key") or "")
    if "active" in change:
        return _set_active(draft, key, _boolean(change, "active", key))
    if "essential" in change:
        branch = change.get("branch_node_id")
        return _set_essential(draft, key, _boolean(change, "essential", key), str(branch) if branch else None)
    if "tracking" in change:
        return _set_tracking(draft, key, _boolean(change, "tracking", key))
    if "text" in change:
        return _set_question_text(draft, key, change["text"])
    raise GraphEditorError(f"set_question_without_change:{key}")

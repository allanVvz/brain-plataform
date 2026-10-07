"""Graph editor operation vocabulary, ownership checks and normalization."""
from __future__ import annotations
import copy
import re
import unicodedata
from typing import Any
from services import graph_bundle, graph_compiler_v3
from services.graph_editor_model import (
    GraphEditorError, EDITOR_SOURCE, QUESTION_STAGES, _EDITABLE_KNOWLEDGE_TYPES,
    _persona_node, _stage, journey_view,
)

QUESTION_MODES = {"required", "optional", "disabled"}
VALIDATION_MODES = {"enum", "schema", "semantic"}
MAX_QUESTION_CHARS = 500
MAX_TEXT_CHARS = 2000
MAX_LABEL_CHARS = 80
_FIELDS_KEY = "data.qualification.fields"
_PLAIN_FIELDS_KEY = "data.fields"
_FIELD_LIST_KEYS = (_PLAIN_FIELDS_KEY, _FIELDS_KEY)
_COMPLETION_KEYS = ("data.completion.required_fields", "data.booking.required_fields")
_QUESTION_KEY = "data.question"
_CONTENT_QUESTION_KEY = "data.content.question"
_MODES_KEY = "data.conversation_policy.qualification.question_modes"
_APPOINTMENT_MODES_KEY = "data.appointment_policy.question_modes"
_LABELS_KEY = "data.conversation_policy.field_labels"
_APPOINTMENT_LABELS_KEY = "data.appointment_policy.field_labels"
_TEXT_KEYS = {
    "opening": "data.conversation_policy.opening.first_turn",
    "closing": "data.conversation_policy.post_qualification_support.transition",
}
_PERSONA_ONLY_KEYS = {
    _MODES_KEY, _APPOINTMENT_MODES_KEY, _LABELS_KEY, _APPOINTMENT_LABELS_KEY, *_TEXT_KEYS.values(),
}
_ALLOWED_PATCH_KEYS = {
    *_FIELD_LIST_KEYS, *_COMPLETION_KEYS, _QUESTION_KEY, _CONTENT_QUESTION_KEY, *_PERSONA_ONLY_KEYS,
    "summary", "data.answer", "data.content.answer", "data.content.resposta",
}
_NEW_QUESTION_PREFIX = "faq:qualification:"


def _is_question_node(node: dict[str, Any]) -> bool:
    data = node.get("data") or {}
    role = data.get("role") or (data.get("metadata") or {}).get("role")
    return node.get("node_type") == "faq" and role == "qualification_question"


def _get_dotted(target: dict[str, Any], dotted: str) -> Any:
    cursor: Any = target
    for key in dotted.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def _set_dotted(target: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cursor = target
    for key in keys[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    cursor[keys[-1]] = copy.deepcopy(value)


def _validation_mode(field: dict[str, Any]) -> str:
    # Same resolution as the compiler: explicit mode, or "schema" when the
    # field carries a value_schema.
    return graph_compiler_v3._compiled_field_validation(field)["mode"]


def _valid_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _check_fields(node: dict[str, Any], key: str, value: Any) -> None:
    node_id = node["id"]
    if not isinstance(value, list) or not all(
        isinstance(field, dict) and isinstance(field.get("key"), str) and field["key"] for field in value
    ):
        raise GraphEditorError(f"qualification_fields_invalid:{node_id}")
    before = {
        field["key"]: field for field in _get_dotted(node, key) or []
        if isinstance(field, dict) and field.get("key")
    }
    for field in value:
        if _validation_mode(field) not in VALIDATION_MODES:
            raise GraphEditorError(f"field_validation_mode_missing:{node_id}:{field['key']}")
        if "tracking" in field and not isinstance(field["tracking"], bool):
            raise GraphEditorError(f"field_tracking_invalid:{node_id}:{field['key']}")
        prior = before.get(field["key"])
        # Collected facts are keyed by owner: an edit never moves them.
        if prior is not None and any(prior.get(attr) != field.get(attr) for attr in ("owner_node_id", "scope")):
            raise GraphEditorError(f"field_owner_change_refused:{node_id}:{field['key']}")


def _check_patch(node: dict[str, Any], key: str, value: Any, *, persona_id: str) -> None:
    node_id = node["id"]
    if key not in _ALLOWED_PATCH_KEYS:
        raise GraphEditorError(f"operation_patch_key_not_editable:{node_id}:{key}")
    if key in {"summary", "data.answer", "data.content.answer", "data.content.resposta"}:
        if node.get("node_type") not in _EDITABLE_KNOWLEDGE_TYPES or not _valid_text(value, MAX_TEXT_CHARS):
            raise GraphEditorError(f"knowledge_text_invalid:{node_id}")
        if key in {"data.answer", "data.content.answer", "data.content.resposta"} and (node.get("node_type") != "faq" or _is_question_node(node)):
            raise GraphEditorError(f"knowledge_answer_not_editable:{node_id}")
        return
    if key in _PERSONA_ONLY_KEYS and node_id != persona_id:
        raise GraphEditorError(f"setting_only_on_persona:{node_id}:{key}")
    if key in (_MODES_KEY, _APPOINTMENT_MODES_KEY):
        if not isinstance(value, dict) or any(
            not isinstance(field, str) or mode not in QUESTION_MODES for field, mode in value.items()
        ):
            raise GraphEditorError("question_modes_invalid")
    elif key in (_QUESTION_KEY, _CONTENT_QUESTION_KEY):
        if node.get("node_type") != "faq":
            raise GraphEditorError(f"question_text_only_on_question_nodes:{node_id}")
        if not _valid_text(value, MAX_QUESTION_CHARS):
            raise GraphEditorError(f"question_text_invalid:{node_id}")
    elif key in _FIELD_LIST_KEYS:
        _check_fields(node, key, value)
    elif key in _TEXT_KEYS.values():
        if not _valid_text(value, MAX_TEXT_CHARS):
            raise GraphEditorError(f"text_invalid:{key}")
    elif key in (_LABELS_KEY, _APPOINTMENT_LABELS_KEY):
        if not isinstance(value, dict) or not all(
            isinstance(field, str) and _valid_text(label, MAX_LABEL_CHARS) for field, label in value.items()
        ):
            raise GraphEditorError("field_labels_invalid")
    elif not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GraphEditorError(f"required_fields_invalid:{node_id}:{key}")


def _check_new_node(node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("id") or "")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    question = data.get("question")
    if node_id == "rule:journey:confirmation" and node.get("node_type") == "rule":
        if data != {"capabilities": {"global_context": True, "journey_stage": "confirmation"}} or not _valid_text(node.get("summary"), MAX_TEXT_CHARS):
            raise GraphEditorError("journey_rule_invalid")
        return copy.deepcopy(node)
    if (
        not node_id.startswith(_NEW_QUESTION_PREFIX)
        or node.get("node_type") != "faq"
        or data.get("role") != "qualification_question"
        or not _valid_text(question, MAX_QUESTION_CHARS)
    ):
        raise GraphEditorError(f"add_node_only_qualification_questions:{node_id}")
    key = node_id[len(_NEW_QUESTION_PREFIX):]
    return {
        "id": node_id,
        "node_type": "faq",
        "slug": str(node.get("slug") or f"qualification-{key}"),
        "title": str(node.get("title") or key),
        "summary": "Pergunta de qualificação definida pelo grafo.",
        "tags": [],
        "status": "approved",
        "data": {
            "question": question.strip(),
            "role": "qualification_question",
            "metadata": {"role": "qualification_question", "field_key": key},
            "source": EDITOR_SOURCE,
            "validation_status": "approved",
        },
    }


def apply_operations(bundle: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply editor operations to a rebuilt bundle; anything else is refused."""
    result = copy.deepcopy(bundle)
    nodes = {node["id"]: node for node in result["nodes"]}
    edge_ids = {edge["id"] for edge in result["edges"]}
    persona_id = _persona_node(result)["id"]
    added: set[str] = set()
    for operation in operations:
        op = operation.get("op")
        if op == "update_node":
            node_id = str(operation.get("node_id") or "")
            node = nodes.get(node_id)
            if node is None:
                raise GraphEditorError(f"node_not_found:{node_id}")
            patch = operation.get("patch")
            if not isinstance(patch, dict) or not patch:
                raise GraphEditorError(f"update_node_patch_required:{node_id}")
            for key, value in patch.items():
                _check_patch(node, key, value, persona_id=persona_id)
                _set_dotted(node, key, value)
        elif op == "add_node":
            node = _check_new_node(operation.get("node") or {})
            if node["id"] in nodes:
                raise GraphEditorError(f"node_already_exists:{node['id']}")
            nodes[node["id"]] = node
            result["nodes"].append(node)
            added.add(node["id"])
        elif op == "add_edge":
            edge = operation.get("edge") or {}
            source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
            relation = str(edge.get("relation_type") or "")
            if source == "@persona":
                source = persona_id
            if relation != "contains" or source != persona_id or target not in added:
                raise GraphEditorError(f"add_edge_only_persona_contains_new_question:{source}:{target}")
            edge_id = str(edge.get("id") or f"edge:{source}:contains:{target}")
            if edge_id in edge_ids:
                raise GraphEditorError(f"edge_already_exists:{edge_id}")
            edge_ids.add(edge_id)
            result["edges"].append({
                "id": edge_id, "source": source, "target": target, "relation_type": "contains",
                "weight": 1.0, "metadata": {"active": True, "graph_json_edge_id": edge_id},
            })
        else:
            raise GraphEditorError(f"operation_not_supported:{op}")
    return normalize_required_lists(result)


def _mode_maps(bundle: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """(appointment_policy, conversation_policy.qualification) question modes."""
    data = _persona_node(bundle).get("data") or {}
    appointment = (data.get("appointment_policy") or {}).get("question_modes") or {}
    qualification = ((data.get("conversation_policy") or {}).get("qualification") or {}).get("question_modes") or {}
    return dict(appointment), dict(qualification)


def _question_modes(bundle: dict[str, Any]) -> dict[str, str]:
    # The compiler reads both maps; the qualification map wins.
    appointment, qualification = _mode_maps(bundle)
    return {**appointment, **qualification}


def _field_lists(node: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    # Same declaration sources as graph_compiler_v3 (data.fields and
    # data.qualification.fields on any node).
    data = node.get("data") or {}
    lists: list[tuple[str, list[Any]]] = []
    if isinstance(data.get("fields"), list):
        lists.append((_PLAIN_FIELDS_KEY, data["fields"]))
    qualification = data.get("qualification")
    if isinstance(qualification, dict) and isinstance(qualification.get("fields"), list):
        lists.append((_FIELDS_KEY, qualification["fields"]))
    return lists


def _declared_field_keys(bundle: dict[str, Any]) -> set[str]:
    return {
        str(field["key"])
        for node in bundle["nodes"] for _, fields in _field_lists(node)
        for field in fields if isinstance(field, dict) and field.get("key")
    }


def normalize_required_lists(bundle: dict[str, Any]) -> dict[str, Any]:
    """Explicit completion/booking lists only name questions that exist and are on.

    These lists reach the model's turn context; a disabled key, or a key with
    no declared question anywhere, would still read as something to collect.
    Order is kept.
    """
    disabled = {key for key, mode in _question_modes(bundle).items() if mode == "disabled"}
    # A key declared in some other branch is not a requirement of this branch.
    # Compile before filtering: it preserves the ownership/path resolution used
    # by the runtime instead of approximating it with a global field union.
    document = graph_bundle.compile_bundle(bundle)
    contracts = list((document.get("branch_contracts") or {}).values())
    for node in bundle["nodes"]:
        scoped = [contract for contract in contracts if node["id"] in (contract.get("closure_node_ids") or [])]
        declared = set.intersection(*(set(f["key"] for f in contract.get("fields") or []) for contract in scoped)) if scoped else {
            f["key"] for _, fields in _field_lists(node) for f in fields if isinstance(f, dict) and f.get("key")
        }
        data = node.get("data") or {}
        for section in ("completion", "booking"):
            listed = data.get(section)
            if isinstance(listed, dict) and isinstance(listed.get("required_fields"), list):
                listed["required_fields"] = [
                    key for key in listed["required_fields"] if key in declared and key not in disabled
                ]
    return bundle


# ── Changes → operations ───────────────────────────────────────────────────
# The screen sends semantic changes (JourneyChange in the portal); each one is
# expanded against the bundle as left by the previous changes.

class _Draft:
    """The bundle after the changes expanded so far, compiled on demand."""

    def __init__(self, bundle: dict[str, Any], document: dict[str, Any] | None):
        self.bundle = bundle
        self._document = document

    @property
    def document(self) -> dict[str, Any]:
        if self._document is None:
            self._document = graph_bundle.compile_bundle(self.bundle)
        return self._document

    @property
    def journey(self) -> dict[str, Any]:
        return journey_view(self.document)["journey"]

    def apply(self, operations: list[dict[str, Any]]) -> None:
        if operations:
            self.bundle = apply_operations(self.bundle, operations)
            self._document = None


def _update(node_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    return {"op": "update_node", "node_id": node_id, "patch": patch}


def _declaring_nodes(bundle: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        node for node in bundle["nodes"]
        if any(isinstance(field, dict) and field.get("key") == key
               for _, fields in _field_lists(node) for field in fields)
    ]


def _rewrite_fields(node: dict[str, Any], key: str, rewrite) -> list[dict[str, Any]]:
    """update_node rewriting the declarations of ``key`` on ``node`` (if any changes)."""
    patch = {}
    for path, fields in _field_lists(node):
        rewritten = [
            rewrite(copy.deepcopy(field)) if isinstance(field, dict) and field.get("key") == key else field
            for field in fields
        ]
        if rewritten != fields:
            patch[path] = rewritten
    return [_update(node["id"], patch)] if patch else []


def _declared(draft: _Draft, key: str) -> list[dict[str, Any]]:
    nodes = _declaring_nodes(draft.bundle, key)
    if not key or not nodes:
        raise GraphEditorError(f"question_not_found:{key}")
    return nodes


def _boolean(change: dict[str, Any], name: str, key: str) -> bool:
    value = change.get(name)
    if not isinstance(value, bool):
        raise GraphEditorError(f"change_value_invalid:{key}:{name}")
    return value

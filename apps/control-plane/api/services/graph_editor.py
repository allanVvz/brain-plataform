"""Graph editor: edit the active GraphBundle publication from the AKIA screen.

The SDR reads only the active ``graph_publications`` row. Every edit starts
from that publication: its ``document_json`` already carries the complete
bundle graph (nodes in bundle form, edges plus a compiler-derived ``primary``
flag), so the source bundle is rebuilt from it and checked by recompiling to
the same content before any edit is accepted.

The screen reads a *journey* (stages of the conversation and their questions)
and a *knowledge* index, both built from the compiled document. It writes
semantic *changes*; the server expands them into graph operations (the
``apply_operations`` vocabulary), validates, compiles and publishes in one
call. See akia/docs/architecture/engenharia-de-grafo.md, "Revisão 2026-10-03
(tarde)".
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from services import graph_bundle, graph_compiler_v3

BUNDLE_VERSION = "1.0"
EDITOR_SOURCE = "akia_graph_editor"


class GraphEditorError(ValueError):
    """An edit or base that the editor refuses, with a stable code."""


class GraphEditorConflict(GraphEditorError):
    """The base is no longer the active publication."""


def _embedding_profile(document: dict[str, Any]) -> dict[str, Any]:
    manifest = document.get("projection_manifest") or {}
    profile = {
        "embedding_provider": manifest.get("embedding_provider"),
        "embedding_model": manifest.get("embedding_model"),
        "embedding_dimension": manifest.get("embedding_dimension"),
    }
    if not all(profile.values()):
        raise GraphEditorError("base_embedding_profile_missing")
    return profile


def _document(publication: dict[str, Any]) -> dict[str, Any]:
    return publication.get("document_json") or publication.get("document") or {}


def bundle_from_publication(publication: dict[str, Any], *, purpose: str = "") -> dict[str, Any]:
    """Rebuild the source bundle of an active publication.

    ``primary`` on edges is derived by the compiler and is dropped; nodes are
    kept as published (including ``projection_node_id``).
    """
    document = _document(publication)
    persona = document.get("persona") or {}
    if not persona.get("id") or not persona.get("slug"):
        raise GraphEditorError("base_persona_missing")
    nodes = document.get("nodes")
    edges = document.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
        raise GraphEditorError("base_graph_missing")
    return {
        "bundle_version": BUNDLE_VERSION,
        "persona": {"id": str(persona["id"]), "slug": str(persona["slug"])},
        "metadata": {
            "baseline_publication": {
                "publication_id": str(publication.get("id") or ""),
                "version": int(publication.get("version") or 0),
                "checksum": str(publication.get("checksum") or ""),
            },
            "embedding_profile": _embedding_profile(document),
            "internal_wa_validator_test_allowed": False,
            "publication_allowed": True,
            "purpose": purpose or "Edição pelo editor de grafo do AKIA",
            "source": EDITOR_SOURCE,
        },
        "nodes": copy.deepcopy(nodes),
        "edges": [{key: value for key, value in edge.items() if key != "primary"} for edge in edges],
    }


def _base_check(publication: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the bundle and recompile it against the active document."""
    document = _document(publication)
    bundle = bundle_from_publication(publication)
    plan = graph_bundle.build_publication_plan(bundle, current_document=document)
    changes = {key: plan.get(key) for key in ("node_changes", "edge_changes")}
    changed = any((changes["node_changes"] or {}).get(kind) for kind in ("added", "changed", "removed"))
    errors = list(plan.get("validation_errors") or [])
    return {
        "bundle": bundle,
        # Editable when the rebuilt bundle carries no content change; a newer
        # compiler alone changes the checksum and is surfaced, not hidden.
        "editable": not errors and not changed,
        "blocked_reasons": errors + (["base_content_changed_on_rebuild"] if changed and not errors else []),
        "validation_errors": errors,
        "runtime_checksum": plan.get("runtime_checksum"),
        "changes": changes,
        "document": plan.get("candidate_document"),
    }


def verify_round_trip(publication: dict[str, Any]) -> dict[str, Any]:
    """The rebuilt bundle must compile to the active runtime checksum, unchanged."""
    check = _base_check(publication)
    same_checksum = check["runtime_checksum"] == publication.get("checksum")
    return {
        "editable": bool(same_checksum and not check["validation_errors"]),
        "runtime_checksum": check["runtime_checksum"],
        "active_checksum": publication.get("checksum"),
        "validation_errors": check["validation_errors"],
        "changes": check["changes"],
    }


# ── Journey and knowledge (what the screen reads) ──────────────────────────
# Port of graph-engineering/data/journey_reference.py, the specification that
# produced the frozen fixtures; behavior must stay identical.

_HIDDEN_KNOWLEDGE_TYPES = {"persona", "embedded", "gallery"}
_NAME_KEYS = {"nome_cliente", "nome", "customer_name"}
QUESTION_STAGES = ("identification", "classification", "service")


def _document_persona(document: dict[str, Any]) -> dict[str, Any]:
    return next(node for node in document["nodes"] if node["node_type"] == "persona")


def _document_declarations(document: dict[str, Any]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    result: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for node in document["nodes"]:
        data = node.get("data") or {}
        for field in list(data.get("fields") or []) + list((data.get("qualification") or {}).get("fields") or []):
            if isinstance(field, dict) and field.get("key"):
                result.setdefault(field["key"], []).append((node["id"], field))
    return result


def _knowledge_text(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    question, answer = data.get("question"), data.get("answer")
    if isinstance(question, str) and isinstance(answer, str) and answer.strip():
        return f"{question.strip()}\n{answer.strip()}"
    if isinstance(question, str) and question.strip():
        return question.strip()
    return str(node.get("summary") or "").strip()


def journey_view(document: dict[str, Any]) -> dict[str, Any]:
    """``{journey, knowledge}`` of a compiled publication document."""
    nodes = {node["id"]: node for node in document["nodes"]}
    persona = _document_persona(document)
    policy = (persona.get("data") or {}).get("conversation_policy") or {}
    common = document.get("common_contract") or {}
    contracts = document.get("branch_contracts") or {}
    coordinates = document.get("coordinates") or {}
    declarations = _document_declarations(document)

    def path_labels(node_id: str) -> list[str]:
        ids = (coordinates.get(node_id) or {}).get("path_node_ids") or [node_id]
        return [nodes[i]["title"] for i in ids if i in nodes and nodes[i]["node_type"] != "persona"]

    anchors = sorted(contracts, key=lambda anchor: " › ".join(path_labels(anchor)))
    branches = [{"branch_node_id": a, "label": nodes[a]["title"], "path": path_labels(a)} for a in anchors]

    # Knowledge index first: questions report how many items are linked.
    by_question: dict[str, list[str]] = {}
    for key, decls in declarations.items():
        qid = next((f.get("question_node_id") for _, f in decls if f.get("question_node_id")), None)
        linked = [n["id"] for n in document["nodes"] if key in ((n.get("data") or {}).get("field_keys") or [])]
        by_question[key] = ([qid] if qid in nodes else []) + linked
    labels = {**(common.get("field_labels") or {})}
    for contract in contracts.values():
        for key, label in (contract.get("field_labels") or {}).items():
            labels.setdefault(key, label)
    texts: dict[str, str] = {}
    for contract in [common, *contracts.values()]:
        for question in (contract.get("questions") or {}).values():
            texts.setdefault(question["field_key"], question.get("text") or "")

    def tracked(key: str) -> bool:
        return any(field.get("tracking") is True for _, field in declarations.get(key, []))

    def question(field: dict[str, Any], *, branch_ids: list[str] | None = None, per_branch=None) -> dict[str, Any]:
        key = field["key"]
        decls = declarations.get(key, [])
        mode = field.get("question_mode") or ("required" if field.get("required") else "optional")
        result = {
            "key": key,
            "label": labels.get(key) or key,
            "text": texts.get(key, ""),
            "question_node_id": field.get("question_node_id"),
            "active": mode != "disabled",
            "essential": bool(field.get("required")),
            "scope": "branches" if branch_ids is not None else "all",
            "tracking": tracked(key),
            "validation_mode": (field.get("validation") or {}).get("mode"),
            "owner_node_ids": sorted({node_id for node_id, _ in decls}),
            "knowledge_count": len(by_question.get(key, [])),
        }
        if branch_ids is not None:
            result["branches"] = branch_ids
            result["per_branch"] = per_branch or {}
        return result

    common_fields = list(common.get("fields") or [])
    selector_field = next((f for f in common_fields if f.get("branch_selection_field")), None)
    general = [f for f in common_fields if f is not selector_field]
    general.sort(key=lambda f: 0 if f["key"] in _NAME_KEYS else 1)  # stable: name first, rest keep compiled order
    identification = [question(f) for f in general if not tracked(f["key"])]
    classification = [question(f) for f in general if tracked(f["key"])]

    common_keys = {f["key"] for f in common_fields}
    specific: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        for field in contracts[anchor].get("fields") or []:
            if field["key"] in common_keys:
                continue
            entry = specific.setdefault(field["key"], {"field": field, "branches": [], "per_branch": {}})
            entry["branches"].append(anchor)
            entry["per_branch"][anchor] = {"essential": bool(field.get("required"))}
    service_questions = sorted(
        (question(v["field"], branch_ids=v["branches"], per_branch=v["per_branch"]) for v in specific.values()),
        key=lambda q: (-len(q["branches"]), q["label"]),
    )

    handoff_rule_ids: list[str] = []
    for contract in contracts.values():
        for node_id in contract.get("handoff_rule_node_ids") or []:
            if node_id not in handoff_rule_ids:
                handoff_rule_ids.append(node_id)
    opening = (policy.get("opening") or {}).get("first_turn")
    closing = (policy.get("post_qualification_support") or {}).get("transition")
    stages = [
        {"key": "opening", "label": "Abertura", "rule_node_id": None,
         "texts": [{"key": "opening", "label": "Primeira mensagem", "value": opening, "editable": True}]
         if isinstance(opening, str) else []},
        {"key": "identification", "label": "Identificação", "rule_node_id": None, "questions": identification},
        {"key": "classification", "label": "Classificação", "rule_node_id": None, "questions": classification,
         "selector": None if selector_field is None else {
             "field_key": selector_field["key"], "question": question(selector_field), "options": branches}},
        {"key": "service", "label": "Perguntas do serviço", "rule_node_id": None,
         "questions": service_questions, "branches": branches},
        {"key": "confirmation", "label": "Confirmação", "rule_node_id": None,
         "description": "O agente escreve o resumo com as respostas da lead e pede confirmação antes de encaminhar."},
        {"key": "handoff", "label": "Encaminhamento", "rule_node_id": None,
         "texts": [{"key": "closing", "label": "Encerramento", "value": closing, "editable": True}]
         if isinstance(closing, str) else [],
         "rules": [{"node_id": i, "title": nodes[i]["title"], "text": str(nodes[i].get("summary") or "")}
                   for i in handoff_rule_ids if i in nodes]},
    ]
    model = "venda" if any(nodes[a]["node_type"] == "audience" for a in anchors) else ("agendamento" if anchors else None)

    memberships = document.get("branch_memberships") or {}
    used = set()
    for contract in contracts.values():
        used.update(contract.get("eligible_faq_node_ids") or [])
        used.update(f.get("question_node_id") for f in contract.get("fields") or [] if f.get("question_node_id"))
    knowledge_nodes = [{
        "id": node["id"], "node_type": node["node_type"], "title": node["title"],
        "status": node.get("status") or "", "text": _knowledge_text(node), "path": path_labels(node["id"]),
        "branch_node_ids": [a for a in anchors if node["id"] in (memberships.get(a) or {})],
        "used_by_sdr": node["id"] in used,
    } for node in document["nodes"] if node["node_type"] not in _HIDDEN_KNOWLEDGE_TYPES]
    knowledge = {
        "nodes": knowledge_nodes,
        "by_branch": {a: list(contracts[a].get("eligible_faq_node_ids") or []) for a in anchors},
        "by_question": by_question,
        "by_stage": {"opening": [], "confirmation": [], "handoff": handoff_rule_ids},
    }
    return {"journey": {"model": model, "branch_count": len(anchors), "stages": stages}, "knowledge": knowledge}


def _stage(journey: dict[str, Any], key: str) -> dict[str, Any]:
    return next(stage for stage in journey["stages"] if stage["key"] == key)


# ── Operations (the only graph writes the editor makes) ────────────────────

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
}
_NEW_QUESTION_PREFIX = "faq:qualification:"


def _persona_node(bundle: dict[str, Any]) -> dict[str, Any]:
    persona = next((node for node in bundle["nodes"] if node.get("node_type") == "persona"), None)
    if persona is None:
        raise GraphEditorError("base_persona_node_missing")
    return persona


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
    if key in _PERSONA_ONLY_KEYS and node_id != persona_id:
        raise GraphEditorError(f"setting_only_on_persona:{node_id}:{key}")
    if key in (_MODES_KEY, _APPOINTMENT_MODES_KEY):
        if not isinstance(value, dict) or any(
            not isinstance(field, str) or mode not in QUESTION_MODES for field, mode in value.items()
        ):
            raise GraphEditorError("question_modes_invalid")
    elif key in (_QUESTION_KEY, _CONTENT_QUESTION_KEY):
        if not _is_question_node(node):
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
    declared = _declared_field_keys(bundle)
    for node in bundle["nodes"]:
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


def _set_text(draft: _Draft, change: dict[str, Any]) -> list[dict[str, Any]]:
    key, value = change.get("key"), change.get("value")
    if key not in _TEXT_KEYS:
        raise GraphEditorError(f"text_key_invalid:{key}")
    if not _valid_text(value, MAX_TEXT_CHARS):
        raise GraphEditorError(f"text_invalid:{key}")
    return [_update(_persona_node(draft.bundle)["id"], {_TEXT_KEYS[key]: value.strip()})]


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


_EXPANSIONS = {
    "set_question": _set_question,
    "add_question": _add_question,
    "move_question": _move_question,
    "set_text": _set_text,
}
_QUESTION_ATTRIBUTES = ("active", "essential", "tracking", "text")


def _split(changes: list[Any]) -> list[dict[str, Any]]:
    result = []
    for change in changes:
        if not isinstance(change, dict) or change.get("type") not in _EXPANSIONS:
            kind = change.get("type") if isinstance(change, dict) else type(change).__name__
            raise GraphEditorError(f"change_not_supported:{kind}")
        attributes = [name for name in _QUESTION_ATTRIBUTES if name in change]
        if change["type"] == "set_question" and len(attributes) > 1:
            base = {name: value for name, value in change.items() if name not in _QUESTION_ATTRIBUTES}
            result += [{**base, name: change[name]} for name in attributes]
        else:
            result.append(change)
    return result


def expand_changes(
    bundle: dict[str, Any], changes: list[dict[str, Any]], *, document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand semantic changes into graph operations, in order.

    ``document`` is the compiled ``bundle`` when the caller already has it.
    Applying the returned operations to ``bundle`` with ``apply_operations``
    reproduces the state each change was expanded against.
    """
    draft = _Draft(copy.deepcopy(bundle), document)
    operations: list[dict[str, Any]] = []
    for change in _split(changes):
        expanded = _EXPANSIONS[change["type"]](draft, change)
        draft.apply(expanded)
        operations += expanded
    return operations


# ── Readable errors ────────────────────────────────────────────────────────

_MESSAGES = {
    # Compiler (graph_compiler_v3) codes.
    "question_mode_field_not_declared": "A pergunta “{label}” não existe em nenhum caminho; não dá para ligar ou desligar.",
    "field_question_empty": "A pergunta “{label}” está sem texto. Escreva a pergunta antes de salvar.",
    "field_question_missing": "A pergunta “{label}” não tem texto de pergunta no grafo.",
    "field_validation_mode_missing": "A pergunta “{label}” precisa de um jeito de validar a resposta (opções, formato ou significado).",
    "ambiguous_field_declaration": "A pergunta “{label}” ficou com duas configurações diferentes no mesmo caminho. Faça a alteração em todos os caminhos.",
    "field_dependency_missing": "A pergunta “{label}” depende de outra pergunta que não existe neste caminho.",
    "field_dependency_cycle": "A pergunta “{label}” depende dela mesma numa cadeia de perguntas.",
    "inconsistent_field_owner": "A pergunta “{label}” ficou com donos diferentes entre os caminhos.",
    "question_mode_invalid": "A pergunta “{label}” recebeu um modo desconhecido.",
    "field_owner_unreachable": "A pergunta “{label}” pertence a um item fora deste caminho.",
    # Editor codes.
    "change_not_supported": "Tipo de alteração desconhecido ({label}).",
    "change_value_invalid": "A alteração da pergunta “{label}” tem um valor inválido.",
    "set_question_without_change": "Nada a alterar na pergunta “{label}”.",
    "question_not_found": "A pergunta “{label}” não existe neste grafo.",
    "question_node_missing": "A pergunta “{label}” não tem um texto de pergunta para editar.",
    "question_text_invalid": "O texto da pergunta não pode ficar vazio nem passar de 500 caracteres.",
    "essential_branch_unknown": "O caminho escolhido para a pergunta “{label}” não existe neste grafo.",
    "essential_branch_shared": "Na pergunta “{label}”, essencial vale para todos os caminhos juntos. Altere em todos.",
    "add_question_stage_invalid": "Escolha a etapa da nova pergunta: identificação, classificação ou serviço.",
    "add_question_label_invalid": "Dê um nome curto à nova pergunta (até 80 caracteres, com letras ou números).",
    "add_question_branches_required": "Escolha ao menos um caminho para a nova pergunta do serviço.",
    "add_question_branch_unknown": "Um dos caminhos escolhidos para a nova pergunta não existe neste grafo.",
    "move_question_not_in_stage": "A pergunta “{label}” não está nesta etapa.",
    "move_out_of_range": "A pergunta “{label}” já está no limite da etapa.",
    "move_not_honored": "A pergunta “{label}” não pode trocar de lugar: o nome vem sempre primeiro e algumas perguntas têm ordem fixa no grafo.",
    "move_service_order_fixed": "Nas perguntas do serviço a ordem é a de cada caminho; não dá para mover nesta etapa.",
    "text_key_invalid": "Só os textos de abertura e de encerramento podem ser editados.",
    "text_invalid": "O texto não pode ficar vazio nem passar de 2000 caracteres.",
    "field_owner_change_refused": "A pergunta “{label}” não pode mudar de dono: as respostas já coletadas dependem dele.",
    "base_not_editable": "Esta versão do grafo não pode ser editada pela tela.",
    "base_not_active": "Outra pessoa salvou uma versão nova. Recarregue o editor e refaça a alteração.",
    "persona_not_found": "Persona não encontrada.",
    "active_publication_not_found": "Esta persona ainda não tem um grafo publicado.",
    "publication_failed": "A publicação falhou e a versão anterior continua ativa.",
}


def readable_errors(errors: list[str], labels: dict[str, str] | None = None) -> list[dict[str, str]]:
    """``[{code, message}]`` in plain Portuguese, one per distinct problem.

    Error strings are ``code:args`` (the compiler may prefix a branch id);
    ``labels`` maps declared field keys to the labels the screen shows.
    """
    labels = labels or {}
    result: list[dict[str, str]] = []
    for error in errors:
        parts = str(error).split(":")
        index = next((i for i, part in enumerate(parts) if part in _MESSAGES), None)
        if index is None:
            item = {"code": parts[0], "message": f"O grafo recusou a alteração ({parts[0]})."}
        else:
            rest = parts[index + 1:]
            key = next((part for part in rest if part in labels), rest[0] if rest else "")
            item = {"code": parts[index], "message": _MESSAGES[parts[index]].format(label=labels.get(key) or key)}
        if item not in result:
            result.append(item)
    return result


class GraphEditorRejected(GraphEditorError):
    """The changes, or the graph they produce, were refused (HTTP 422)."""

    def __init__(self, errors: list[str], *, labels: dict[str, str] | None = None):
        self.errors = readable_errors(errors, labels)
        super().__init__("; ".join(item["code"] for item in self.errors))


def _labels(bundle: dict[str, Any]) -> dict[str, str]:
    data = _persona_node(bundle).get("data") or {}
    published = (data.get("conversation_policy") or {}).get("field_labels") or (
        (data.get("appointment_policy") or {}).get("field_labels") or {})
    return {key: str(published.get(key) or key) for key in _declared_field_keys(bundle)}


# ── Read, plan, save, revert ───────────────────────────────────────────────

def editor_view(publication: dict[str, Any]) -> dict[str, Any]:
    document = _document(publication)
    check = _base_check(publication)
    published_with = publication.get("compiler_version") or document.get("compiler_version")
    return {
        "publication": {key: publication.get(key) for key in ("id", "version", "checksum", "activated_at", "compiler_version")},
        "editable": check["editable"],
        "blocked_reasons": check["blocked_reasons"],
        "compiler_upgrade": None if published_with == graph_compiler_v3.COMPILER_VERSION else {
            "from": published_with, "to": graph_compiler_v3.COMPILER_VERSION,
        },
        "persona_node_id": _persona_node(check["bundle"])["id"],
        **journey_view(document),
    }


def plan_changes(publication: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Dry run of a save: expand, apply, normalize, compile. Nothing is written.

    Raises GraphEditorRejected when the base, a change or the resulting graph
    is refused; otherwise returns the publication plan plus ``bundle``,
    ``operations`` and the new ``journey``.
    """
    document = _document(publication)
    try:
        check = _base_check(publication)
    except GraphEditorError as exc:
        raise GraphEditorRejected([f"base_not_editable:{exc}"]) from exc
    bundle = check["bundle"]
    if not check["editable"]:
        raise GraphEditorRejected([f"base_not_editable:{reason}" for reason in check["blocked_reasons"]])
    try:
        operations = expand_changes(bundle, changes, document=check["document"])
        edited = apply_operations(bundle, operations)
    except graph_compiler_v3.GraphCompilationError as exc:
        raise GraphEditorRejected(exc.errors, labels=_labels(bundle)) from exc
    except GraphEditorError as exc:
        raise GraphEditorRejected([str(exc)], labels=_labels(bundle)) from exc
    result = graph_bundle.build_publication_plan(
        edited, current_document=document, next_version=int(publication.get("version") or 0) + 1,
    )
    if result.get("validation_errors"):
        raise GraphEditorRejected(result["validation_errors"], labels=_labels(edited))
    if result.get("publication_allowed") is not True:
        raise GraphEditorRejected(["publication_not_allowed"])
    candidate = result.pop("candidate_document")
    return {**result, "bundle": edited, "operations": operations, "journey": journey_view(candidate)["journey"]}


_locks: dict[str, Any] = {}
_saved: dict[str, dict[str, Any]] = {}


def _lock(persona_slug: str):
    import threading
    return _locks.setdefault(persona_slug, threading.Lock())


def active_publication(persona_slug: str) -> dict[str, Any]:
    from services import supabase_client
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise GraphEditorError("persona_not_found")
    row = supabase_client.get_active_graph_publication(str(persona["id"]))
    if not row:
        raise GraphEditorError("active_publication_not_found")
    return row


def previous_publication(persona_slug: str, active_id: str) -> dict[str, Any] | None:
    """The publication that was active before the current one (for revert)."""
    from services import supabase_client
    persona = supabase_client.get_persona(persona_slug) or {}
    rows = (
        supabase_client.get_client().table("graph_publications")
        .select("id,version,checksum,status,activated_at")
        .eq("persona_id", str(persona.get("id") or ""))
        .not_.is_("activated_at", "null")
        .order("activated_at", desc=True).limit(5).execute().data
    ) or []
    return next((row for row in rows if str(row.get("id")) != str(active_id)), None)


def save(
    *, persona_slug: str, base_publication_id: str, changes: list[dict[str, Any]],
    actor: str, idempotency_key: str,
) -> dict[str, Any]:
    """Expand, validate, compile, stage and activate, only on top of the active base.

    Checksums are computed and approved here, in the same call; a failed
    activation reactivates the base publication.
    """
    from services import graph_bundle_publisher, supabase_client
    replay_key = f"{persona_slug}:{idempotency_key}"
    with _lock(persona_slug):
        if replay_key in _saved:
            return _saved[replay_key]
        base = active_publication(persona_slug)
        if str(base.get("id")) != str(base_publication_id):
            raise GraphEditorConflict(f"base_not_active:{base_publication_id}:{base.get('id')}")
        reviewed = plan_changes(base, changes)
        bundle = reviewed["bundle"]
        draft_checksum, runtime_checksum = reviewed["draft_checksum"], reviewed["runtime_checksum"]
        staged = graph_bundle_publisher.stage_bundle(bundle, approved_draft_checksum=draft_checksum, actor=actor)
        publication = staged.get("publication") or {}
        try:
            graph_bundle_publisher.activate_staged_bundle(
                bundle, publication_id=str(publication["id"]), approved_draft_checksum=draft_checksum,
                approved_runtime_checksum=runtime_checksum, actor=actor,
            )
            if active_publication(persona_slug).get("checksum") != runtime_checksum:
                raise GraphEditorError("activation_not_confirmed")
        except Exception:
            supabase_client.get_client().rpc(
                "activate_graph_publication_v3", {"p_publication_id": str(base["id"])}
            ).execute()
            raise
        result = {
            "version": publication.get("version"), "publication_id": publication.get("id"),
            "previous_publication_id": base.get("id"),
        }
        supabase_client.insert_event({
            "event_type": "graph_editor_saved", "entity_type": "graph_publication",
            "entity_id": str(publication.get("id") or ""), "persona_id": base.get("persona_id"),
            "payload": {**result, "actor": actor, "changes": changes, "draft_checksum": draft_checksum,
                        "runtime_checksum": runtime_checksum, "operation_count": len(reviewed["operations"])},
        }, source="services.graph_editor")
        _saved[replay_key] = result
        return result


def revert(*, persona_slug: str, to_publication_id: str, actor: str) -> dict[str, Any]:
    """Reactivate the publication that was active before the current one."""
    from services import supabase_client
    with _lock(persona_slug):
        current = active_publication(persona_slug)
        previous = previous_publication(persona_slug, str(current.get("id")))
        if not previous or str(previous.get("id")) != str(to_publication_id):
            raise GraphEditorConflict(f"revert_target_not_previous:{to_publication_id}")
        activation = supabase_client.get_client().rpc(
            "activate_graph_publication_v3", {"p_publication_id": str(previous["id"])}
        ).execute().data
        result = {"publication_id": previous["id"], "version": previous.get("version"),
                  "reverted_from_publication_id": current.get("id")}
        supabase_client.insert_event({
            "event_type": "graph_editor_reverted", "entity_type": "graph_publication",
            "entity_id": str(previous["id"]), "persona_id": current.get("persona_id"),
            "payload": {**result, "actor": actor, "activation": activation},
        }, source="services.graph_editor")
        return result

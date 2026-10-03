"""Graph editor: edit the active GraphBundle publication from the AKIA screen.

The SDR reads only the active ``graph_publications`` row. Every edit starts
from that publication: its ``document_json`` already carries the complete
bundle graph (nodes in bundle form, edges plus a compiler-derived ``primary``
flag), so the source bundle is rebuilt from it and checked by recompiling to
the same runtime checksum before any edit is accepted.

Edits are graph operations (the ``apply_operations`` vocabulary) restricted to
the SDR question surface in phase 1. See
akia/docs/architecture/engenharia-de-grafo.md.
"""
from __future__ import annotations

import copy
from typing import Any

from services import graph_bundle

BUNDLE_VERSION = "1.0"
EDITOR_SOURCE = "akia_graph_editor"


class GraphEditorError(ValueError):
    """An edit or base that the editor refuses, with a stable code."""


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


def bundle_from_publication(publication: dict[str, Any], *, purpose: str = "") -> dict[str, Any]:
    """Rebuild the source bundle of an active publication.

    ``primary`` on edges is derived by the compiler and is dropped; nodes are
    kept as published (including ``projection_node_id``).
    """
    document = publication.get("document_json") or publication.get("document") or {}
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


def verify_round_trip(publication: dict[str, Any]) -> dict[str, Any]:
    """The rebuilt bundle must compile to the active runtime checksum, unchanged."""
    document = publication.get("document_json") or publication.get("document") or {}
    bundle = bundle_from_publication(publication)
    plan = graph_bundle.build_publication_plan(bundle, current_document=document)
    changes = {key: plan.get(key) for key in ("node_changes", "edge_changes")}
    same_checksum = plan.get("runtime_checksum") == publication.get("checksum")
    return {
        "editable": bool(same_checksum and not plan.get("validation_errors")),
        "runtime_checksum": plan.get("runtime_checksum"),
        "active_checksum": publication.get("checksum"),
        "validation_errors": plan.get("validation_errors") or [],
        "changes": changes,
    }


# ── Operations (phase 1: SDR questions) ────────────────────────────────────

QUESTION_MODES = {"required", "optional", "disabled"}
MAX_QUESTION_CHARS = 500
_FIELDS_KEY = "data.qualification.fields"
_COMPLETION_KEYS = ("data.completion.required_fields", "data.booking.required_fields")
_QUESTION_KEY = "data.question"
_MODES_KEY = "data.conversation_policy.qualification.question_modes"
_ALLOWED_PATCH_KEYS = {_FIELDS_KEY, *_COMPLETION_KEYS, _QUESTION_KEY, _MODES_KEY}
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


def _check_patch(node: dict[str, Any], key: str, value: Any, *, persona_id: str) -> None:
    node_id = node["id"]
    if key not in _ALLOWED_PATCH_KEYS:
        raise GraphEditorError(f"operation_patch_key_not_editable:{node_id}:{key}")
    if key == _MODES_KEY:
        if node_id != persona_id:
            raise GraphEditorError(f"question_modes_only_on_persona:{node_id}")
        if not isinstance(value, dict) or any(
            not isinstance(field, str) or mode not in QUESTION_MODES for field, mode in value.items()
        ):
            raise GraphEditorError("question_modes_invalid")
    elif key == _QUESTION_KEY:
        if not _is_question_node(node):
            raise GraphEditorError(f"question_text_only_on_question_nodes:{node_id}")
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_QUESTION_CHARS:
            raise GraphEditorError(f"question_text_invalid:{node_id}")
    elif key == _FIELDS_KEY:
        if not isinstance(value, list) or not all(
            isinstance(field, dict) and isinstance(field.get("key"), str) and field["key"] for field in value
        ):
            raise GraphEditorError(f"qualification_fields_invalid:{node_id}")
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
        or not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS
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
    return normalize_disabled_questions(result)


def _question_modes(bundle: dict[str, Any]) -> dict[str, str]:
    data = _persona_node(bundle).get("data") or {}
    appointment = (data.get("appointment_policy") or {}).get("question_modes") or {}
    qualification = ((data.get("conversation_policy") or {}).get("qualification") or {}).get("question_modes") or {}
    return {**appointment, **qualification}


def normalize_disabled_questions(bundle: dict[str, Any]) -> dict[str, Any]:
    """Drop disabled keys from explicit completion/booking lists (order kept)."""
    disabled = {key for key, mode in _question_modes(bundle).items() if mode == "disabled"}
    if not disabled:
        return bundle
    for node in bundle["nodes"]:
        data = node.get("data") or {}
        for section in ("completion", "booking"):
            declared = data.get(section)
            if isinstance(declared, dict) and isinstance(declared.get("required_fields"), list):
                declared["required_fields"] = [key for key in declared["required_fields"] if key not in disabled]
    return bundle


# ── Read, plan, publish, revert ────────────────────────────────────────────

def _contracts(document: dict[str, Any]) -> list[dict[str, Any]]:
    node_by_id = document.get("node_by_id") or {node["id"]: node for node in document.get("nodes") or []}
    coordinates = document.get("coordinates") or {}
    result = []
    for anchor, contract in sorted((document.get("branch_contracts") or {}).items()):
        labels = contract.get("field_labels") or {}
        questions = contract.get("questions") or {}
        fields = []
        for field in contract.get("fields") or []:
            question = questions.get(field.get("question_node_id") or "") or {}
            fields.append({
                "key": field["key"],
                "label": labels.get(field["key"]) or field["key"],
                "question_node_id": field.get("question_node_id"),
                "text": question.get("text") or "",
                "required": bool(field.get("required")),
                "question_mode": field.get("question_mode") or ("required" if field.get("required") else "optional"),
                "scope": field.get("scope") or "branch",
                "depends_on": list(field.get("depends_on") or []),
            })
        path_ids = (coordinates.get(anchor) or {}).get("path_node_ids") or [anchor]
        result.append({
            "branch_node_id": anchor,
            "path": [{"node_id": node_id, "label": (node_by_id.get(node_id) or {}).get("title") or node_id} for node_id in path_ids],
            "fields": fields,
        })
    return result


def _persona_policy(bundle: dict[str, Any]) -> dict[str, Any]:
    data = _persona_node(bundle).get("data") or {}
    conversation = data.get("conversation_policy") or {}
    qualification = conversation.get("qualification") or {}
    return {
        "business_model": data.get("business_model"),
        "question_modes": _question_modes(bundle),
        "field_labels": conversation.get("field_labels") or (data.get("appointment_policy") or {}).get("field_labels") or {},
        "texts": {key: value for key, value in qualification.items() if isinstance(value, str)},
    }


def editor_view(publication: dict[str, Any]) -> dict[str, Any]:
    document = publication.get("document_json") or {}
    bundle = bundle_from_publication(publication)
    check = verify_round_trip(publication)
    changed = any((check["changes"].get("node_changes") or {}).get(kind) for kind in ("added", "changed", "removed"))
    from services import graph_compiler_v3  # local import keeps module import light
    published_with = publication.get("compiler_version") or document.get("compiler_version")
    return {
        "publication": {key: publication.get(key) for key in ("id", "version", "checksum", "activated_at", "compiler_version")},
        # Editable when the rebuilt bundle carries no content change; a newer
        # compiler alone changes the checksum and is surfaced, not hidden.
        "editable": not check["validation_errors"] and not changed,
        "blocked_reasons": check["validation_errors"],
        "compiler_upgrade": None if published_with == graph_compiler_v3.COMPILER_VERSION else {
            "from": published_with, "to": graph_compiler_v3.COMPILER_VERSION,
        },
        "persona_node_id": _persona_node(bundle)["id"],
        "bundle": {"nodes": bundle["nodes"], "edges": bundle["edges"]},
        "contracts": _contracts(document),
        "persona_policy": _persona_policy(bundle),
    }


def plan(publication: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Dry run: apply, normalize, compile. Nothing is written."""
    document = publication.get("document_json") or {}
    bundle = apply_operations(bundle_from_publication(publication), operations)
    result = graph_bundle.build_publication_plan(
        bundle, current_document=document, next_version=int(publication.get("version") or 0) + 1,
    )
    contracts: list[dict[str, Any]] = []
    if not result.get("validation_errors"):
        contracts = _contracts(graph_bundle.compile_bundle(bundle))
    return {**result, "contracts": contracts, "bundle": bundle}


class GraphEditorConflict(GraphEditorError):
    """The base is no longer the active publication, or the plan changed."""


_locks: dict[str, Any] = {}
_published: dict[str, dict[str, Any]] = {}


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


def publish(
    *, persona_slug: str, base_publication_id: str, operations: list[dict[str, Any]],
    draft_checksum: str, runtime_checksum: str, actor: str, idempotency_key: str,
) -> dict[str, Any]:
    """Stage and activate an edited bundle, only on top of the active base."""
    from services import graph_bundle_publisher, supabase_client
    with _lock(persona_slug):
        if idempotency_key and idempotency_key in _published:
            return _published[idempotency_key]
        base = active_publication(persona_slug)
        if str(base.get("id")) != str(base_publication_id):
            raise GraphEditorConflict(f"base_not_active:{base_publication_id}:{base.get('id')}")
        reviewed = plan(base, operations)
        if reviewed.get("validation_errors") or reviewed.get("publication_allowed") is not True:
            raise GraphEditorError("plan_blocked:" + ",".join(reviewed.get("validation_errors") or ["not_allowed"]))
        if reviewed.get("draft_checksum") != draft_checksum or reviewed.get("runtime_checksum") != runtime_checksum:
            raise GraphEditorConflict("plan_changed_since_review")
        bundle = reviewed["bundle"]
        staged = graph_bundle_publisher.stage_bundle(bundle, approved_draft_checksum=draft_checksum, actor=actor)
        publication = staged.get("publication") or {}
        try:
            graph_bundle_publisher.activate_staged_bundle(
                bundle, publication_id=str(publication["id"]), approved_draft_checksum=draft_checksum,
                approved_runtime_checksum=runtime_checksum, actor=actor,
            )
            now_active = active_publication(persona_slug)
            if now_active.get("checksum") != runtime_checksum:
                raise GraphEditorError("activation_not_confirmed")
        except Exception:
            supabase_client.get_client().rpc(
                "activate_graph_publication_v3", {"p_publication_id": str(base["id"])}
            ).execute()
            raise
        result = {
            "publication_id": publication.get("id"), "version": publication.get("version"),
            "checksum": runtime_checksum, "previous_publication_id": base.get("id"),
        }
        supabase_client.insert_event({
            "event_type": "graph_editor_published", "entity_type": "graph_publication",
            "entity_id": str(publication.get("id") or ""), "persona_id": base.get("persona_id"),
            "payload": {**result, "actor": actor, "draft_checksum": draft_checksum, "operations": operations},
        }, source="services.graph_editor")
        if idempotency_key:
            _published[idempotency_key] = result
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

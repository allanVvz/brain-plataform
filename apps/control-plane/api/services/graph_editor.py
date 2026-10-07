"""Graph editor planning and durable CAS publication orchestration."""
from __future__ import annotations
import hashlib
import json
from typing import Any
from services import graph_bundle, graph_compiler_v3
from services.graph_editor_model import (
    GraphEditorError, GraphEditorConflict, bundle_from_publication, verify_round_trip,
    journey_view, _document, _base_check, _persona_node,
)
from services.graph_editor_changes import (
    GraphEditorRejected, apply_operations, normalize_required_lists,
    expand_changes, readable_errors, _labels,
)

# ── Read, plan, save, revert ───────────────────────────────────────────────

def editor_view(publication: dict[str, Any]) -> dict[str, Any]:
    document = _document(publication)
    check = _base_check(publication)
    return {
        "publication": {key: publication.get(key) for key in ("id", "version", "checksum", "activated_at", "compiler_version")},
        "editable": check["editable"],
        "blocked_reasons": check["blocked_reasons"],
        "compiler_upgrade": check["compiler_upgrade"],
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


def active_publication(persona_slug: str) -> dict[str, Any]:
    from services import supabase_client
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise GraphEditorError("persona_not_found")
    value = _rpc("read_graph_editor_publication_v1", {"p_persona_id": str(persona["id"])})
    if not value:
        raise GraphEditorError("active_publication_not_found")
    row = value.get("publication") or {}
    document_text = value.get("document_text")
    if not isinstance(document_text, str):
        raise GraphEditorError("active_document_text_missing")
    document = json.loads(document_text)
    if str(row.get("persona_id")) != str(persona["id"]) or (document.get("persona") or {}).get("id") != str(persona["id"]):
        raise GraphEditorError("active_publication_scope_mismatch")
    if row.get("checksum") != document.get("checksum"):
        raise GraphEditorError("active_publication_checksum_mismatch")
    return {**row, "document_json": document}


def _rpc(name: str, params: dict[str, Any]) -> Any:
    from services import supabase_client
    try:
        return supabase_client.get_client().rpc(name, params).execute().data
    except Exception as exc:
        if str(getattr(exc, "code", "")) == "40001":
            message = str(getattr(exc, "message", exc))
            raise GraphEditorConflict(message.removeprefix("graph_editor_")) from exc
        raise


def _persona_id(persona_slug: str) -> str:
    from services import supabase_client
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise GraphEditorError("persona_not_found")
    return str(persona["id"])


def _request_params(persona_id: str, actor: str, key: str, operation: str,
                    base: str | None, content: Any) -> dict[str, Any]:
    if not actor or not key or len(key) > 128:
        raise GraphEditorError("invalid_idempotency_request")
    canonical = json.dumps({"operation": operation, "base": base, "content": content},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {"p_persona_id": persona_id, "p_actor": actor, "p_idempotency_key": key,
            "p_operation": operation, "p_base_publication_id": base,
            "p_request_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()}


def previous_publication(persona_slug: str, active_id: str) -> dict[str, Any] | None:
    """Use activation lineage; legacy timestamps cannot prove a predecessor."""
    return _rpc("graph_editor_previous_v1", {
        "p_persona_id": _persona_id(persona_slug), "p_active_publication_id": active_id,
    })


class GraphEditorOutcomeUnknown(GraphEditorError):
    """Retry the identical request/key to reconcile a possibly committed RPC."""


def _commit(params: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _rpc("commit_graph_editor_v1", params)
    except GraphEditorConflict:
        raise
    except Exception as exc:
        # Never compensate with an unconditional activation: another writer
        # might already have published. A durable receipt resolves a lost reply.
        raise GraphEditorOutcomeUnknown("publication_outcome_unknown_retry_same_key") from exc
    if not isinstance(result, dict) or not result.get("publication_id"):
        raise GraphEditorOutcomeUnknown("publication_outcome_unknown_retry_same_key")
    return result


def save(
    *, persona_slug: str, base_publication_id: str, changes: list[dict[str, Any]],
    actor: str, idempotency_key: str,
) -> dict[str, Any]:
    """Stage an immutable candidate, then atomically CAS + persist its receipt."""
    from services import graph_bundle_publisher
    params = _request_params(_persona_id(persona_slug), actor, idempotency_key,
                             "save", base_publication_id, changes)
    replay = _rpc("graph_editor_receipt_v1", params)
    if replay is not None:
        return replay
    base = active_publication(persona_slug)
    if str(base.get("id")) != str(base_publication_id):
        raise GraphEditorConflict(f"base_not_active:{base_publication_id}:{base.get('id')}")
    reviewed = plan_changes(base, changes)
    try:
        staged = graph_bundle_publisher.stage_bundle(
            reviewed["bundle"], approved_draft_checksum=reviewed["draft_checksum"], actor=actor,
        )
    except graph_bundle_publisher.GraphBundlePublishError as exc:
        if str(exc) == "bundle_base_not_active":
            raise GraphEditorConflict("base_not_active") from exc
        raise
    publication = staged.get("publication") or {}
    return _commit({**params, "p_publication_id": str(publication["id"]),
                    "p_runtime_checksum": reviewed["runtime_checksum"], "p_audit": {
                        "changes": changes, "draft_checksum": reviewed["draft_checksum"],
                        "runtime_checksum": reviewed["runtime_checksum"],
                        "operation_count": len(reviewed["operations"]),
                    }})


def revert(*, persona_slug: str, to_publication_id: str, actor: str,
           base_publication_id: str, idempotency_key: str) -> dict[str, Any]:
    """CAS the recorded predecessor with a durable caller-supplied key."""
    persona_id = _persona_id(persona_slug)
    params = _request_params(persona_id, actor, idempotency_key, "revert",
                             base_publication_id, {"to_publication_id": to_publication_id})
    replay = _rpc("graph_editor_receipt_v1", params)
    if replay is not None:
        return replay
    current = active_publication(persona_slug)
    if str(current["id"]) != base_publication_id:
        raise GraphEditorConflict("base_not_active")
    previous = previous_publication(persona_slug, base_publication_id)
    if not previous or str(previous.get("id")) != str(to_publication_id):
        raise GraphEditorConflict(f"revert_target_not_previous:{to_publication_id}")
    return _commit({**params, "p_publication_id": str(previous["id"]),
                    "p_runtime_checksum": previous["checksum"], "p_audit": {}})

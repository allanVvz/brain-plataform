"""Gated GraphBundle staging and activation.

Staging persists the reviewed immutable document and its derived projections.
It deliberately never mutates ``knowledge_nodes`` or ``knowledge_edges``.
"""
from __future__ import annotations

from typing import Any, Callable

from services import graph_bundle, graph_compiler_v3, supabase_client


class GraphBundlePublishError(RuntimeError):
    pass


def _require_reviewed_plan(
    bundle: dict[str, Any], approved_draft_checksum: str,
    reviewed_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    plan = reviewed_plan or graph_bundle.build_publication_plan(bundle)
    errors = plan.get("validation_errors") or []
    if errors:
        raise GraphBundlePublishError("plan_blocked:" + ",".join(errors))
    if plan.get("publication_allowed") is not True:
        raise GraphBundlePublishError("publication_not_authorized")
    if plan.get("draft_checksum") != approved_draft_checksum:
        raise GraphBundlePublishError(
            f"approved_draft_checksum_mismatch:{approved_draft_checksum}:"
            f"{plan.get('draft_checksum')}"
        )
    return plan


def _require_persona_scope(normalized: dict[str, Any]) -> tuple[str, str]:
    persona_id = normalized["persona"]["id"]
    persona_slug = normalized["persona"]["slug"]
    persona = supabase_client.get_persona(persona_slug)
    if not persona or str(persona.get("id") or "") != persona_id:
        raise GraphBundlePublishError("persona_scope_mismatch")
    return persona_id, persona_slug


def _require_reviewed_document(
    plan: dict[str, Any], normalized: dict[str, Any],
) -> dict[str, Any]:
    document = plan.get("candidate_document")
    if not isinstance(document, dict):
        document = graph_bundle.compile_bundle(normalized)
    if document["checksum"] != plan["runtime_checksum"]:
        raise GraphBundlePublishError(
            f"materialized_runtime_checksum_mismatch:{document['checksum']}:"
            f"{plan['runtime_checksum']}"
        )
    return document


def stage_bundle(
    bundle: dict[str, Any],
    *,
    approved_draft_checksum: str,
    actor: str,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
    reviewed_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = _require_reviewed_plan(bundle, approved_draft_checksum, reviewed_plan)
    candidate_bundle = plan.get("candidate_bundle") or bundle
    normalized = graph_bundle.normalize_bundle(candidate_bundle)
    persona_id, persona_slug = _require_persona_scope(normalized)
    document = _require_reviewed_document(plan, normalized)

    staged = graph_compiler_v3.compile_persona_publication(
        persona_slug,
        activate=False,
        embedder=embedder,
        embedding_profile=normalized["metadata"]["embedding_profile"],
        precompiled_document=document,
    )
    publication = staged.get("publication") or {}
    if publication.get("checksum") != plan["runtime_checksum"]:
        raise GraphBundlePublishError("staged_publication_checksum_mismatch")
    supabase_client.insert_event({
        "event_type": "graph_bundle_publication_staged",
        "entity_type": "graph_publication",
        "entity_id": str(publication.get("id") or ""),
        "persona_id": persona_id,
        "payload": {
            "persona_slug": persona_slug,
            "draft_checksum": plan["draft_checksum"],
            "runtime_checksum": plan["runtime_checksum"],
            "publication_id": publication.get("id"),
            "version": publication.get("version"),
            "actor": actor,
        },
    }, source="services.graph_bundle_publisher")
    return {"plan": plan, **staged}


def _require_staged_publication(
    *, publication_id: str, persona_id: str, runtime_checksum: str,
) -> dict[str, Any]:
    publication = (
        supabase_client.get_client().table("graph_publications").select("*")
        .eq("id", publication_id).maybe_single().execute().data
    )
    if not publication:
        raise GraphBundlePublishError("staged_publication_not_found")
    if str(publication.get("persona_id") or "") != persona_id:
        raise GraphBundlePublishError("staged_publication_persona_scope_mismatch")
    if publication.get("status") not in {"compiled", "active"}:
        raise GraphBundlePublishError(
            f"staged_publication_not_activatable:{publication.get('status')}"
        )
    if publication.get("checksum") != runtime_checksum:
        raise GraphBundlePublishError("publication_checksum_changed_before_activation")
    return publication


def activate_staged_bundle(
    bundle: dict[str, Any],
    *,
    publication_id: str,
    approved_draft_checksum: str,
    approved_runtime_checksum: str,
    actor: str,
) -> dict[str, Any]:
    plan = graph_bundle.build_publication_plan(bundle)
    if plan.get("draft_checksum") != approved_draft_checksum:
        raise GraphBundlePublishError("activation_draft_checksum_mismatch")
    if plan.get("runtime_checksum") != approved_runtime_checksum:
        raise GraphBundlePublishError("activation_runtime_checksum_mismatch")

    # Activation must be scoped just as tightly as staging.  The publication
    # id comes from a previous stage, but it is still an external identifier at
    # this boundary; never let a bundle for persona A activate a staged
    # publication belonging to persona B.
    normalized = graph_bundle.normalize_bundle(bundle)
    persona_id, _persona_slug = _require_persona_scope(normalized)
    client = supabase_client.get_client()
    publication = _require_staged_publication(
        publication_id=publication_id, persona_id=persona_id,
        runtime_checksum=approved_runtime_checksum,
    )
    activation = client.rpc(
        "activate_graph_publication_v3", {"p_publication_id": publication_id}
    ).execute().data
    supabase_client.insert_event({
        "event_type": "graph_bundle_publication_activated",
        "entity_type": "graph_publication",
        "entity_id": publication_id,
        "persona_id": publication.get("persona_id"),
        "payload": {
            "draft_checksum": approved_draft_checksum,
            "runtime_checksum": approved_runtime_checksum,
            "publication_id": publication_id,
            "version": publication.get("version"),
            "actor": actor,
        },
    }, source="services.graph_bundle_publisher")
    return {"publication": publication, "activation": activation}


def activate_reviewed_publication(
    *,
    publication_id: str,
    persona_id: str,
    approved_runtime_checksum: str,
    draft_ref: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Activate the checkpointed publication without compiling authoring data."""
    try:
        result = supabase_client.get_client().rpc(
            "activate_graph_bundle_draft_publication",
            {
                "p_draft_ref": draft_ref,
                "p_persona_id": persona_id,
                "p_publication_id": publication_id,
                "p_runtime_checksum": approved_runtime_checksum,
                "p_idempotency_key": idempotency_key,
            },
        ).execute().data
    except Exception as exc:
        raise GraphBundlePublishError(str(exc)) from exc
    return dict(result or {})


def checkpoint_reviewed_publication(
    *,
    draft: dict[str, Any],
    publication_id: str,
    runtime_checksum: str,
    idempotency_key: str,
) -> dict[str, Any]:
    try:
        result = supabase_client.get_client().rpc(
            "checkpoint_graph_bundle_draft_publication",
            {
                "p_draft_ref": draft["draft_ref"],
                "p_persona_id": draft["persona_id"],
                "p_publication_id": publication_id,
                "p_runtime_checksum": runtime_checksum,
                "p_expected_active_publication_id": draft["base_publication_id"],
                "p_expected_active_checksum": draft["base_runtime_checksum"],
                "p_draft_revision": draft["revision"],
                "p_draft_checksum": draft["draft_checksum"],
                "p_idempotency_key": idempotency_key,
            },
        ).execute().data
    except Exception as exc:
        raise GraphBundlePublishError(str(exc)) from exc
    return dict(result or {})


def get_publish_checkpoint(
    draft_ref: str, idempotency_key: str,
) -> dict[str, Any] | None:
    row = (
        supabase_client.get_client().table("system_events").select("payload")
        .eq("entity_type", "graph_bundle_draft_publication")
        .eq("entity_id", draft_ref)
        .eq("payload->>idempotency_key", idempotency_key)
        .order("created_at", desc=True).limit(1).execute().data or []
    )
    return dict(row[0].get("payload") or {}) if row else None

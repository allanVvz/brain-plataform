"""Gated GraphBundle materialization, staging and activation.

The source graph is materialized first, then recompiled from the canonical
knowledge tables. The staged runtime checksum must equal the reviewed plan.
Activation is a separate function with both approved checksums as CAS gates.
"""
from __future__ import annotations

from typing import Any, Callable

from services import graph_bundle, graph_compiler_v3, supabase_client


class GraphBundlePublishError(RuntimeError):
    pass


def _active_edge(row: dict[str, Any]) -> bool:
    return (row.get("metadata") or {}).get("active", True) is not False


def _preflight_source_scope(
    normalized: dict[str, Any],
    node_rows: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    base_document: dict[str, Any] | None = None,
) -> None:
    base_document = base_document or {}
    retired = {row.get("id") for row in normalized.get("metadata", {}).get("retired_nodes", []) if isinstance(row, dict)}
    base_nodes = {node["id"]: node for node in base_document.get("nodes", [])}
    permitted_retired_ids = {str(base_nodes[key].get("projection_node_id")) for key in retired if key in base_nodes}
    declared_removed_edges = {row.get("id") for row in (normalized.get("metadata", {}).get("visual_media_reconciliation") or {}).get("soft_disabled_edges", []) if isinstance(row, dict)}
    permitted_removed_edges = {
        (str(base_nodes[e["source"]].get("projection_node_id")), str(base_nodes[e["target"]].get("projection_node_id")), e["relation_type"])
        for e in base_document.get("edges", [])
        if (e.get("id") in declared_removed_edges or e["source"] in retired or e["target"] in retired)
        and e["source"] in base_nodes and e["target"] in base_nodes
    }
    desired_nodes = {
        (node["node_type"], node["slug"]) for node in normalized["nodes"]
    }
    desired_projection_ids = {
        str(node.get("projection_node_id") or "") for node in normalized["nodes"]
    }
    has_authored_persona = any(
        node_type == "persona" and slug != "self"
        for node_type, slug in desired_nodes
    )
    existing_nodes = {
        (str(row.get("node_type") or ""), str(row.get("slug") or ""))
        for row in node_rows
        if str(row.get("status") or "").lower() in graph_compiler_v3.PUBLISHED_STATUSES
        and str(row.get("id") or "") not in desired_projection_ids
        and str(row.get("id") or "") not in permitted_retired_ids
        and not (
            has_authored_persona
            and str(row.get("node_type") or "").lower() == "persona"
            and str(row.get("slug") or "").lower() == "self"
        )
    }
    unexpected_nodes = sorted(existing_nodes - desired_nodes)
    if unexpected_nodes:
        raise GraphBundlePublishError(
            "source_graph_has_unplanned_nodes:" + ",".join(
                f"{node_type}:{slug}" for node_type, slug in unexpected_nodes
            )
        )

    projection_by_stable = {
        node["id"]: str(node.get("projection_node_id") or "")
        for node in normalized["nodes"]
    }
    ignored_legacy_persona_projection_ids = {
        str(row.get("id"))
        for row in node_rows
        if has_authored_persona
        and str(row.get("node_type") or "").lower() == "persona"
        and str(row.get("slug") or "").lower() == "self"
    }
    desired_edges = {
        (
            projection_by_stable.get(edge["source"], ""),
            projection_by_stable.get(edge["target"], ""),
            edge["relation_type"],
        )
        for edge in normalized["edges"]
    }
    existing_edges = {
        (
            str(row.get("source_node_id") or ""),
            str(row.get("target_node_id") or ""),
            str(row.get("relation_type") or ""),
        )
        for row in edge_rows
        if _active_edge(row)
        and str(row.get("source_node_id")) not in ignored_legacy_persona_projection_ids
        and str(row.get("target_node_id")) not in ignored_legacy_persona_projection_ids
    }
    unexpected_edges = sorted(existing_edges - desired_edges - permitted_removed_edges)
    if unexpected_edges:
        raise GraphBundlePublishError(
            "source_graph_has_unplanned_edges:" + ",".join(
                ":".join(edge) for edge in unexpected_edges
            )
        )


def stage_bundle(
    bundle: dict[str, Any],
    *,
    approved_draft_checksum: str,
    actor: str,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
) -> dict[str, Any]:
    plan = graph_bundle.build_publication_plan(bundle)
    if plan.get("validation_errors"):
        raise GraphBundlePublishError(
            "plan_blocked:" + ",".join(plan["validation_errors"])
        )
    if plan.get("publication_allowed") is not True:
        raise GraphBundlePublishError("publication_not_allowed_by_bundle")
    if plan.get("draft_checksum") != approved_draft_checksum:
        raise GraphBundlePublishError(
            f"approved_draft_checksum_mismatch:{approved_draft_checksum}:"
            f"{plan.get('draft_checksum')}"
        )

    normalized = graph_bundle.normalize_bundle(bundle)
    persona_id = normalized["persona"]["id"]
    persona_slug = normalized["persona"]["slug"]
    persona = supabase_client.get_persona(persona_slug)
    if not persona or str(persona.get("id") or "") != persona_id:
        raise GraphBundlePublishError("persona_scope_mismatch")

    # Editor candidates compile their immutable reviewed inputs. Published
    # source nodes/edges are replaced only by commit_graph_editor_v1.
    from services import graph_editor
    try:
        base_publication = graph_editor.active_publication(persona_slug)
    except graph_editor.GraphEditorError as exc:
        if str(exc) != "active_publication_not_found":
            raise
        base_publication = None
    active_base_id = str(base_publication["id"]) if base_publication else None
    reviewed_base_id = (normalized.get("metadata", {}).get("baseline_publication") or {}).get("publication_id")
    reviewed_base_id = str(reviewed_base_id) if reviewed_base_id else None
    if reviewed_base_id != active_base_id:
        raise GraphBundlePublishError("bundle_base_not_active")
    reviewed_checksum = (normalized.get("metadata", {}).get("baseline_publication") or {}).get("checksum")
    if reviewed_checksum and reviewed_checksum != (base_publication or {}).get("checksum"):
        raise GraphBundlePublishError("bundle_base_checksum_mismatch")
    current_nodes, current_edges = supabase_client.list_all_knowledge_graph(
        persona_id=persona_id, limit_nodes=10000
    )

    _preflight_source_scope(normalized, current_nodes, current_edges, (base_publication or {}).get("document_json"))
    _, node_rows, edge_rows, profile = graph_bundle._compiler_inputs(normalized)
    staged = graph_compiler_v3.compile_persona_publication(
        persona_slug, activate=False, embedder=embedder, embedding_profile=profile,
        source_rows=(node_rows, edge_rows),
    )
    if (staged.get("publication") or {}).get("checksum") != plan["runtime_checksum"]:
        raise GraphBundlePublishError("staged_publication_checksum_mismatch")
    return {"plan": plan, **staged, "base_publication_id": active_base_id}

def activate_staged_bundle(
    bundle: dict[str, Any],
    *,
    publication_id: str,
    approved_draft_checksum: str,
    approved_runtime_checksum: str,
    actor: str,
    expected_base_publication_id: str | None,
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
    persona_id = normalized["persona"]["id"]
    persona_slug = normalized["persona"]["slug"]
    persona = supabase_client.get_persona(persona_slug)
    if not persona or str(persona.get("id") or "") != persona_id:
        raise GraphBundlePublishError("persona_scope_mismatch")

    client = supabase_client.get_client()
    publication = (
        client.table("graph_publications").select("*")
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
    if publication.get("checksum") != approved_runtime_checksum:
        raise GraphBundlePublishError("publication_checksum_changed_before_activation")
    if publication.get("status") == "active" and str(supabase_client.get_active_graph_publication(persona_id).get("id")) == publication_id:
        return {"publication": publication, "activation": {"status": "active", "publication_id": publication_id}}
    from services import graph_editor
    import hashlib
    params = graph_editor._request_params(
        persona_id, actor,
        "bundle:" + hashlib.sha256(f"{actor}:{expected_base_publication_id}:{approved_runtime_checksum}".encode()).hexdigest(),
        "publish", expected_base_publication_id, {"checksum": approved_runtime_checksum,
            "draft_checksum": approved_draft_checksum},
    )
    activation = client.rpc("commit_graph_editor_v1", {
        **params, "p_publication_id": publication_id,
        "p_runtime_checksum": approved_runtime_checksum,
        "p_audit": {"writer": "graph_bundle_publisher", "actor": actor,
                    "draft_checksum": approved_draft_checksum},
    }).execute().data
    return {"publication": publication, "activation": activation}

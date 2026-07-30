"""Atomic-ish canonical Graph JSON publication over existing system_events.

The published event is deliberately written *after* mandatory projections
complete.  Projection writes are idempotent, so a failed attempt can safely be
retried without advancing the canonical version.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from schemas.graph_json_v2 import Edge, GraphJson, Node
from services import (
    graph_json_importer,
    graph_json_v2_store,
    graph_json_v2_validator,
    graph_markdown,
    supabase_client,
)


class VersionConflict(RuntimeError):
    def __init__(self, *, expected: int, current: int):
        super().__init__(f"Graph version conflict: expected {expected}, current {current}")
        self.expected = expected
        self.current = current


class GraphValidationError(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__("Canonical graph validation failed")
        self.errors = errors


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _scope_key(persona_slug: str, brand_slug: str | None) -> str:
    return f"{persona_slug}:{brand_slug or 'default'}"


def _lock_for(scope: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(scope, threading.RLock())


def _audit(
    event_type: str,
    *,
    persona_slug: str,
    brand_slug: str | None,
    version: int,
    source: str,
    idempotency_key: str | None,
    payload: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    try:
        persona = supabase_client.get_persona(persona_slug) or {}
        supabase_client.insert_event(
            {
                "event_type": event_type,
                "entity_type": "graph_document",
                "entity_id": f"{_scope_key(persona_slug, brand_slug)}:v{version}",
                "persona_id": persona.get("id"),
                "payload": {
                    "persona_slug": persona_slug,
                    "brand_slug": brand_slug,
                    "version": version,
                    "idempotency_key": idempotency_key,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    **(payload or {}),
                },
                "level": level,
                "source": source,
            },
            source=source,
        )
    except Exception:
        # The final graph_document_published event is mandatory and is written
        # by save_version. Auxiliary attempt/failure telemetry must not mask the
        # original projection error.
        return


def _load_current(persona_slug: str, brand_slug: str | None):
    try:
        return graph_json_v2_store.load_current(persona_slug, brand_slug)
    except TypeError:  # compatibility with older test doubles/callers
        return graph_json_v2_store.load_current(persona_slug)


def _idempotent_result(
    persona_slug: str,
    brand_slug: str | None,
    idempotency_key: str | None,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    for row in supabase_client.list_system_events(
        entity_type="graph_document",
        event_types=["graph_document_published"],
        limit=500,
    ):
        payload = row.get("payload") or {}
        if payload.get("persona_slug") != persona_slug:
            continue
        if (payload.get("brand_slug") or None) != (brand_slug or None):
            continue
        if payload.get("idempotency_key") != idempotency_key:
            continue
        projections = payload.get("projections") or {}
        return {
            **projections,
            "ok": True,
            "idempotent_replay": True,
            "id": row.get("entity_id"),
            "persona_slug": persona_slug,
            "brand_slug": brand_slug,
            "version": int(payload.get("version") or 0),
            "checksum": payload.get("checksum"),
            "projections": projections,
        }
    return None


def publish(
    *,
    graph: GraphJson,
    persona_slug: str,
    brand_slug: str | None,
    source: str,
    note: str | None = None,
    published_by: str | None = None,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
    session_id: str | None = None,
    current_version_override: int | None = None,
) -> dict[str, Any]:
    try:
        graph = graph_markdown.canonicalize_graph(graph)
    except graph_markdown.GraphMarkdownError as exc:
        raise GraphValidationError(exc.errors) from exc
    scope = _scope_key(persona_slug, brand_slug)
    with _lock_for(scope):
        replay = _idempotent_result(persona_slug, brand_slug, idempotency_key)
        if replay:
            return replay

        current = None if current_version_override is not None else _load_current(persona_slug, brand_slug)
        current_version = (
            int(current_version_override)
            if current_version_override is not None
            else (int(current[0]) if current else 0)
        )
        if expected_version is not None and int(expected_version) != current_version:
            raise VersionConflict(expected=int(expected_version), current=current_version)

        next_version = current_version + 1
        checksum = graph_json_v2_store.checksum_graph(graph)
        _audit(
            "graph_document_publish_attempted",
            persona_slug=persona_slug,
            brand_slug=brand_slug,
            version=next_version,
            source=source,
            idempotency_key=idempotency_key,
            payload={"checksum": checksum},
        )
        try:
            projections = graph_json_importer.import_graph_json(
                graph_json=graph,
                source=source,
                session_id=session_id,
                version=next_version,
                graph_checksum=checksum,
            )
            if not projections or projections.get("ok") is not True:
                raise RuntimeError(
                    str((projections or {}).get("errors") or (projections or {}).get("reindex_error") or "projection failed")
                )
            persisted_checksum = graph_json_v2_store.save_version(
                persona_slug,
                next_version,
                graph,
                brand_slug=brand_slug,
                source=source,
                note=note,
                published_by=published_by,
                idempotency_key=idempotency_key,
                projections=projections,
            )
        except Exception as exc:
            try:
                _audit(
                    "graph_document_publish_failed",
                    persona_slug=persona_slug,
                    brand_slug=brand_slug,
                    version=next_version,
                    source=source,
                    idempotency_key=idempotency_key,
                    payload={"checksum": checksum, "error": str(exc)[:1000]},
                    level="error",
                )
            finally:
                raise

        return {
            "ok": True,
            "idempotent_replay": False,
            "id": f"{scope}:v{next_version}",
            "persona_slug": persona_slug,
            "brand_slug": brand_slug,
            "version": next_version,
            "checksum": persisted_checksum,
            "projections": projections,
            "reindex_ok": True,
            "nodes_imported": projections.get("nodes_imported"),
            "edges_imported": projections.get("edges_imported"),
            "reindex_error": None,
        }


def sync(
    *,
    persona_slug: str,
    brand_slug: str | None,
    source: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    current = _load_current(persona_slug, brand_slug)
    if current is None:
        raise LookupError("No published graph document available")
    version, graph = current
    is_valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    if not is_valid:
        raise GraphValidationError(errors)
    try:
        event = graph_json_v2_store.latest_event(persona_slug, brand_slug) or {}
    except Exception:
        event = {}
    checksum = ((event.get("payload") or {}).get("checksum")) or graph_json_v2_store.checksum_graph(graph)
    projections = graph_json_importer.import_graph_json(
        graph_json=graph,
        source=source,
        version=version,
        graph_checksum=checksum,
    )
    if not projections or projections.get("ok") is not True:
        raise RuntimeError(str((projections or {}).get("errors") or "projection sync failed"))
    _audit(
        "graph_document_synced",
        persona_slug=persona_slug,
        brand_slug=brand_slug,
        version=version,
        source=source,
        idempotency_key=idempotency_key,
        payload={"checksum": checksum, "projections": projections},
    )
    return {
        "ok": True,
        "persona_slug": persona_slug,
        "brand_slug": brand_slug,
        "version": version,
        "checksum": checksum,
        "projections": projections,
    }


def apply_sofia_patch(graph: GraphJson, patch: dict[str, Any]) -> GraphJson:
    """Translate Sofia's compatibility patch into a complete canonical document."""
    next_graph = GraphJson.model_validate(graph.model_dump())
    nodes = {node.id: node for node in next_graph.nodes}

    def refs() -> dict[str, str]:
        out: dict[str, str] = {}
        for node in nodes.values():
            out[f"id:{node.id}"] = node.id
            out[f"slug:{node.slug.lower()}"] = node.id
            knowledge_id = str((node.data or {}).get("knowledge_node_id") or "")
            if knowledge_id:
                out[f"id:{knowledge_id}"] = node.id
        return out

    ref_map = refs()
    for raw in patch.get("nodes_upsert") or []:
        node_type = str(raw.get("node_type") or "").strip().lower()
        slug = str(raw.get("slug") or "").strip().lower()
        if not node_type or not slug:
            raise ValueError("Sofia nodes_upsert requires node_type and slug")
        existing_id = next(
            (
                node.id
                for node in nodes.values()
                if node.node_type == node_type and node.slug.lower() == slug
            ),
            None,
        )
        node_id = existing_id or f"node:{node_type}:{slug}"
        existing = nodes.get(node_id)
        nodes[node_id] = Node(
            id=node_id,
            node_type=node_type,
            slug=slug,
            label=str(raw.get("title") or (existing.label if existing else slug)),
            parent_id=existing.parent_id if existing else None,
            data={
                **((existing.data if existing else {}) or {}),
                **(raw.get("metadata") or {}),
                "summary": raw.get("summary") or ((existing.data if existing else {}) or {}).get("summary"),
                "status": raw.get("status") or ((existing.data if existing else {}) or {}).get("status") or "pending_validation",
                "tags": raw.get("tags") or ((existing.data if existing else {}) or {}).get("tags") or [node_type],
                "source": (raw.get("metadata") or {}).get("source") or "sofia_graph",
            },
        )
        ref_map = refs()

    remove_ids: set[str] = set()
    for raw in patch.get("nodes_delete") or []:
        value = raw if isinstance(raw, str) else raw.get("id") or raw.get("node_id") or raw.get("slug")
        key = str(value or "")
        resolved = ref_map.get(key) or ref_map.get(f"id:{key}") or ref_map.get(f"slug:{key.lower()}")
        if resolved:
            node = nodes.get(resolved)
            if node and node.node_type in {"persona", "embedded", "gallery"}:
                raise ValueError(f"Protected node cannot be removed: {node.node_type}")
            remove_ids.add(resolved)
    for node_id in remove_ids:
        nodes.pop(node_id, None)

    edges = {
        edge.id: edge
        for edge in next_graph.edges
        if edge.source in nodes and edge.target in nodes
    }
    for raw in patch.get("edges_delete") or []:
        value = raw if isinstance(raw, str) else raw.get("id") or raw.get("edge_id")
        if value:
            edges.pop(str(value), None)

    ref_map = refs()
    for raw in patch.get("edges_upsert") or []:
        source_ref = str(raw.get("source_ref") or raw.get("source") or "")
        target_ref = str(raw.get("target_ref") or raw.get("target") or "")
        source = ref_map.get(source_ref) or ref_map.get(f"id:{source_ref}") or ref_map.get(f"slug:{source_ref.lower()}")
        target = ref_map.get(target_ref) or ref_map.get(f"id:{target_ref}") or ref_map.get(f"slug:{target_ref.lower()}")
        if not source or not target:
            raise ValueError(f"Sofia edge reference not found: {source_ref} -> {target_ref}")
        relation = str(raw.get("relation_type") or "contains").strip().lower()
        primary = (raw.get("metadata") or {}).get("primary_tree") is not False
        existing_id = next(
            (
                edge.id
                for edge in edges.values()
                if edge.source == source and edge.target == target and edge.relation == relation
            ),
            None,
        )
        edge_id = existing_id or f"edge:sofia:{uuid.uuid4().hex}"
        edges[edge_id] = Edge(
            id=edge_id,
            source=source,
            target=target,
            relation=relation,
            primary_tree=primary,
            metadata={**(raw.get("metadata") or {}), "created_from": "sofia_graph"},
        )
        if primary and target in nodes:
            nodes[target].parent_id = source

    next_graph.nodes = list(nodes.values())
    next_graph.edges = list(edges.values())
    return next_graph

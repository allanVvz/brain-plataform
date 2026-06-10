from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from schemas.graph_json_v2 import GraphJson
from services import graph_json_importer, graph_json_v2_store, graph_json_v2_validator
from services import auth_service, supabase_client

router = APIRouter(prefix="/graph-documents", tags=["graph-documents"])


class PublishGraphDocumentBody(BaseModel):
    persona_slug: str = Field(..., min_length=1)
    brand_slug: Optional[str] = None
    graph_json: dict
    source: str = "import_v1_to_v2"
    note: Optional[str] = None


class ApplyPatchBody(BaseModel):
    persona_slug: str = Field(..., min_length=1)
    graph_json: dict
    source: str = "apply_patch"
    note: Optional[str] = None


class ImportGraphDocumentBody(BaseModel):
    persona_slug: str = Field(..., min_length=1)
    graph_json: dict
    source: str = "graph_documents.import_json"
    session_id: Optional[str] = None
    note: Optional[str] = None


class RollbackBody(BaseModel):
    persona_slug: str = Field(..., min_length=1)
    version: int = Field(..., ge=1)
    note: Optional[str] = None


class ReindexBody(BaseModel):
    persona_slug: str = Field(..., min_length=1)
    note: Optional[str] = None


def _latest_event(persona_slug: str, brand_slug: Optional[str]) -> Optional[dict]:
    rows = supabase_client.list_system_events(
        entity_type="graph_document",
        event_types=["graph_document_published"],
        limit=200,
    )
    filtered: list[dict] = []
    for row in rows:
        payload = row.get("payload") or {}
        if payload.get("persona_slug") != persona_slug:
            continue
        if (payload.get("brand_slug") or None) != (brand_slug or None):
            continue
        filtered.append(row)
    if not filtered:
        return None
    filtered.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return filtered[0]


def _validate_graph_json_or_422(graph_json: dict) -> GraphJson:
    try:
        graph = GraphJson.model_validate(graph_json)
    except Exception as exc:
        raise HTTPException(422, f"Invalid graph_json payload: {exc}") from exc

    is_valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    if not is_valid:
        raise HTTPException(422, {"code": "GRAPH_VALIDATION_FAILED", "errors": errors})
    return graph


@router.get("/current")
def graph_document_current(
    request: Request,
    persona_slug: str = Query(...),
    brand_slug: Optional[str] = Query(None),
):
    auth_service.current_user(request)
    evt = _latest_event(persona_slug, brand_slug)
    if not evt:
        return {
            "id": None,
            "persona_slug": persona_slug,
            "brand_slug": brand_slug,
            "version": 0,
            "graph_json": {},
            "published_at": None,
            "source": None,
            "note": None,
        }
    payload = evt.get("payload") or {}
    return {
        "id": evt.get("entity_id"),
        "persona_slug": payload.get("persona_slug"),
        "brand_slug": payload.get("brand_slug"),
        "version": payload.get("version", 1),
        "graph_json": payload.get("graph_json") or {},
        "published_at": evt.get("created_at"),
        "source": payload.get("source"),
        "note": payload.get("note"),
    }


@router.get("/versions")
def graph_document_versions(
    request: Request,
    persona_slug: str = Query(...),
    brand_slug: Optional[str] = Query(None),
):
    auth_service.current_user(request)
    rows = supabase_client.list_system_events(
        entity_type="graph_document",
        event_types=["graph_document_published"],
        limit=500,
    )
    out: list[dict] = []
    for row in rows:
        payload = row.get("payload") or {}
        if payload.get("persona_slug") != persona_slug:
            continue
        if (payload.get("brand_slug") or None) != (brand_slug or None):
            continue
        out.append(
            {
                "id": row.get("entity_id"),
                "version": payload.get("version", 1),
                "published_at": row.get("created_at"),
                "source": payload.get("source"),
                "note": payload.get("note"),
            }
        )
    out.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return {"persona_slug": persona_slug, "brand_slug": brand_slug, "versions": out}


@router.post("/publish")
def graph_document_publish(body: PublishGraphDocumentBody, request: Request):
    auth_service.current_user(request)
    graph = _validate_graph_json_or_422(body.graph_json)
    current = _latest_event(body.persona_slug, body.brand_slug)
    current_payload = (current or {}).get("payload") or {}
    next_version = int(current_payload.get("version") or 0) + 1
    doc_id = f"{body.persona_slug}:{body.brand_slug or 'default'}:v{next_version}"
    payload = {
        "persona_slug": body.persona_slug,
        "brand_slug": body.brand_slug,
        "version": next_version,
        "graph_json": body.graph_json,
        "source": body.source,
        "note": body.note,
        "published_by": (auth_service.current_user(request) or {}).get("id"),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    evt = supabase_client.insert_event(
        {
            "event_type": "graph_document_published",
            "entity_type": "graph_document",
            "entity_id": doc_id,
            "payload": payload,
            "level": "info",
            "source": "graph_documents.publish",
        },
        source="graph_documents.publish",
    )
    if not evt:
        raise HTTPException(502, "Failed to persist graph document event")

    # Publishing the canonical document materializes the derived knowledge_nodes /
    # knowledge_edges / vault rows (this is what "aciona os serviços de atualizar o
    # banco" when the front-end edits the graph). A reindex failure does NOT lose
    # the published document — it is surfaced as `reindex_error`.
    reindex: dict = {}
    try:
        reindex = graph_json_importer.import_graph_json(
            graph_json=graph,
            source=f"graph_documents.publish:{body.source}",
        ) or {}
    except Exception as exc:  # pragma: no cover - defensive
        reindex = {"ok": False, "reindex_error": str(exc)}

    return {
        "ok": True,
        "id": doc_id,
        "persona_slug": body.persona_slug,
        "brand_slug": body.brand_slug,
        "version": next_version,
        "reindex_ok": bool(reindex.get("ok", False)),
        "nodes_imported": reindex.get("nodes_imported"),
        "edges_imported": reindex.get("edges_imported"),
        "reindex_error": reindex.get("reindex_error") or (None if reindex.get("ok", True) else reindex.get("errors")),
    }


@router.post("/apply-patch")
def graph_document_apply_patch(body: ApplyPatchBody, request: Request):
    auth_service.current_user(request)
    graph = _validate_graph_json_or_422(body.graph_json)
    current = graph_json_v2_store.load_current(body.persona_slug)
    next_version = 1 if not current else current[0] + 1
    checksum = graph_json_v2_store.save_version(body.persona_slug, next_version, graph)
    return {
        "ok": True,
        "persona_slug": body.persona_slug,
        "version": next_version,
        "checksum": checksum,
        "source": body.source,
        "note": body.note,
    }


@router.post("/import-json")
def graph_document_import_json(body: ImportGraphDocumentBody, request: Request):
    auth_service.current_user(request)
    graph = _validate_graph_json_or_422(body.graph_json)
    if graph.persona_slug != body.persona_slug:
        raise HTTPException(
            422,
            {
                "code": "GRAPH_PERSONA_MISMATCH",
                "errors": [f"body persona_slug={body.persona_slug} differs from graph_json persona_slug={graph.persona_slug}"],
            },
        )
    result = graph_json_importer.import_graph_json(
        graph_json=graph,
        source=body.source,
        session_id=body.session_id,
    )
    if result.get("ok") is False:
        raise HTTPException(422, result)
    current = graph_json_v2_store.load_current(body.persona_slug)
    next_version = 1 if not current else current[0] + 1
    checksum = graph_json_v2_store.save_version(body.persona_slug, next_version, graph)
    return {
        **result,
        "version": next_version,
        "checksum": checksum,
        "note": body.note,
    }


@router.post("/rollback")
def graph_document_rollback(body: RollbackBody, request: Request):
    auth_service.current_user(request)
    target = graph_json_v2_store.load_version(body.persona_slug, body.version)
    if target is None:
        raise HTTPException(404, "Requested rollback version not found")
    current = graph_json_v2_store.load_current(body.persona_slug)
    next_version = 1 if not current else current[0] + 1
    checksum = graph_json_v2_store.save_version(body.persona_slug, next_version, target)
    return {
        "ok": True,
        "persona_slug": body.persona_slug,
        "rolled_back_from": body.version,
        "new_version": next_version,
        "checksum": checksum,
        "note": body.note,
    }


@router.post("/reindex")
def graph_document_reindex(body: ReindexBody, request: Request):
    auth_service.current_user(request)
    current = graph_json_v2_store.load_current(body.persona_slug)
    if current is None:
        raise HTTPException(404, "No graph document available for reindex")
    version, graph = current
    # Re-validate current state to mirror backend reindex guard semantics.
    is_valid, errors = graph_json_v2_validator.validate_graph_json(graph)
    if not is_valid:
        raise HTTPException(422, {"code": "GRAPH_VALIDATION_FAILED", "errors": errors})
    # Materialize the canonical document into the derived tables (knowledge_nodes /
    # knowledge_edges / knowledge_items + vault). Tolerant: a materialization error
    # is reported but does not 500 the reindex.
    reindex: dict = {}
    try:
        reindex = graph_json_importer.import_graph_json(
            graph_json=graph,
            source=f"graph_documents.reindex:{body.persona_slug}",
        ) or {}
    except Exception as exc:  # pragma: no cover - defensive
        reindex = {"ok": False, "reindex_error": str(exc)}
    return {
        "ok": True,
        "persona_slug": body.persona_slug,
        "version": version,
        "indexed_nodes": reindex.get("nodes_imported", len(graph.nodes)),
        "indexed_edges": reindex.get("edges_imported", len(graph.edges)),
        "reindex_ok": bool(reindex.get("ok", False)),
        "reindex_error": reindex.get("reindex_error"),
        "note": body.note,
    }


@router.get("/events")
def graph_document_events(
    request: Request,
    persona_slug: str = Query(...),
    brand_slug: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    auth_service.current_user(request)
    rows = supabase_client.list_system_events(
        entity_type="graph_document",
        event_types=[
            "graph_document_published",
            "graph_document_apply_patch",
            "graph_document_rollback",
            "graph_document_reindex",
        ],
        limit=limit,
    )
    out: list[dict] = []
    for row in rows:
        payload = row.get("payload") or {}
        if payload.get("persona_slug") != persona_slug:
            continue
        if (payload.get("brand_slug") or None) != (brand_slug or None):
            continue
        out.append(
            {
                "id": row.get("id"),
                "event_type": row.get("event_type"),
                "entity_id": row.get("entity_id"),
                "payload": payload,
                "created_at": row.get("created_at"),
            }
        )
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"persona_slug": persona_slug, "brand_slug": brand_slug, "events": out}

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services import auth_service, supabase_client

router = APIRouter(prefix="/graph-documents", tags=["graph-documents"])


class PublishGraphDocumentBody(BaseModel):
    persona_slug: str = Field(..., min_length=1)
    brand_slug: Optional[str] = None
    graph_json: dict
    source: str = "import_v1_to_v2"
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


@router.get("/current")
def graph_document_current(
    request: Request,
    persona_slug: str = Query(...),
    brand_slug: Optional[str] = Query(None),
):
    auth_service.current_user(request)
    evt = _latest_event(persona_slug, brand_slug)
    if not evt:
        raise HTTPException(404, "No published graph document for this persona/brand")
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
    return {
        "ok": True,
        "id": doc_id,
        "persona_slug": body.persona_slug,
        "brand_slug": body.brand_slug,
        "version": next_version,
    }

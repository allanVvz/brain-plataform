from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
import mimetypes

from services import auth_service, graph_bundle_view, supabase_client
from pydantic import BaseModel, Field
from services import catalog_media_plan
from services import site_blocks
from brain_contracts.catalog_media import resolve_catalog_media


class MediaOperation(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)
    owner_node_id: str
    asset_node_id: str
    action: Literal["assign", "pin", "unpin", "unlink"]
    assigned_at: str = Field(min_length=1)


class MediaPlanBody(BaseModel):
    bundle: dict
    operations: list[MediaOperation] = Field(min_length=1, max_length=100)


class MediaPreviewBody(BaseModel):
    bundle: dict
    scope: str
    owner_node_id: str


router = APIRouter(prefix="/graph-bundles", tags=["graph-bundles"])


@router.post("/media-preview")
def media_preview(body: MediaPreviewBody, request: Request):
    persona = body.bundle.get("persona") or {}
    if not persona.get("id"):
        raise HTTPException(422, "Persona is required")
    auth_service.assert_persona_access(request, persona_id=persona["id"])
    try:
        nodes = body.bundle["nodes"]
        edges = body.bundle["edges"]
        scope = site_blocks.branch_closure({node["id"]: node for node in nodes}, edges, body.scope)
        return resolve_catalog_media(nodes, edges, persona_id=persona["id"],
                                     scoped_ids=scope, owner_id=body.owner_node_id)
    except (ValueError, KeyError, site_blocks.SiteBlockError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/media/{asset_node_id}")
def graph_media(asset_node_id: str, request: Request, persona_slug: str = Query(...),
                publication_id: str = Query(...)):
    auth_service.assert_persona_access(request, persona_slug=persona_slug)
    try:
        view = graph_bundle_view.get_view(persona_slug, source="publication",
                                          ref=f"publication:{publication_id}")
    except graph_bundle_view.GraphBundleViewNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    node = next((row for row in (view.get("document") or {}).get("nodes", [])
                 if str(row.get("id")) == asset_node_id and row.get("node_type") == "asset"), None)
    media = (node or {}).get("data", {}).get("media") or {}
    bucket, path = media.get("bucket"), media.get("path")
    mime = media.get("mime") or mimetypes.guess_type(str(path or ""))[0]
    if not bucket or not path or mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}:
        raise HTTPException(404, "Media not found")
    try:
        content = supabase_client.download_from_storage(bucket, path)
    except Exception:
        raise HTTPException(404, "Media unavailable") from None
    return Response(content, media_type=mime, headers={"Cache-Control": "private, no-store",
                                                       "X-Content-Type-Options": "nosniff"})


@router.post("/media-plan")
def media_plan(body: MediaPlanBody, request: Request):
    persona = body.bundle.get("persona") or {}
    if not persona.get("id") or not persona.get("slug"):
        raise HTTPException(422, "Persona is required")
    auth_service.assert_persona_capability(request, "edit", persona_id=persona["id"])
    user = auth_service.current_user(request) or {}
    if user.get("role") == "viewer" or not user.get("id"):
        raise HTTPException(403, "Editing is not permitted")
    try:
        return catalog_media_plan.plan(body.bundle,
            [operation.model_dump() for operation in body.operations], actor_id=user["id"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _assert_persona_view(request: Request, persona_slug: str) -> None:
    auth_service.assert_persona_access(request, persona_slug=persona_slug)


@router.get("/versions")
def graph_bundle_versions(
    request: Request,
    persona_slug: str = Query(..., min_length=1),
):
    _assert_persona_view(request, persona_slug)
    try:
        return graph_bundle_view.list_versions(persona_slug)
    except graph_bundle_view.GraphBundleViewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/view")
def graph_bundle_view_get(
    request: Request,
    persona_slug: str = Query(..., min_length=1),
    source: Literal["draft", "publication"] = Query(...),
    ref: str = Query(..., min_length=1),
):
    _assert_persona_view(request, persona_slug)
    try:
        return graph_bundle_view.get_view(persona_slug, source=source, ref=ref)
    except graph_bundle_view.GraphBundleViewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

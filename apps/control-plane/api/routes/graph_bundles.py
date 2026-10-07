from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
import mimetypes

from services import auth_service, graph_bundle_view, graph_editor, supabase_client
from services.graph_bundle_publisher import GraphBundlePublishError
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


# ── Graph editor (akia/docs/architecture/engenharia-de-grafo.md) ─────────────

class EditorSaveBody(BaseModel):
    persona_slug: str = Field(min_length=1, max_length=128)
    base_publication_id: str = Field(min_length=1, max_length=64)
    changes: list[dict] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=128)


class EditorRevertBody(BaseModel):
    persona_slug: str = Field(min_length=1, max_length=128)
    to_publication_id: str = Field(min_length=1, max_length=64)
    base_publication_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _editor_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, graph_editor.GraphEditorOutcomeUnknown):
        return _editor_save_error(exc)
    if isinstance(exc, graph_editor.GraphEditorConflict):
        return HTTPException(status_code=409, detail={"errors": graph_editor.readable_errors([str(exc)])})
    if isinstance(exc, graph_editor.GraphEditorError) and str(exc) in {"persona_not_found", "active_publication_not_found"}:
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _editor_save_error(exc: Exception) -> HTTPException:
    """Save failures always carry {errors: [{code, message}]} in plain Portuguese."""
    if isinstance(exc, graph_editor.GraphEditorRejected):
        return HTTPException(status_code=422, detail={"errors": exc.errors})
    if isinstance(exc, graph_editor.GraphEditorOutcomeUnknown):
        return HTTPException(status_code=503, detail={"errors": [{
            "code": "publication_outcome_unknown_retry_same_key",
            "message": "Não foi possível confirmar o salvamento. Tente novamente; seu rascunho foi preservado.",
        }]})
    if isinstance(exc, graph_editor.GraphEditorConflict):
        return HTTPException(status_code=409, detail={"errors": graph_editor.readable_errors([str(exc)])})
    if isinstance(exc, graph_editor.GraphEditorError) and str(exc) in {"persona_not_found", "active_publication_not_found"}:
        return HTTPException(status_code=404, detail={"errors": graph_editor.readable_errors([str(exc)])})
    if isinstance(exc, (GraphBundlePublishError, graph_editor.GraphEditorError)):
        # Validation/staging errors do not trigger a compensating activation.
        return HTTPException(status_code=422, detail={"errors": [{
            "code": "publication_failed",
            "message": f"A publicação foi recusada ({str(exc).split(':')[0]}).",
        }]})
    return HTTPException(status_code=422, detail={"errors": graph_editor.readable_errors([str(exc)])})


def _assert_editor_publisher(request: Request, persona_slug: str) -> str:
    # Phase 1: publishing from the editor is limited to platform admins.
    auth_service.assert_persona_capability(request, "edit", persona_slug=persona_slug)
    user = auth_service.current_user(request)
    if not auth_service.is_admin(user):
        raise HTTPException(status_code=403, detail="Publicação pelo editor restrita a administradores nesta fase.")
    return str(user.get("id") or user.get("email") or "unknown")


@router.get("/editor")
def graph_editor_get(request: Request, persona_slug: str = Query(..., min_length=1)):
    _assert_persona_view(request, persona_slug)
    try:
        publication = graph_editor.active_publication(persona_slug)
        view = graph_editor.editor_view(publication)
        previous = graph_editor.previous_publication(persona_slug, str(publication.get("id")))
        return {"publication": view.pop("publication"), "previous_publication": previous, **view}
    except (graph_editor.GraphEditorError, ValueError) as exc:
        raise _editor_http_error(exc) from exc


@router.post("/editor/save")
def graph_editor_save(body: EditorSaveBody, request: Request):
    actor = _assert_editor_publisher(request, body.persona_slug)
    try:
        return graph_editor.save(
            persona_slug=body.persona_slug, base_publication_id=body.base_publication_id,
            changes=body.changes, actor=actor, idempotency_key=body.idempotency_key,
        )
    except (graph_editor.GraphEditorError, GraphBundlePublishError, ValueError) as exc:
        raise _editor_save_error(exc) from exc


@router.post("/editor/revert")
def graph_editor_revert(body: EditorRevertBody, request: Request):
    actor = _assert_editor_publisher(request, body.persona_slug)
    try:
        return graph_editor.revert(persona_slug=body.persona_slug, to_publication_id=body.to_publication_id,
                                   actor=actor, base_publication_id=body.base_publication_id,
                                   idempotency_key=body.idempotency_key)
    except (graph_editor.GraphEditorError, ValueError) as exc:
        raise _editor_http_error(exc) from exc

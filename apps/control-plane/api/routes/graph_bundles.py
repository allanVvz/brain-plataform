from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from schemas.graph_bundle_drafts import (
    CreateGraphBundleDraftBody, PatchGraphBundleDraftBody,
    PublishGraphBundleDraftBody, SealGraphBundleDraftBody, FaqImpactBody,
)
from services import (
    auth_service, graph_bundle, graph_bundle_active_adapter,
    graph_bundle_draft_evidence, graph_bundle_draft_ops, graph_bundle_draft_store,
    graph_bundle_publisher, graph_bundle_view,
    supabase_client,
)


router = APIRouter(prefix="/graph-bundles", tags=["graph-bundles"])


def _assert_persona_view(request: Request, persona_slug: str) -> None:
    auth_service.assert_persona_access(request, persona_slug=persona_slug)


def _actor(request: Request) -> str:
    user = auth_service.current_user(request)
    return str(user.get("id") or user.get("email") or "unknown")


def _draft_for_request(request: Request, draft_ref: str, capability: str = "view") -> dict:
    try:
        draft = graph_bundle_draft_store.get(draft_ref)
    except graph_bundle_draft_store.DraftNotFound as exc:
        raise HTTPException(404, "graph_bundle_draft_not_found") from exc
    auth_service.assert_persona_capability(
        request, capability, persona_id=draft.get("persona_id"),
        persona_slug=draft.get("persona_slug"),
    )
    return draft


def _draft_conflict(draft: dict, code: str = "draft_cas_conflict") -> HTTPException:
    return HTTPException(409, {
        "code": code,
        "current_revision": draft.get("revision"),
        "current_draft_checksum": draft.get("draft_checksum"),
    })


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


@router.post("/drafts", status_code=201)
def create_draft(request: Request, body: CreateGraphBundleDraftBody):
    auth_service.assert_persona_capability(request, "edit", persona_slug=body.persona_slug)
    persona = supabase_client.get_persona(body.persona_slug)
    if not persona:
        raise HTTPException(404, "persona_not_found")
    try:
        replay = graph_bundle_draft_store.replay_create(
            persona_id=str(persona["id"]),
            expected_active_checksum=body.expected_active_checksum,
            reason=body.reason, source=body.source.model_dump(),
            idempotency_key=body.idempotency_key,
        )
    except graph_bundle_draft_store.DraftConflict as exc:
        raise _draft_conflict(exc.current or {}, str(exc)) from exc
    if replay:
        return replay
    active = supabase_client.get_active_graph_publication(str(persona["id"]))
    if not active or active.get("status") != "active":
        raise HTTPException(409, "active_graph_publication_v3_required")
    if active.get("checksum") != body.expected_active_checksum:
        raise HTTPException(409, "active_publication_checksum_changed")
    try:
        bundle = graph_bundle_active_adapter.active_document_to_draft(
            active.get("document_json") or {}, expected_persona_slug=body.persona_slug,
            expected_runtime_checksum=body.expected_active_checksum,
        )
        return graph_bundle_draft_store.create(
            persona_id=str(persona["id"]), persona_slug=body.persona_slug, bundle=bundle,
            active_publication_id=str(active["id"]), active_checksum=body.expected_active_checksum,
            actor=_actor(request), reason=body.reason, source=body.source.model_dump(),
            idempotency_key=body.idempotency_key,
            reuse_open=body.reuse_open,
        )
    except graph_bundle_active_adapter.ActivePublicationAdapterError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/drafts/{draft_ref}")
def get_draft(request: Request, draft_ref: str):
    return _draft_for_request(request, draft_ref)


@router.patch("/drafts/{draft_ref}")
def patch_draft(request: Request, draft_ref: str, body: PatchGraphBundleDraftBody):
    _draft_for_request(request, draft_ref, "edit")
    try:
        return graph_bundle_draft_store.patch(
            draft_ref, expected_revision=body.expected_revision,
            expected_checksum=body.expected_draft_checksum, operations=body.operations,
            actor=_actor(request), reason=body.reason, source=body.source.model_dump(),
            idempotency_key=body.idempotency_key,
        )
    except graph_bundle_draft_store.DraftConflict as exc:
        raise _draft_conflict(exc.current or _draft_for_request(request, draft_ref), str(exc)) from exc
    except graph_bundle_draft_ops.GraphBundleDraftConflict as exc:
        raise _draft_conflict(_draft_for_request(request, draft_ref)) from exc
    except graph_bundle_draft_ops.GraphBundleDraftOperationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/drafts/{draft_ref}/diff")
def draft_diff(request: Request, draft_ref: str):
    draft = _draft_for_request(request, draft_ref)
    active = supabase_client.get_active_graph_publication(draft["persona_id"])
    plan = graph_bundle.build_draft_publication_plan(
        draft["bundle"], current_document=(active or {}).get("document_json")
    )
    return {key: plan.get(key) for key in (
        "draft_checksum", "runtime_checksum", "node_changes", "edge_changes",
        "branches_affected", "chunks_reused", "chunks_to_embed", "breaking_contract_changes",
    )}


@router.post("/drafts/{draft_ref}/faq-impact")
def draft_faq_impact(request: Request, draft_ref: str, body: FaqImpactBody):
    draft = _draft_for_request(request, draft_ref)
    if (
        draft["revision"] != body.expected_revision
        or draft["draft_checksum"] != body.expected_draft_checksum
    ):
        raise _draft_conflict(draft)
    try:
        return {
            "draft_ref": draft_ref,
            "revision": draft["revision"],
            "draft_checksum": draft["draft_checksum"],
            **graph_bundle_draft_ops.faq_impact(
                draft["bundle"], body.changed_node_ids
            ),
        }
    except graph_bundle_draft_ops.GraphBundleDraftOperationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/drafts/{draft_ref}/plan")
def draft_plan(request: Request, draft_ref: str, body: SealGraphBundleDraftBody):
    draft = _draft_for_request(request, draft_ref, "edit")
    if draft["revision"] != body.expected_revision or draft["draft_checksum"] != body.expected_draft_checksum:
        raise _draft_conflict(draft)
    active = supabase_client.get_active_graph_publication(draft["persona_id"])
    plan = graph_bundle.build_draft_publication_plan(
        draft["bundle"], current_document=(active or {}).get("document_json")
    )
    evidence = graph_bundle_draft_evidence.record(
        "plan", draft=draft, result=plan, actor=_actor(request),
        idempotency_key=body.idempotency_key,
    )
    return {**plan, "plan_ref": evidence["evidence_ref"]}


@router.post("/drafts/{draft_ref}/validate")
def draft_validate(request: Request, draft_ref: str, body: SealGraphBundleDraftBody):
    draft = _draft_for_request(request, draft_ref, "edit")
    if draft["revision"] != body.expected_revision or draft["draft_checksum"] != body.expected_draft_checksum:
        raise _draft_conflict(draft)
    active = supabase_client.get_active_graph_publication(draft["persona_id"])
    plan = graph_bundle.build_draft_publication_plan(
        draft["bundle"], current_document=(active or {}).get("document_json")
    )
    result = {
        "ok": not plan.get("validation_errors"),
        "validation_errors": plan.get("validation_errors", []),
        "runtime_checksum": plan.get("runtime_checksum"),
    }
    evidence = graph_bundle_draft_evidence.record(
        "validation", draft=draft, result=result, actor=_actor(request),
        idempotency_key=body.idempotency_key,
    )
    return {**result, "validation_ref": evidence["evidence_ref"]}


@router.get("/drafts/{draft_ref}/preview")
def draft_preview(request: Request, draft_ref: str, surface: Literal["agent", "catalog", "site"]):
    draft = _draft_for_request(request, draft_ref)
    plan = graph_bundle.build_draft_publication_plan(draft["bundle"])
    document = plan.get("candidate_document")
    if not isinstance(document, dict):
        raise HTTPException(422, plan.get("validation_errors") or ["draft_preview_blocked"])
    return {"surface": surface, "draft_ref": draft_ref, "draft_checksum": draft["draft_checksum"],
            "runtime_checksum": document["checksum"], "document": document}


@router.post("/drafts/{draft_ref}/publish")
def draft_publish(request: Request, draft_ref: str, body: PublishGraphBundleDraftBody):
    draft = _draft_for_request(request, draft_ref, "edit")
    checkpoint = graph_bundle_publisher.get_publish_checkpoint(
        draft_ref, body.idempotency_key
    )
    if checkpoint:
        if (
            checkpoint.get("draft_checksum") != body.expected_draft_checksum
            or checkpoint.get("runtime_checksum") != body.approved_runtime_checksum
        ):
            raise _draft_conflict(draft, "publish_idempotency_key_reused")
        activated = graph_bundle_publisher.activate_reviewed_publication(
            publication_id=str(checkpoint["publication_id"]),
            persona_id=draft["persona_id"],
            approved_runtime_checksum=body.approved_runtime_checksum,
            draft_ref=draft_ref,
            idempotency_key=body.idempotency_key,
        )
        return {"draft_ref": draft_ref, "publication": checkpoint,
                "activation": activated, "checksum": body.approved_runtime_checksum}
    if draft["revision"] != body.expected_revision or draft["draft_checksum"] != body.expected_draft_checksum:
        raise _draft_conflict(draft)
    try:
        plan_evidence = graph_bundle_draft_evidence.require(
            body.plan_ref, "plan", draft=draft,
            runtime_checksum=body.approved_runtime_checksum,
        )
        graph_bundle_draft_evidence.require(
            body.validation_ref, "validation", draft=draft,
            runtime_checksum=body.approved_runtime_checksum,
        )
        reviewed_plan = dict(plan_evidence.get("result") or {})
        if reviewed_plan.get("runtime_checksum") != body.approved_runtime_checksum:
            raise graph_bundle_draft_evidence.DraftEvidenceError("publish_evidence_stale")
        staged = graph_bundle_publisher.stage_bundle(
            reviewed_plan.get("candidate_bundle") or draft["bundle"],
            approved_draft_checksum=body.expected_draft_checksum,
            actor=_actor(request), reviewed_plan=reviewed_plan,
        )
        publication = staged["publication"]
        graph_bundle_publisher.checkpoint_reviewed_publication(
            draft=draft, publication_id=str(publication["id"]),
            runtime_checksum=body.approved_runtime_checksum,
            idempotency_key=body.idempotency_key,
        )
        activated = graph_bundle_publisher.activate_reviewed_publication(
            publication_id=str(publication["id"]), persona_id=draft["persona_id"],
            approved_runtime_checksum=body.approved_runtime_checksum,
            draft_ref=draft_ref, idempotency_key=body.idempotency_key,
        )
    except (graph_bundle_draft_evidence.DraftEvidenceError,
            graph_bundle_publisher.GraphBundlePublishError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"draft_ref": draft_ref, "publication": publication,
            "activation": activated, "checksum": body.approved_runtime_checksum}

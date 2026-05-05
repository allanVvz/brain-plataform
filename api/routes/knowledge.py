import asyncio
import os
from fastapi import APIRouter, Query, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from services import auth_service, supabase_client, knowledge_graph
from services.knowledge_rag_backfill import backfill_knowledge_rag
from services.knowledge_rag_intake import process_intake, process_intake_plan
from services.vault_sync import run_sync, scan_vault
from services.event_emitter import emit

VAULT_SOURCE_MODE = os.environ.get("VAULT_SOURCE_MODE")
OBSIDIAN_LOCAL_PATH = os.environ.get("OBSIDIAN_LOCAL_PATH")

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class RagIntakeBody(BaseModel):
    raw_text: str
    persona_id: Optional[str] = None
    persona_slug: Optional[str] = None
    source: str = "manual"
    source_ref: Optional[str] = None
    title: Optional[str] = None
    content_type: Optional[str] = None
    tags: list[str] = []
    metadata: dict = {}
    submitted_by: Optional[str] = None
    validate: bool = False
    parent_node_id: Optional[str] = None
    parent_relation_type: str = "manual"


class RagBackfillBody(BaseModel):
    persona_id: Optional[str] = None
    persona_slug: Optional[str] = None
    include_vault: bool = True
    # This is no longer used, vault source is configured by env vars
    # vault_path: Optional[str] = None 
    limit_items: int = 5000
    limit_nodes: int = 5000


class RagIntakePlanBody(BaseModel):
    persona_id: Optional[str] = None
    persona_slug: Optional[str] = None
    run_token: Optional[str] = None
    entries: list[dict]
    links: list[dict] = []
    source: str = "plan"
    source_ref: Optional[str] = None
    submitted_by: Optional[str] = None
    validate: bool = True


@router.post("/intake")
def intake_rag_knowledge(body: RagIntakeBody, request: Request):
    if not body.raw_text.strip():
        raise HTTPException(400, "raw_text is required")
    if not body.persona_id and not body.persona_slug:
        raise HTTPException(400, "persona_id or persona_slug is required")
    auth_service.assert_persona_access(request, persona_id=body.persona_id, persona_slug=body.persona_slug)
    try:
        result = process_intake(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Knowledge intake failed: {exc}") from exc

    rag_entry = result.get("rag_entry") or {}
    emit(
        "knowledge_rag_intake_created",
        entity_type="knowledge_rag_entry",
        entity_id=rag_entry.get("id"),
        persona_id=rag_entry.get("persona_id"),
        payload={
            "title": rag_entry.get("title"),
            "content_type": rag_entry.get("content_type"),
            "status": rag_entry.get("status"),
        },
    )
    return result


@router.post("/intake/plan")
def intake_rag_knowledge_plan(body: RagIntakePlanBody, request: Request):
    if not body.entries:
        raise HTTPException(400, "entries is required")
    if not body.persona_id and not body.persona_slug:
        raise HTTPException(400, "persona_id or persona_slug is required")
    auth_service.assert_persona_access(request, persona_id=body.persona_id, persona_slug=body.persona_slug)
    try:
        result = process_intake_plan(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Knowledge plan intake failed: {exc}") from exc

    emit(
        "knowledge_rag_plan_intake_created",
        entity_type="knowledge_rag_plan",
        entity_id=result.get("run_token"),
        persona_id=(result.get("persona") or {}).get("id"),
        payload={
            "entries_created": result.get("entries_created"),
            "nodes_created": result.get("nodes_created"),
            "main_edges": result.get("main_edges"),
            "auxiliary_edges": result.get("auxiliary_edges"),
        },
    )
    return result

# ── Vault Sync ────────────────────────────────────────────────

@router.post("/rag/backfill")
async def backfill_rag_knowledge(body: RagBackfillBody):
    """Reprocess legacy knowledge into knowledge_rag_entries/chunks/links."""
    if body.persona_id and body.persona_slug:
        raise HTTPException(400, "Use persona_id or persona_slug, not both")
    try:
        # Pass a dictionary without vault_path to the backfill function
        dump = body.model_dump()
        dump.pop("vault_path", None) 
        result = await asyncio.to_thread(backfill_knowledge_rag, **dump)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"RAG backfill failed: {exc}") from exc
    emit(
        "knowledge_rag_backfill_completed",
        entity_type="knowledge_rag_backfill",
        persona_id=body.persona_id,
        payload=result,
    )
    return result


@router.post("/sync")
async def trigger_sync(persona: str = Query(None)):
    emit("vault_sync_started", entity_type="sync", payload={})
    result = await asyncio.to_thread(run_sync, persona_filter=persona)
    if "error" in result:
        emit("vault_sync_failed", payload=result)
        raise HTTPException(400, result["error"])
    return result


@router.get("/sync/preview")
async def preview_sync():
    result = await asyncio.to_thread(scan_vault)
    return result


@router.get("/sync/runs")
def list_sync_runs(limit: int = 20):
    return supabase_client.get_sync_runs(limit)


@router.get("/sync/runs/{run_id}/logs")
def get_sync_logs(run_id: str, limit: int = 200):
    return supabase_client.get_sync_logs(run_id, limit)


# ── File serve (for asset preview) ───────────────────────────

@router.get("/file")
def serve_vault_file(path: str):
    """Serve a file from the vault. Only available in local mode."""
    if VAULT_SOURCE_MODE != "local":
        raise HTTPException(
            status_code=501,
            detail="File serving from vault is only supported in VAULT_SOURCE_MODE='local'."
        )
    if not OBSIDIAN_LOCAL_PATH:
        raise HTTPException(status_code=500, detail="OBSIDIAN_LOCAL_PATH is not set.")

    from pathlib import Path
    vault_root = Path(OBSIDIAN_LOCAL_PATH).resolve()
    requested = (vault_root / path).resolve()
    # Security: prevent path traversal
    if not str(requested).startswith(str(vault_root)):
        raise HTTPException(403, "Access denied")
    if not requested.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(requested))


# ── Knowledge Queue ───────────────────────────────────────────

# Statuses that require human attention before content can be used
ATTENTION_STATUSES = ["needs_persona", "needs_category", "pending"]

# Fixed paths MUST be registered before parameterised /{item_id}
@router.get("/queue")
def list_queue(
    request: Request,
    status: str = Query("pending"),
    persona_id: str = Query(None),
    content_type: str = Query(None),
    limit: int = 100,
    offset: int = 0,
):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    elif not auth_service.is_admin(auth_service.current_user(request)):
        rows: list[dict] = []
        for pid in auth_service.allowed_persona_ids(request):
            rows.extend(list_queue(request, status=status, persona_id=pid, content_type=content_type, limit=limit, offset=offset))
        return rows[:limit]
    # "attention" is a virtual combined filter
    if status == "attention":
        return supabase_client.get_knowledge_items_multi(
            statuses=ATTENTION_STATUSES,
            persona_id=persona_id,
            content_type=content_type,
            limit=limit,
            offset=offset,
        )
    return supabase_client.get_knowledge_items(
        status=status,
        persona_id=persona_id,
        content_type=content_type,
        limit=limit,
        offset=offset,
    )


@router.get("/queue/counts")
def queue_counts(request: Request, persona_id: str = Query(None)):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    elif not auth_service.is_admin(auth_service.current_user(request)):
        combined = {"by_status": {}, "total": 0}
        for pid in auth_service.allowed_persona_ids(request):
            partial = queue_counts(request, persona_id=pid)
            combined["total"] += partial.get("total", 0)
            for key, value in (partial.get("by_status") or {}).items():
                combined["by_status"][key] = combined["by_status"].get(key, 0) + value
        return combined
    counts = supabase_client.get_knowledge_item_counts(persona_id=persona_id)
    bs = counts.get("by_status", {})
    counts["by_status"]["attention"] = sum(
        bs.get(s, 0) for s in ATTENTION_STATUSES
    )
    return counts


@router.get("/gallery-assets")
def gallery_assets(request: Request, persona_id: str = Query(None), limit: int = Query(250, ge=1, le=500)):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    elif not auth_service.is_admin(auth_service.current_user(request)):
        rows: list[dict] = []
        for pid in auth_service.allowed_persona_ids(request):
            rows.extend(supabase_client.list_gallery_assets(persona_id=pid, limit=limit))
        return rows[:limit]
    return supabase_client.list_gallery_assets(persona_id=persona_id, limit=limit)


@router.get("/queue/{item_id}")
def get_queue_item(item_id: str, request: Request):
    try:
        item = supabase_client.get_knowledge_item(item_id)
    except Exception as exc:
        raise HTTPException(502, f"Database error: {exc}") from exc
    if not item:
        raise HTTPException(404, "Item not found")
    if item.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=item.get("persona_id"))
    return item


class ItemUpdate(BaseModel):
    persona_id: Optional[str] = None
    content_type: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    rejected_reason: Optional[str] = None
    tags: Optional[list] = None
    agent_visibility: Optional[list] = None
    asset_type: Optional[str] = None
    asset_function: Optional[str] = None


@router.patch("/queue/{item_id}")
def update_queue_item(item_id: str, body: ItemUpdate, request: Request):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Nothing to update")
    try:
        # Auto-upgrade status based on what's being filled in
        cached_item: Optional[dict] = None
        existing = supabase_client.get_knowledge_item(item_id)
        if existing and existing.get("persona_id"):
            auth_service.assert_persona_access(request, persona_id=existing.get("persona_id"))
        if data.get("persona_id"):
            auth_service.assert_persona_access(request, persona_id=data.get("persona_id"))

        if "persona_id" in data:
            cached_item = existing
            if cached_item and cached_item.get("status") == "needs_persona":
                ct = data.get("content_type") or cached_item.get("content_type", "other")
                data["status"] = "pending"

        if "content_type" in data and data["content_type"] != "other":
            if cached_item is None:
                cached_item = supabase_client.get_knowledge_item(item_id)
            if cached_item and cached_item.get("status") == "needs_category":
                data["status"] = "pending"

        supabase_client.update_knowledge_item(item_id, data)
        updated = supabase_client.get_knowledge_item(item_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Database error: {exc}") from exc

    if not updated:
        raise HTTPException(404, "Item not found after update")
    return updated


class ApproveBody(BaseModel):
    promote_to_kb: bool = False
    agent_visibility: list = ["SDR", "Closer", "Classifier"]


@router.post("/queue/{item_id}/approve")
def approve_item(item_id: str, request: Request, body: ApproveBody = ApproveBody()):
    from datetime import datetime, timezone
    try:
        item = supabase_client.get_knowledge_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if not item.get("persona_id"):
            raise HTTPException(400, "Assign a persona before approving")
        auth_service.assert_persona_access(request, persona_id=item.get("persona_id"))

        update_data: dict = {
            "status": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "agent_visibility": body.agent_visibility,
        }
        supabase_client.update_knowledge_item(item_id, update_data)

        if body.promote_to_kb:
            _promote_to_kb({**item, **update_data})
            supabase_client.update_knowledge_item(item_id, {"status": "embedded"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Approve/promote failed: {exc}") from exc

    emit("item_approved", entity_type="knowledge_item", entity_id=item_id,
         persona_id=item.get("persona_id"),
         payload={"title": item.get("title"), "content_type": item.get("content_type"),
                  "promoted_to_kb": body.promote_to_kb})

    return supabase_client.get_knowledge_item(item_id)


class RejectBody(BaseModel):
    reason: str = ""


@router.post("/queue/{item_id}/reject")
def reject_item(item_id: str, request: Request, body: RejectBody = RejectBody()):
    item = supabase_client.get_knowledge_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if item.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=item.get("persona_id"))
    supabase_client.update_knowledge_item(item_id, {
        "status": "rejected",
        "rejected_reason": body.reason,
    })
    emit("item_rejected", entity_type="knowledge_item", entity_id=item_id,
         persona_id=item.get("persona_id"),
         payload={"title": item.get("title"), "reason": body.reason})
    return {"ok": True}


@router.post("/queue/{item_id}/to-kb")
def promote_to_kb(item_id: str, request: Request):
    try:
        item = supabase_client.get_knowledge_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if item["status"] not in ("approved", "embedded"):
            raise HTTPException(400, "Item must be approved before promoting to KB")
        if not item.get("persona_id"):
            raise HTTPException(400, "Item must have a persona assigned")
        auth_service.assert_persona_access(request, persona_id=item.get("persona_id"))
        _promote_to_kb(item)
        supabase_client.update_knowledge_item(item_id, {"status": "embedded"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Promote to KB failed: {exc}") from exc
    emit("item_promoted_to_kb", entity_type="knowledge_item", entity_id=item_id,
         persona_id=item.get("persona_id"),
         payload={"title": item.get("title")})
    return {"ok": True}


def _promote_to_kb(item: dict) -> None:
    import hashlib
    kb_id = "ki_" + hashlib.md5(
        f"{item.get('file_path', item['id'])}:{item['persona_id']}".encode()
    ).hexdigest()[:12]
    entry = supabase_client.upsert_kb_entry({
        "kb_id": kb_id,
        "persona_id": item["persona_id"],
        "tipo": _content_type_to_tipo(item["content_type"]),
        "categoria": item["content_type"],
        "titulo": item["title"],
        "conteudo": item["content"],
        "status": "ATIVO",
        "source": "manual",
        "agent_visibility": item.get("agent_visibility") or ["SDR", "Closer", "Classifier"],
        "tags": item.get("tags") or [],
    })
    if entry:
        knowledge_graph.bootstrap_from_item(
            {
                "id": entry.get("id"),
                "title": entry.get("titulo"),
                "content_type": item.get("content_type"),
                "content": entry.get("conteudo") or item.get("content"),
                "tags": entry.get("tags") or item.get("tags") or [],
                "status": entry.get("status") or "ATIVO",
                "persona_id": entry.get("persona_id") or item.get("persona_id"),
                "file_path": item.get("file_path") or entry.get("link"),
            },
            frontmatter=item.get("metadata") or {},
            body=entry.get("conteudo") or item.get("content") or "",
            persona_id=entry.get("persona_id") or item.get("persona_id"),
            source_table="kb_entries",
        )


def _content_type_to_tipo(ct: str) -> str:
    return {
        "faq": "faq", "brand": "brand", "briefing": "briefing",
        "product": "produto", "copy": "copy", "prompt": "prompt",
        "rule": "regra", "tone": "tom", "competitor": "concorrente",
        "audience": "audiencia", "campaign": "campanha",
        "maker_material": "maker", "asset": "asset", "other": "geral",
    }.get(ct, "geral")


# ── Upload / Knowledge Intake ─────────────────────────────────

class UploadTextBody(BaseModel):
    title: str
    content: str
    persona_id: Optional[str] = None
    content_type: str = "other"
    metadata: dict = {}


@router.post("/upload/text")
def upload_text(body: UploadTextBody, request: Request):
    if body.persona_id:
        auth_service.assert_persona_access(request, persona_id=body.persona_id)
    source = supabase_client.get_or_create_manual_source()
    status = "pending"
    item = supabase_client.insert_knowledge_item({
        "persona_id": body.persona_id,
        "source_id": source["id"],
        "status": status,
        "content_type": body.content_type,
        "title": body.title,
        "content": body.content,
        "metadata": body.metadata,
        "file_type": "text",
    })
    if item:
        knowledge_graph.bootstrap_from_item(
            item,
            frontmatter=body.metadata or {},
            body=body.content,
            persona_id=body.persona_id,
            source_table="knowledge_items",
        )
    emit("upload_received", entity_type="knowledge_item", entity_id=item["id"],
         persona_id=body.persona_id,
         payload={"title": body.title, "content_type": body.content_type})
    return item


@router.post("/upload/file")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    persona_id: str = Form(None),
    content_type: str = Form("other"),
):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    content_bytes = await file.read()
    try:
        text = content_bytes.decode("utf-8")
    except Exception:
        raise HTTPException(400, "File must be UTF-8 text")

    source = supabase_client.get_or_create_manual_source()
    status = "pending"
    item = supabase_client.insert_knowledge_item({
        "persona_id": persona_id,
        "source_id": source["id"],
        "status": status,
        "content_type": content_type,
        "title": file.filename or "upload",
        "content": text[:8000],
        "file_type": (file.filename or "").rsplit(".", 1)[-1] if file.filename else "txt",
        "metadata": {"original_filename": file.filename},
    })
    if item:
        knowledge_graph.bootstrap_from_item(
            item,
            frontmatter={"original_filename": file.filename},
            body=text,
            persona_id=persona_id,
            source_table="knowledge_items",
        )
    emit("upload_received", entity_type="knowledge_item", entity_id=item["id"],
         persona_id=persona_id, payload={"filename": file.filename})
    return item


# ── KB Entries (Vault) — single-item CRUD ────────────────────

@router.get("/kb/{entry_id}")
def get_kb_entry(entry_id: str, request: Request):
    entry = supabase_client.get_kb_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    if entry.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=entry.get("persona_id"))
    return entry


class KbEntryUpdate(BaseModel):
    titulo: Optional[str] = None
    conteudo: Optional[str] = None
    tipo: Optional[str] = None
    categoria: Optional[str] = None
    tags: Optional[list] = None
    status: Optional[str] = None
    agent_visibility: Optional[list] = None


@router.patch("/kb/{entry_id}")
def update_kb_entry(entry_id: str, body: KbEntryUpdate, request: Request):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Nothing to update")
    entry = supabase_client.get_kb_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    if entry.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=entry.get("persona_id"))
    supabase_client.update_kb_entry(entry_id, data)
    entry = supabase_client.get_kb_entry(entry_id)
    emit("kb_entry_updated", entity_type="kb_entry", entity_id=entry_id,
         persona_id=entry.get("persona_id"),
         payload={"titulo": entry.get("titulo"), "fields": list(data.keys())})
    return entry


@router.post("/kb/{entry_id}/validate")
def validate_kb_entry(entry_id: str, request: Request):
    entry = supabase_client.get_kb_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    if entry.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=entry.get("persona_id"))
    supabase_client.update_kb_entry(entry_id, {"status": "ATIVO"})
    emit("kb_entry_validated", entity_type="kb_entry", entity_id=entry_id,
         persona_id=entry.get("persona_id"),
         payload={"titulo": entry.get("titulo")})
    return {"ok": True, "status": "ATIVO"}


# ── Workflow Bindings ─────────────────────────────────────────

@router.get("/bindings")
def list_bindings(request: Request, persona_id: str = Query(None)):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    return supabase_client.get_workflow_bindings(persona_id)


class BindingBody(BaseModel):
    persona_id: str
    workflow_name: str
    n8n_workflow_id: Optional[str] = None
    whatsapp_number: Optional[str] = None
    active: bool = True


@router.post("/bindings")
def create_binding(body: BindingBody, request: Request):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode criar bindings")
    return supabase_client.upsert_workflow_binding(body.model_dump())


# ── Knowledge Graph rebuild (admin) ──────────────────────────

@router.post("/graph/rebuild")
def rebuild_graph(request: Request, persona_slug: Optional[str] = Query(None)):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode reconstruir o grafo")
    """Reprocessa knowledge_items + kb_entries existentes para popular
    knowledge_nodes / knowledge_edges (migration 008).

    Use após aplicar 008 ou quando o grafo divergir das tabelas-fonte.

    Quando `persona_slug` é informado, escopa pra essa persona; senão,
    roda globalmente (cuidado em prod com muitos clientes).

    Resposta:
      {persona_slug, persona_id, counts: {items_seen, items_mirrored,
       items_skipped, kb_seen, kb_mirrored, kb_skipped, errors[]}}
    """
    persona_id: Optional[str] = None
    if persona_slug:
        persona = supabase_client.get_persona(persona_slug)
        if not persona:
            raise HTTPException(404, f"Persona not found: {persona_slug}")
        persona_id = persona.get("id")

    counts = knowledge_graph.rebuild_graph_for_persona(persona_id)
    return {
        "persona_slug": persona_slug,
        "persona_id": persona_id,
        "counts": counts,
    }


# ── Chat Context (semantic graph + KB fallback) ──────────────

@router.get("/chat-context")
def chat_context(
    request: Request,
    lead_ref: int = Query(None),
    persona_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(12, le=50),
):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    """Knowledge bundle for the messages sidebar.

    Resolves products/campaigns/assets/FAQs related to a lead's recent
    conversation (or to an explicit `q`). Falls back gracefully when the
    semantic graph has no data — always returns the same response shape.
    """
    return knowledge_graph.get_chat_context(
        lead_ref=lead_ref,
        persona_id=persona_id,
        user_text=q,
        limit=limit,
    )


# ── KB Context (for external consumers like wa-wscrap-bot) ───

@router.get("/context/{persona_slug}")
def get_kb_context(persona_slug: str, request: Request):
    """Return formatted KB text for a persona slug. Used by ai_fallback in wa-wscrap-bot."""
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise HTTPException(404, f"Persona not found: {persona_slug}")
    auth_service.assert_persona_access(request, persona_id=persona.get("id"), persona_slug=persona_slug)

    persona_id = persona["id"]
    entries = supabase_client.get_kb_entries(persona_id=persona_id, status="ATIVO")
    if not entries:
        return {"persona_slug": persona_slug, "context": ""}

    sections: dict[str, list[str]] = {}
    for e in entries:
        tipo = e.get("tipo", "geral")
        text = f"[{e.get('titulo', '')}] {e.get('conteudo', '')}"
        sections.setdefault(tipo, []).append(text)

    lines: list[str] = []
    priority = ["brand", "tom", "produto", "regra", "briefing", "faq"]
    order = priority + [k for k in sections if k not in priority]
    for tipo in order:
        if tipo not in sections:
            continue
        lines.append(f'\n### {tipo.upper()}')
        for item in sections[tipo][:6]:
            lines.append(f"- {item[:400]}")

    return {"persona_slug": persona_slug, "context": "\n".join(lines)}


# ── Brand Profiles ────────────────────────────────────────────

@router.get("/brand/{persona_id}")
def get_brand(persona_id: str, request: Request):
    auth_service.assert_persona_access(request, persona_id=persona_id)
    return supabase_client.get_brand_profile(persona_id) or {}


@router.put("/brand/{persona_id}")
def upsert_brand(persona_id: str, body: dict, request: Request):
    auth_service.assert_persona_access(request, persona_id=persona_id)
    return supabase_client.upsert_brand_profile({"persona_id": persona_id, **body})

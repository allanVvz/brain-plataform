import asyncio
import os
from fastapi import APIRouter, Query, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from services import supabase_client, knowledge_graph
from services.vault_sync import run_sync, scan_vault, VAULT_PATH
from services.event_emitter import emit

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# ── Vault Sync ────────────────────────────────────────────────

@router.post("/sync")
async def trigger_sync(persona: str = Query(None), vault_path: str = Query(None)):
    path = vault_path or VAULT_PATH
    emit("vault_sync_started", entity_type="sync", payload={"path": path})
    result = await asyncio.to_thread(run_sync, path, persona)
    if "error" in result:
        emit("vault_sync_failed", payload=result)
        raise HTTPException(400, result["error"])
    return result


@router.get("/sync/preview")
async def preview_sync(vault_path: str = Query(None)):
    path = vault_path or VAULT_PATH
    result = await asyncio.to_thread(scan_vault, path)
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
    """Serve a file from the vault. Path is relative to VAULT_PATH."""
    from pathlib import Path
    vault_root = Path(VAULT_PATH).resolve()
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
    status: str = Query("pending"),
    persona_id: str = Query(None),
    content_type: str = Query(None),
    limit: int = 100,
    offset: int = 0,
):
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
def queue_counts():
    counts = supabase_client.get_knowledge_item_counts()
    bs = counts.get("by_status", {})
    counts["by_status"]["attention"] = sum(
        bs.get(s, 0) for s in ATTENTION_STATUSES
    )
    return counts


@router.get("/queue/{item_id}")
def get_queue_item(item_id: str):
    try:
        item = supabase_client.get_knowledge_item(item_id)
    except Exception as exc:
        raise HTTPException(502, f"Database error: {exc}") from exc
    if not item:
        raise HTTPException(404, "Item not found")
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
def update_queue_item(item_id: str, body: ItemUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Nothing to update")
    try:
        # Auto-upgrade status based on what's being filled in
        cached_item: Optional[dict] = None

        if "persona_id" in data:
            cached_item = supabase_client.get_knowledge_item(item_id)
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
def approve_item(item_id: str, body: ApproveBody = ApproveBody()):
    from datetime import datetime, timezone
    try:
        item = supabase_client.get_knowledge_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if not item.get("persona_id"):
            raise HTTPException(400, "Assign a persona before approving")

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
def reject_item(item_id: str, body: RejectBody = RejectBody()):
    item = supabase_client.get_knowledge_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    supabase_client.update_knowledge_item(item_id, {
        "status": "rejected",
        "rejected_reason": body.reason,
    })
    emit("item_rejected", entity_type="knowledge_item", entity_id=item_id,
         persona_id=item.get("persona_id"),
         payload={"title": item.get("title"), "reason": body.reason})
    return {"ok": True}


@router.post("/queue/{item_id}/to-kb")
def promote_to_kb(item_id: str):
    try:
        item = supabase_client.get_knowledge_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if item["status"] not in ("approved", "embedded"):
            raise HTTPException(400, "Item must be approved before promoting to KB")
        if not item.get("persona_id"):
            raise HTTPException(400, "Item must have a persona assigned")
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
def upload_text(body: UploadTextBody):
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
    file: UploadFile = File(...),
    persona_id: str = Form(None),
    content_type: str = Form("other"),
):
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
def get_kb_entry(entry_id: str):
    entry = supabase_client.get_kb_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
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
def update_kb_entry(entry_id: str, body: KbEntryUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Nothing to update")
    supabase_client.update_kb_entry(entry_id, data)
    entry = supabase_client.get_kb_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    emit("kb_entry_updated", entity_type="kb_entry", entity_id=entry_id,
         persona_id=entry.get("persona_id"),
         payload={"titulo": entry.get("titulo"), "fields": list(data.keys())})
    return entry


@router.post("/kb/{entry_id}/validate")
def validate_kb_entry(entry_id: str):
    entry = supabase_client.get_kb_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    supabase_client.update_kb_entry(entry_id, {"status": "ATIVO"})
    emit("kb_entry_validated", entity_type="kb_entry", entity_id=entry_id,
         persona_id=entry.get("persona_id"),
         payload={"titulo": entry.get("titulo")})
    return {"ok": True, "status": "ATIVO"}


# ── Workflow Bindings ─────────────────────────────────────────

@router.get("/bindings")
def list_bindings(persona_id: str = Query(None)):
    return supabase_client.get_workflow_bindings(persona_id)


class BindingBody(BaseModel):
    persona_id: str
    workflow_name: str
    n8n_workflow_id: Optional[str] = None
    whatsapp_number: Optional[str] = None
    active: bool = True


@router.post("/bindings")
def create_binding(body: BindingBody):
    return supabase_client.upsert_workflow_binding(body.model_dump())


# ── Knowledge Graph rebuild (admin) ──────────────────────────

@router.post("/graph/rebuild")
def rebuild_graph(persona_slug: Optional[str] = Query(None)):
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
    lead_ref: int = Query(None),
    persona_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(12, le=50),
):
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
def get_kb_context(persona_slug: str):
    """Return formatted KB text for a persona slug. Used by ai_fallback in wa-wscrap-bot."""
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise HTTPException(404, f"Persona not found: {persona_slug}")

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
        lines.append(f"\n### {tipo.upper()}")
        for item in sections[tipo][:6]:
            lines.append(f"- {item[:400]}")

    return {"persona_slug": persona_slug, "context": "\n".join(lines)}


# ── Brand Profiles ────────────────────────────────────────────

@router.get("/brand/{persona_id}")
def get_brand(persona_id: str):
    return supabase_client.get_brand_profile(persona_id) or {}


@router.put("/brand/{persona_id}")
def upsert_brand(persona_id: str, body: dict):
    return supabase_client.upsert_brand_profile({"persona_id": persona_id, **body})

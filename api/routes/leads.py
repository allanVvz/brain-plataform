import csv
import io
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from services import agents_service, auth_service, event_emitter, knowledge_graph, supabase_client

router = APIRouter(prefix="/leads", tags=["leads"])


NAME_HEADERS = {"nome", "name", "nome completo", "cliente", "contato", "lead", "first name", "fn"}
LAST_NAME_HEADERS = {"sobrenome", "last name", "last_name", "ln"}
PHONE_HEADERS = {"telefone", "celular", "phone", "whatsapp", "numero", "lead_id", "mobile"}
EMAIL_HEADERS = {"email", "e-mail", "mail"}
CITY_HEADERS = {"cidade", "city", "ct"}
STATE_HEADERS = {"estado", "state", "st", "uf"}
ZIP_HEADERS = {"cep", "zip", "zipcode", "postal_code"}
COUNTRY_HEADERS = {"pais", "country"}


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("55") and len(digits) > 11:
        return digits
    return digits


def _display_name(first_name: str, last_name: str, fallback: str = "") -> str:
    name = " ".join(part for part in [first_name.strip(), last_name.strip()] if part).strip()
    return name or fallback.strip()


def _pick_field(row: dict, candidates: set[str]) -> str:
    normalized = {_normalize_header(k): v for k, v in row.items()}
    for key in candidates:
        if key in normalized and str(normalized[key] or "").strip():
            return str(normalized[key]).strip()
    for key, value in normalized.items():
        if any(candidate in key for candidate in candidates) and str(value or "").strip():
            return str(value).strip()
    return ""


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "CSV must be UTF-8 text")


def _create_audience_node(*, persona_id: str, batch_payload: dict) -> dict | None:
    batch_id = batch_payload["batch_id"]
    stats = batch_payload.get("stats") or {}
    title = f"Audiencia importada - {batch_payload.get('filename') or batch_id[:8]}"
    node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "source_table": "system_events",
        "source_id": batch_id,
        "node_type": "audience",
        "slug": f"audiencia-import-{batch_id}",
        "title": title,
        "summary": f"{stats.get('valid', 0)} leads validos; {stats.get('with_phone', 0)} com celular.",
        "tags": ["audience", "lead_import", "crm"],
        "metadata": {
            "lead_import_batch_id": batch_id,
            "filename": batch_payload.get("filename"),
            "stats": stats,
            "preview": batch_payload.get("preview") or [],
            "open_url": f"/leads/import?open={batch_id}",
            "source": "lead_import",
        },
        "status": "active",
        "level": 55,
        "importance": 0.72,
        "confidence": 1,
    })
    persona_root = knowledge_graph._ensure_persona_root(persona_id)
    if node and persona_root:
        supabase_client.upsert_knowledge_edge(
            source_node_id=persona_root["id"],
            target_node_id=node["id"],
            relation_type="contains",
            persona_id=persona_id,
            weight=1,
            metadata={"primary_tree": True, "created_from": "lead_import"},
        )
    return node


@router.get("")
def list_leads(
    request: Request,
    limit: int = Query(100, le=500),
    offset: int = 0,
    persona_id: str | None = Query(None),
    persona_slug: str | None = Query(None),
):
    try:
        if persona_id or persona_slug:
            auth_service.assert_persona_access(request, persona_id=persona_id, persona_slug=persona_slug)
        elif not auth_service.is_admin(auth_service.current_user(request)):
            return supabase_client.get_leads_for_persona_ids(auth_service.allowed_persona_ids(request), limit=limit, offset=offset)
        return supabase_client.get_leads(persona_slug=persona_id or persona_slug, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(500, f"Erro ao buscar leads: {exc}")


@router.post("/imports")
async def import_leads_csv(
    request: Request,
    file: UploadFile = File(...),
    persona_id: str | None = Form(None),
):
    if not persona_id:
        raise HTTPException(400, "Selecione uma persona antes de importar leads")
    auth_service.assert_persona_access(request, persona_id=persona_id)

    filename = file.filename or "leads.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported for now")

    text = _decode_csv(await file.read())
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(400, "CSV header row is required")

    batch_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    batch_event = supabase_client.insert_event(
        {
            "event_type": "lead_import_batch",
            "entity_type": "lead_import",
            "entity_id": batch_id,
            "persona_id": persona_id,
            "payload": {
                "batch_id": batch_id,
                "filename": filename,
                "headers": reader.fieldnames,
                "status": "running",
                "started_at": now_iso,
            },
        },
        level="info",
        source="leads.import",
    )

    stats = {"total": 0, "valid": 0, "with_phone": 0, "email_only": 0, "created": 0, "updated": 0, "invalid": 0}
    preview: list[dict] = []
    for index, row in enumerate(reader, start=1):
        stats["total"] += 1
        raw_row = {str(k or ""): v for k, v in (row or {}).items()}
        first_name = _pick_field(raw_row, NAME_HEADERS)
        last_name = _pick_field(raw_row, LAST_NAME_HEADERS)
        name = _display_name(first_name, last_name, _pick_field(raw_row, {"nome completo", "name", "nome"}))
        phone = _normalize_phone(_pick_field(raw_row, PHONE_HEADERS))
        email = _pick_field(raw_row, EMAIL_HEADERS)
        city = _pick_field(raw_row, CITY_HEADERS)
        state = _pick_field(raw_row, STATE_HEADERS)
        zip_code = _pick_field(raw_row, ZIP_HEADERS)
        country = _pick_field(raw_row, COUNTRY_HEADERS)
        status = "created"
        error = ""
        lead_ref = None

        has_phone = bool(phone and len(phone) >= 8)
        has_email = bool(email)
        if not has_phone and not has_email:
            status = "invalid"
            error = "missing_email_and_phone"
            stats["invalid"] += 1
        elif not has_phone:
            status = "email_only"
            stats["valid"] += 1
            stats["email_only"] += 1
        else:
            stats["valid"] += 1
            stats["with_phone"] += 1
            existing = supabase_client.get_lead(phone)
            lead = supabase_client.ensure_lead_for_persona(
                lead_id=phone,
                persona_slug_or_id=persona_id,
                nome=name or None,
                stage="novo",
                canal="bulk_import",
                cidade=city or None,
                cep=zip_code or None,
            )
            lead_ref = lead.get("id") if lead else None
            if existing:
                status = "updated"
                stats["updated"] += 1
            else:
                stats["created"] += 1

        payload = {
            "batch_id": batch_id,
            "filename": filename,
            "row_index": index,
            "raw_row": raw_row,
            "parsed": {
                "nome": name,
                "fn": first_name,
                "ln": last_name,
                "lead_id": phone,
                "email": email,
                "cidade": city,
                "estado": state,
                "zip": zip_code,
                "country": country,
            },
            "status": status,
            "error": error,
            "lead_ref": lead_ref,
            "persona_id": persona_id,
        }
        supabase_client.insert_event(
            {
                "event_type": "lead_import_row",
                "entity_type": "lead_import",
                "entity_id": batch_id,
                "persona_id": persona_id,
                "payload": payload,
            },
            level="error" if status == "invalid" else "info",
            source="leads.import",
        )
        if status != "invalid" and len(preview) < 5:
            preview.append(payload)

    finished_at = datetime.now(timezone.utc).isoformat()
    batch_payload = {
        "batch_id": batch_id,
        "filename": filename,
        "headers": reader.fieldnames,
        "status": "completed",
        "started_at": now_iso,
        "finished_at": finished_at,
        "stats": stats,
        "preview": preview,
        "persona_id": persona_id,
    }
    supabase_client.insert_event(
        {
            "event_type": "lead_import_batch",
            "entity_type": "lead_import",
            "entity_id": batch_id,
            "persona_id": persona_id,
            "payload": batch_payload,
        },
        level="info",
        source="leads.import",
    )
    audience_node = _create_audience_node(persona_id=persona_id, batch_payload=batch_payload)
    batch_payload["audience_node_id"] = audience_node.get("id") if audience_node else None
    return {"ok": True, "batch": batch_payload, "batch_event": batch_event, "preview": preview, "audience_node": audience_node}


@router.get("/imports")
def list_lead_imports(
    request: Request,
    limit: int = Query(20, le=100),
    persona_id: str | None = Query(None),
):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    elif not auth_service.is_admin(auth_service.current_user(request)):
        persona_ids = auth_service.allowed_persona_ids(request)
        imports: list[dict] = []
        for pid in persona_ids:
            imports.extend(list_lead_imports(request, limit=limit, persona_id=pid))
        imports.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return imports[:limit]
    events = supabase_client.get_events(
        limit=limit * 5,
        event_type="lead_import_batch",
        persona_id=persona_id,
    )
    deleted = supabase_client.get_events(
        limit=500,
        event_type="lead_import_batch_deleted",
        persona_id=persona_id,
    )
    deleted_ids = {
        (event.get("payload") or {}).get("batch_id") or event.get("entity_id")
        for event in deleted
    }
    by_batch: dict[str, dict] = {}
    for event in events:
        payload = event.get("payload") or {}
        batch_id = payload.get("batch_id") or event.get("entity_id") or event.get("id")
        if not batch_id or batch_id in deleted_ids or batch_id in by_batch:
            continue
        by_batch[batch_id] = {**payload, "event_id": event.get("id"), "created_at": event.get("created_at")}
    return list(by_batch.values())[:limit]


@router.get("/imports/{batch_event_id}")
def get_lead_import(batch_event_id: str, request: Request, limit: int = Query(2000, le=5000)):
    rows = supabase_client.get_events(
        limit=limit,
        event_type="lead_import_row",
        entity_id=batch_event_id,
    )
    batches = supabase_client.get_events(
        limit=10,
        event_type="lead_import_batch",
        entity_id=batch_event_id,
    )
    batch = (batches[0].get("payload") if batches else {}) or {"batch_id": batch_event_id}
    if batch.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=batch.get("persona_id"))
    parsed_rows = [event.get("payload") or {} for event in rows]
    parsed_rows.sort(key=lambda item: int(item.get("row_index") or 0))
    return {"batch": batch, "rows": parsed_rows}


@router.delete("/imports/{batch_id}")
def delete_lead_import(batch_id: str, request: Request):
    batches = supabase_client.get_events(limit=10, event_type="lead_import_batch", entity_id=batch_id)
    batch = (batches[0].get("payload") if batches else {}) or {"batch_id": batch_id}
    persona_id = batch.get("persona_id")
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    supabase_client.insert_event(
        {
            "event_type": "lead_import_batch_deleted",
            "entity_type": "lead_import",
            "entity_id": batch_id,
            "persona_id": persona_id,
            "payload": {
                "batch_id": batch_id,
                "filename": batch.get("filename"),
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "status": "deleted",
            },
        },
        level="info",
        source="leads.import",
    )
    if persona_id:
        supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "source_table": "system_events",
            "source_id": batch_id,
            "node_type": "audience",
            "slug": f"audiencia-import-{batch_id}",
            "title": f"Audiencia importada - {batch.get('filename') or batch_id[:8]}",
            "summary": "Grupo de leads arquivado.",
            "tags": ["audience", "lead_import", "archived"],
            "metadata": {**(batch or {}), "archived": True, "lead_import_batch_id": batch_id},
            "status": "archived",
        })
    return {"ok": True, "batch_id": batch_id}


@router.get("/{lead_id}")
def get_lead(lead_id: str, request: Request):
    lead = supabase_client.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=lead.get("persona_id"))
    return lead


@router.post("/{lead_ref}/pause-ai")
def pause_ai(lead_ref: int, request: Request):
    """Pausa a IA para esse lead. /process passa a devolver agent_used=PAUSED."""
    lead = supabase_client.get_lead_by_ref(lead_ref)
    if lead and lead.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=lead.get("persona_id"))
    ok = agents_service.pause_lead(lead_ref)
    if not ok:
        raise HTTPException(500, "Falha ao pausar lead")
    event_emitter.emit(
        "lead.ai_paused",
        entity_type="lead",
        entity_id=str(lead_ref),
        payload={"ai_paused": True, "by": "manual"},
        source="leads.pause_ai",
    )
    return {"ok": True, "lead_ref": lead_ref, "ai_paused": True}


@router.post("/{lead_ref}/resume-ai")
def resume_ai(lead_ref: int, request: Request):
    """Retoma a IA para esse lead."""
    lead = supabase_client.get_lead_by_ref(lead_ref)
    if lead and lead.get("persona_id"):
        auth_service.assert_persona_access(request, persona_id=lead.get("persona_id"))
    ok = agents_service.resume_lead(lead_ref)
    if not ok:
        raise HTTPException(500, "Falha ao retomar lead")
    event_emitter.emit(
        "lead.ai_resumed",
        entity_type="lead",
        entity_id=str(lead_ref),
        payload={"ai_paused": False, "by": "manual"},
        source="leads.resume_ai",
    )
    return {"ok": True, "lead_ref": lead_ref, "ai_paused": False}

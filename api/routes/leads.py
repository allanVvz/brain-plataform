import csv
import io
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from services import agents_service, auth_service, event_emitter, knowledge_graph, supabase_client

router = APIRouter(prefix="/leads", tags=["leads"])


class LeadAudienceChangeBody(BaseModel):
    target_persona_id: str
    target_audience_id: str | None = None
    target_audience_slug: str | None = None
    source_audience_id: str | None = None
    source_audience_slug: str | None = None


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
    stats = batch_payload.get("stats") or {}
    audience = supabase_client.ensure_import_audience(persona_id)
    if not audience:
        return None
    node = supabase_client.sync_audience_node({
        **audience,
        "description": f"{stats.get('valid', 0)} leads validos; {stats.get('with_phone', 0)} com celular.",
    })
    if node:
        supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "source_table": "audiences",
            "source_id": audience["id"],
            "node_type": "audience",
            "slug": audience["slug"],
            "title": audience["name"],
            "summary": f"{stats.get('valid', 0)} leads validos; {stats.get('with_phone', 0)} com celular.",
            "tags": ["audience", "lead_import", "crm"],
            "metadata": {
                **(node.get("metadata") or {}),
                "lead_import_batch_id": batch_payload.get("batch_id"),
                "filename": batch_payload.get("filename"),
                "stats": stats,
                "preview": batch_payload.get("preview") or [],
                "open_url": f"/leads/{(supabase_client.get_persona_by_id(persona_id) or {}).get('slug', '')}/{audience['slug']}",
                "source": "lead_import",
            },
            "status": "active",
            "level": 55,
            "importance": 0.72,
            "confidence": 1,
        })
    return node


@router.get("")
def list_leads(
    request: Request,
    limit: int = Query(100, le=2000),
    offset: int = 0,
    persona_id: str | None = Query(None),
    persona_slug: str | None = Query(None),
    audience_id: str | None = Query(None),
    audience_slug: str | None = Query(None),
):
    """Lista leads visiveis na persona ativa.

    Visibilidade vem de lead_audience_memberships, nao de leads.persona_id.
    Quando audience_slug=import e a persona ainda nao tem essa system
    audience, garantimos via helper idempotente para nao 404 a UI.
    """
    try:
        resolved_persona_id = persona_id
        if not resolved_persona_id and persona_slug:
            persona = supabase_client.get_persona(persona_slug)
            resolved_persona_id = persona.get("id") if persona else None
        if resolved_persona_id:
            # Garantir que system audience `import` exista; idempotente.
            try:
                supabase_client.ensure_system_audiences_for_persona(resolved_persona_id)
            except Exception:
                pass
        if resolved_persona_id and (audience_id or audience_slug):
            auth_service.assert_persona_access(request, persona_id=resolved_persona_id, persona_slug=persona_slug)
            try:
                return supabase_client.get_leads_for_audience_scope(
                    persona_id=resolved_persona_id,
                    audience_id=audience_id,
                    audience_slug=audience_slug,
                    limit=limit,
                    offset=offset,
                ) or []
            except Exception:
                return []
        if persona_id or persona_slug:
            auth_service.assert_persona_access(request, persona_id=persona_id, persona_slug=persona_slug)
        elif not auth_service.is_admin(auth_service.current_user(request)):
            return supabase_client.get_leads_for_persona_ids(auth_service.allowed_persona_ids(request), limit=limit, offset=offset) or []
        return supabase_client.get_leads(persona_slug=persona_id or persona_slug, limit=limit, offset=offset) or []
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Erro ao buscar leads: {exc}")


_EMPTY_HASHED_HINT = (
    "Nenhum lead valido. Verifique se o CSV tem colunas email/telefone em texto plano. "
    "Audiencias Meta exportadas com hash (sha256) nao sao suportadas; "
    "exporte o CSV sem hashing."
)


def _persist_terminal_batch_event(
    *,
    batch_id: str,
    persona_id: str,
    payload: dict,
    level: str = "info",
) -> dict | None:
    """Grava o evento batch terminal (completed/failed) numa unica chamada."""
    return supabase_client.insert_event(
        {
            "event_type": "lead_import_batch",
            "entity_type": "lead_import",
            "entity_id": batch_id,
            "persona_id": persona_id,
            "payload": payload,
        },
        level=level,
        source="leads.import",
    )


@router.post("/imports")
async def import_leads_csv(
    request: Request,
    file: UploadFile = File(...),
    persona_id: str | None = Form(None),
):
    if not persona_id:
        raise HTTPException(400, "Selecione uma persona antes de importar leads")
    auth_service.assert_persona_access(request, persona_id=persona_id)
    current_user = auth_service.current_user(request)

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
    started_at = datetime.now(timezone.utc).isoformat()
    headers = list(reader.fieldnames or [])

    # System "import" audience is idempotent — safe to ensure even if the batch
    # eventually fails; nothing is attached to it unless we insert memberships.
    import_audience = supabase_client.ensure_import_audience(
        persona_id,
        created_by_user_id=current_user.get("id"),
    )

    stats = {"total": 0, "valid": 0, "with_phone": 0, "email_only": 0, "created": 0, "updated": 0, "invalid": 0}
    preview: list[dict] = []

    try:
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
            row_status = "created"
            row_error = ""
            lead_ref = None

            has_phone = bool(phone and len(phone) >= 8)
            has_email = bool(email)
            if not has_phone and not has_email:
                row_status = "invalid"
                row_error = "missing_email_and_phone"
                stats["invalid"] += 1
            elif not has_phone:
                row_status = "email_only"
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
                if lead_ref and import_audience:
                    supabase_client.ensure_lead_membership(
                        lead_ref,
                        import_audience["id"],
                        membership_type="primary" if not existing else "shared",
                        created_by_user_id=current_user.get("id"),
                    )
                if existing:
                    row_status = "updated"
                    stats["updated"] += 1
                else:
                    stats["created"] += 1

            row_payload = {
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
                "status": row_status,
                "error": row_error,
                "lead_ref": lead_ref,
                "persona_id": persona_id,
            }
            supabase_client.insert_event(
                {
                    "event_type": "lead_import_row",
                    "entity_type": "lead_import",
                    "entity_id": batch_id,
                    "persona_id": persona_id,
                    "payload": row_payload,
                },
                level="error" if row_status == "invalid" else "info",
                source="leads.import",
            )
            if row_status != "invalid" and len(preview) < 5:
                preview.append(row_payload)
    except Exception as exc:
        # Any unexpected error mid-loop: persist a single terminal `failed`
        # event so the import never lingers as orphan/running. Re-raise as 500
        # so the frontend surfaces the failure.
        finished_at = datetime.now(timezone.utc).isoformat()
        failed_payload = {
            "batch_id": batch_id,
            "filename": filename,
            "headers": headers,
            "status": "failed",
            "started_at": started_at,
            "finished_at": finished_at,
            "stats": stats,
            "preview": preview,
            "persona_id": persona_id,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _persist_terminal_batch_event(
            batch_id=batch_id, persona_id=persona_id, payload=failed_payload, level="error"
        )
        raise HTTPException(500, f"Falha ao importar leads: {exc}")

    finished_at = datetime.now(timezone.utc).isoformat()

    # Total == 0 → CSV header-only. Refuse without persisting noise.
    if stats["total"] == 0:
        raise HTTPException(400, "CSV sem linhas alem do cabecalho.")

    valid = stats["valid"]
    if valid == 0:
        # Header parsed but no row produced a usable lead. Persist as failed
        # with a descriptive error and skip the legacy audience graph node so
        # the graph nao polui com lixo de import.
        failed_payload = {
            "batch_id": batch_id,
            "filename": filename,
            "headers": headers,
            "status": "failed",
            "started_at": started_at,
            "finished_at": finished_at,
            "stats": stats,
            "preview": preview,
            "persona_id": persona_id,
            "error": _EMPTY_HASHED_HINT,
        }
        _persist_terminal_batch_event(
            batch_id=batch_id, persona_id=persona_id, payload=failed_payload, level="warn"
        )
        return {
            "ok": False,
            "status": "failed",
            "batch": failed_payload,
            "preview": preview,
            "audience_node": None,
            "error": _EMPTY_HASHED_HINT,
        }

    batch_payload = {
        "batch_id": batch_id,
        "filename": filename,
        "headers": headers,
        "status": "completed",
        "started_at": started_at,
        "finished_at": finished_at,
        "stats": stats,
        "preview": preview,
        "persona_id": persona_id,
    }
    batch_event = _persist_terminal_batch_event(
        batch_id=batch_id, persona_id=persona_id, payload=batch_payload, level="info"
    )
    audience_node = _create_audience_node(persona_id=persona_id, batch_payload=batch_payload)
    batch_payload["audience_node_id"] = audience_node.get("id") if audience_node else None
    return {
        "ok": True,
        "status": "completed",
        "batch": batch_payload,
        "batch_event": batch_event,
        "preview": preview,
        "audience_node": audience_node,
    }


_TERMINAL_BATCH_STATUSES = {"completed", "failed"}
_STALE_RUNNING_THRESHOLD_SECONDS = 120


def _reclassify_stale_running(item: dict) -> dict:
    """Mark batches stuck on `running` (or sem status terminal) as `failed`.

    Cobre lixo legado de antes da gravacao atomica do handler — o handler novo
    nunca escreve `running`, mas eventos antigos podem persistir. Sem este
    filtro o frontend listava esses batches como 'imports validos' com 0/0/0.
    """
    status = (item.get("status") or "").lower()
    if status in _TERMINAL_BATCH_STATUSES:
        return item
    created = item.get("created_at") or ""
    age_seconds = 0.0
    try:
        ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        age_seconds = 0.0
    if age_seconds < _STALE_RUNNING_THRESHOLD_SECONDS:
        return item
    stats = item.get("stats") or {"total": 0, "valid": 0, "with_phone": 0, "email_only": 0, "created": 0, "updated": 0, "invalid": 0}
    return {
        **item,
        "status": "failed",
        "stats": stats,
        "error": item.get("error") or "Importacao interrompida sem evento terminal (orfa).",
    }


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
    items = [_reclassify_stale_running(item) for item in by_batch.values()]
    return items[:limit]


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
    try:
        lead_pk = int(lead.get("id") or 0)
    except (TypeError, ValueError):
        lead_pk = 0
    memberships: list[dict] = []
    if lead_pk > 0:
        try:
            memberships = supabase_client.get_lead_memberships(lead_pk) or []
        except Exception:
            memberships = []
    visible = False
    for membership in memberships:
        audience = membership.get("audience") or {}
        persona_id = audience.get("persona_id")
        if not persona_id:
            continue
        try:
            auth_service.assert_persona_access(request, persona_id=persona_id)
            visible = True
            break
        except HTTPException:
            continue
    if not visible and lead.get("persona_id"):
        # Compatibilidade: leads antigos sem membership ainda podem usar
        # leads.persona_id como fallback de visibilidade.
        auth_service.assert_persona_access(request, persona_id=lead.get("persona_id"))
    return lead


def _resolve_target_audience(body: LeadAudienceChangeBody, request: Request) -> dict:
    """Resolve a audience destino. Se o slug requisitado for `import` e
    a persona destino ainda nao tiver, criamos via helper idempotente em vez
    de devolver 404. Para qualquer outro slug nao encontrado, mantemos 404."""
    auth_service.assert_persona_access(request, persona_id=body.target_persona_id)
    audience = None
    if body.target_audience_id:
        audience = supabase_client.get_audience(body.target_audience_id)
    elif body.target_audience_slug:
        audience = supabase_client.get_audience_by_slug(body.target_persona_id, body.target_audience_slug)
        if not audience and body.target_audience_slug == "import":
            audience = supabase_client.ensure_import_audience(body.target_persona_id)
    if not audience or audience.get("persona_id") != body.target_persona_id:
        raise HTTPException(404, "Target audience not found for persona")
    return audience


def _resolve_source_audience(lead_ref: int, body: LeadAudienceChangeBody) -> dict | None:
    if body.source_audience_id:
        return supabase_client.get_audience(body.source_audience_id)
    if body.source_audience_slug and body.target_persona_id:
        return supabase_client.get_audience_by_slug(body.target_persona_id, body.source_audience_slug)
    try:
        memberships = supabase_client.get_lead_memberships(lead_ref) or []
    except Exception:
        memberships = []
    return memberships[0].get("audience") if memberships else None


@router.get("/{lead_id}/memberships")
def lead_memberships(lead_id: str, request: Request):
    """Endpoint defensivo: nunca quebra por lead sem membership.

    Sempre retorna 200 com `{lead, memberships: [...]}`. Para leads
    inexistentes mantemos 404 (e o frontend trata).
    """
    lead = supabase_client.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    try:
        lead_pk = int(lead.get("id") or 0)
    except (TypeError, ValueError):
        lead_pk = 0
    memberships: list[dict] = []
    if lead_pk > 0:
        try:
            memberships = supabase_client.get_lead_memberships(lead_pk) or []
        except Exception:
            memberships = []
    allowed: list[dict] = []
    for membership in memberships:
        audience = membership.get("audience") or {}
        persona_id = audience.get("persona_id")
        try:
            if persona_id:
                auth_service.assert_persona_access(request, persona_id=persona_id)
            allowed.append(membership)
        except HTTPException:
            continue
    return {"lead": lead, "memberships": allowed}


@router.post("/{lead_ref}/move")
def move_lead(lead_ref: int, body: LeadAudienceChangeBody, request: Request):
    lead = supabase_client.get_lead_by_ref(lead_ref)
    if not lead:
        raise HTTPException(404, "Lead not found")
    # Garante que a persona destino tenha audiences system antes de resolver.
    try:
        supabase_client.ensure_system_audiences_for_persona(body.target_persona_id)
    except Exception:
        pass
    target_audience = _resolve_target_audience(body, request)
    try:
        memberships = supabase_client.get_lead_memberships(lead_ref) or []
    except Exception:
        memberships = []
    for membership in memberships:
        audience = membership.get("audience") or {}
        if audience.get("persona_id"):
            auth_service.assert_persona_access(request, persona_id=audience["persona_id"])
    source_audience = _resolve_source_audience(lead_ref, body)
    if source_audience:
        supabase_client.delete_lead_membership(lead_ref, source_audience["id"])
    supabase_client.ensure_lead_membership(
        lead_ref,
        target_audience["id"],
        membership_type="primary",
        created_by_user_id=auth_service.current_user(request).get("id"),
    )
    # leads.persona_id e legado/default; atualizamos por compatibilidade mas a
    # visibilidade real e a posse operacional vem de memberships.
    supabase_client.update_lead(lead_ref, {"persona_id": body.target_persona_id, "updated_at": datetime.now(timezone.utc).isoformat()})
    supabase_client.insert_event(
        {
            "event_type": "lead_moved",
            "entity_type": "lead",
            "entity_id": str(lead_ref),
            "persona_id": body.target_persona_id,
            "payload": {
                "lead_id": lead_ref,
                "target_audience_id": target_audience["id"],
                "source_audience_id": source_audience.get("id") if source_audience else None,
                "target_persona_id": body.target_persona_id,
                "by_user_id": auth_service.current_user(request).get("id"),
            },
        },
        source="leads.move",
    )
    return {"ok": True, "lead": supabase_client.get_lead_by_ref(lead_ref), "memberships": supabase_client.get_lead_memberships(lead_ref)}


@router.post("/{lead_ref}/share")
def share_lead(lead_ref: int, body: LeadAudienceChangeBody, request: Request):
    lead = supabase_client.get_lead_by_ref(lead_ref)
    if not lead:
        raise HTTPException(404, "Lead not found")
    try:
        supabase_client.ensure_system_audiences_for_persona(body.target_persona_id)
    except Exception:
        pass
    target_audience = _resolve_target_audience(body, request)
    try:
        existing_memberships = supabase_client.get_lead_memberships(lead_ref) or []
    except Exception:
        existing_memberships = []
    if not existing_memberships:
        # Lead canonico ainda nao tem nenhuma audience: cria membership primary
        # automaticamente na audience source da persona atual antes de
        # compartilhar com a nova. Evita 400 desnecessario para leads legados.
        source = _resolve_source_audience(lead_ref, body)
        if not source and lead.get("persona_id"):
            source = supabase_client.ensure_import_audience(lead.get("persona_id"))
        if source:
            supabase_client.ensure_lead_membership(
                lead_ref,
                source["id"],
                membership_type="primary",
                created_by_user_id=auth_service.current_user(request).get("id"),
            )
            existing_memberships = supabase_client.get_lead_memberships(lead_ref) or []
        if not existing_memberships:
            raise HTTPException(400, "Lead precisa pertencer a pelo menos uma audiencia antes de compartilhar")
    for membership in existing_memberships:
        audience = membership.get("audience") or {}
        if audience.get("persona_id"):
            auth_service.assert_persona_access(request, persona_id=audience["persona_id"])
    supabase_client.ensure_lead_membership(
        lead_ref,
        target_audience["id"],
        membership_type="shared",
        created_by_user_id=auth_service.current_user(request).get("id"),
    )
    supabase_client.insert_event(
        {
            "event_type": "lead_shared",
            "entity_type": "lead",
            "entity_id": str(lead_ref),
            "persona_id": body.target_persona_id,
            "payload": {
                "lead_id": lead_ref,
                "target_audience_id": target_audience["id"],
                "target_persona_id": body.target_persona_id,
                "by_user_id": auth_service.current_user(request).get("id"),
            },
        },
        source="leads.share",
    )
    return {"ok": True, "lead": lead, "memberships": supabase_client.get_lead_memberships(lead_ref)}


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

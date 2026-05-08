import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from supabase import create_client, Client
from typing import Optional

_client: Optional[Client] = None
_TRANSIENT_ERROR_MARKERS = (
    "Server disconnected",
    "RemoteProtocolError",
    "ReadError",
    "ConnectError",
    "TimeoutException",
    "Connection reset",
)


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


def _reset_client() -> None:
    global _client
    _client = None


def _is_transient_transport_error(exc: Exception) -> bool:
    text = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


def _execute_with_retry(query, retries: int = 4):
    """Run a PostgREST query with exponential backoff on transient transport errors.

    Supabase Edge / PostgREST occasionally drops connections under load
    ("Server disconnected", "RemoteProtocolError"). Retries with a fresh client
    have proven to recover most of these without operator-visible failure.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return query.execute()
        except Exception as exc:
            last_exc = exc
            if not _is_transient_transport_error(exc) or attempt >= retries:
                raise
            _reset_client()
            # Backoff: 0.25, 0.5, 1.0, 2.0, 4.0 seconds. Caps at ~7.75s total.
            time.sleep(min(0.25 * (2 ** attempt), 4.0))
    if last_exc:
        raise last_exc
    return None


# ── Safe query helpers ─────────────────────────────────────────────────────
# All public functions use _q() / _one() so that:
#   • A None result never causes AttributeError
#   • A missing table returns a safe default instead of a 500

def _q(query) -> list:
    """Execute a list query; return [] on None or any exception."""
    try:
        result = _execute_with_retry(query)
        if result is None:
            return []
        return result.data or []
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"query failed: {exc}", exc)
        except Exception:
            pass
        return []


def _one(query) -> Optional[dict]:
    """Execute a single-row query (maybe_single); return None on error."""
    try:
        result = _execute_with_retry(query)
        if result is None:
            return None
        return result.data
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"query failed: {exc}", exc)
        except Exception:
            pass
        return None


def _insert_one(query) -> dict:
    """Execute an insert and return the first row.

    Re-raises on any database error so callers see the real cause (CHECK violations,
    NOT NULL, FK, etc.) instead of receiving a silent {}. Returns {} only when the
    insert succeeded but PostgREST returned no row data — an anomalous shape that
    callers can recover from via a follow-up lookup.
    """
    try:
        result = _execute_with_retry(query)
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"insert failed: {exc}", exc)
        except Exception:
            pass
        raise
    if result is None or not result.data:
        return {}
    return result.data[0]


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return text.strip("-") or "item"


# ── Leads ──────────────────────────────────────────────────────────────────

def get_lead(lead_id: str) -> Optional[dict]:
    client = get_client()
    try:
        import re as _re
        digits = _re.sub(r"\D", "", lead_id or "")
        if digits and len(digits) <= 10:
            row = _one(client.table("leads").select("*").eq("id", int(digits)).maybe_single())
            if row:
                return row
    except Exception:
        pass
    return _one(client.table("leads").select("*").eq("lead_id", lead_id).maybe_single())


def _resolve_persona_id(persona_slug_or_id: Optional[str]) -> Optional[str]:
    if not persona_slug_or_id:
        return None
    if len(persona_slug_or_id) == 36 and persona_slug_or_id.count("-") == 4:
        return persona_slug_or_id
    persona = get_persona(persona_slug_or_id)
    return persona.get("id") if persona else None


_LEADS_MISSING_COLUMNS: set[str] = set()


def _missing_column_from_error(exc: Exception) -> Optional[str]:
    """Detect PGRST204 'Could not find the X column' and extract column name."""
    text = str(exc)
    if "PGRST204" not in text and "schema cache" not in text:
        return None
    import re as _re
    m = _re.search(r"Could not find the '([^']+)' column", text)
    return m.group(1) if m else None


def _strip_known_missing_columns(payload: dict) -> dict:
    if not _LEADS_MISSING_COLUMNS:
        return payload
    return {k: v for k, v in payload.items() if k not in _LEADS_MISSING_COLUMNS}


def _execute_lead_write(query_factory, payload: dict, *, max_retries: int = 3) -> Optional[dict]:
    """Run a leads INSERT/UPDATE, learning and retrying around missing columns.

    Postgres + PostgREST will reject the whole write when any payload key is
    not in the schema cache (e.g. canal column missing). Instead of swallowing
    silently, we strip the offending column and retry, so the row still lands.
    """
    cleaned = _strip_known_missing_columns(payload)
    last_exc: Exception | None = None
    for _ in range(max_retries):
        try:
            result = _execute_with_retry(query_factory(cleaned))
            return result
        except Exception as exc:
            missing = _missing_column_from_error(exc)
            if not missing or missing not in cleaned:
                last_exc = exc
                break
            _LEADS_MISSING_COLUMNS.add(missing)
            cleaned = {k: v for k, v in cleaned.items() if k != missing}
            last_exc = exc
    if last_exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"lead write failed: {last_exc}", last_exc)
        except Exception:
            pass
    return None


def ensure_lead_for_persona(
    *,
    lead_id: str,
    persona_slug_or_id: Optional[str],
    lead_ref: Optional[int] = None,
    nome: Optional[str] = None,
    stage: Optional[str] = None,
    canal: Optional[str] = None,
    mensagem: Optional[str] = None,
    interesse_produto: Optional[str] = None,
    cidade: Optional[str] = None,
    cep: Optional[str] = None,
    whatsapp_phone_number_id: Optional[str] = None,
) -> Optional[dict]:
    """Ensure an inbound lead is tied to the intended persona branch.

    If an existing lead has no persona, assign it. If it already belongs to a
    different persona and no explicit lead_ref was provided, keep it unchanged
    to avoid moving a real lead between clients by phone/name collision.
    """
    if not lead_id and lead_ref is None:
        return None
    from datetime import datetime, timezone

    client = get_client()
    persona_id = _resolve_persona_id(persona_slug_or_id)
    if not whatsapp_phone_number_id and persona_id:
        whatsapp_phone_number_id = get_default_whatsapp_phone_number_id(persona_id)
    existing = get_lead_by_ref(lead_ref) if lead_ref is not None else get_lead(lead_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    update: dict = {
        "last_update": now_iso,
        "updated_at": now_iso,
    }
    if nome:
        update["nome"] = nome
    if stage:
        update["stage"] = stage
    if canal:
        update["canal"] = canal
        # Mirror canal into origem so dashboards filtering by source still
        # work even when the canal column is absent in the schema cache.
        update.setdefault("origem", canal)
    if mensagem:
        update["ultima_mensagem"] = mensagem
    if interesse_produto:
        update["interesse_produto"] = interesse_produto
    if cidade:
        update["cidade"] = cidade
    if cep:
        update["cep"] = cep
    if whatsapp_phone_number_id:
        update["whatsapp_phone_number_id"] = whatsapp_phone_number_id
    if lead_id:
        update["lead_id"] = lead_id
        digits = "".join(ch for ch in lead_id if ch.isdigit())
        if digits:
            update["telefone"] = digits

    if existing:
        current_persona = existing.get("persona_id")
        if persona_id and (not current_persona or lead_ref is not None or current_persona == persona_id):
            update["persona_id"] = persona_id
        elif current_persona and persona_id and current_persona != persona_id:
            update = {k: v for k, v in update.items() if k in {"last_update", "updated_at", "ultima_mensagem"}}
        result = _execute_lead_write(
            lambda payload: client.table("leads").update(payload).eq("id", existing["id"]),
            update,
        )
        if result and getattr(result, "data", None):
            return (result.data or [{**existing, **update}])[0]
        return {**existing, **_strip_known_missing_columns(update)}

    payload = {
        **update,
        "lead_id": lead_id,
        "nome": nome,
        "stage": stage or "novo",
        "canal": canal or "whatsapp",
        "persona_id": persona_id,
        "ai_enabled": True,
        "created_at": now_iso,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    payload.setdefault("origem", payload.get("canal"))
    result = _execute_lead_write(
        lambda body: client.table("leads").insert(body),
        payload,
    )
    if result and getattr(result, "data", None):
        return result.data[0]
    return None


def get_leads(persona_slug: Optional[str] = None, limit: int = 100, offset: int = 0) -> list:
    try:
        q = get_client().table("leads").select("*").order("updated_at", desc=True).range(offset, offset + limit - 1)
        if persona_slug:
            persona_id = _resolve_persona_id(persona_slug) or persona_slug
            q = q.eq("persona_id", persona_id)
        return _q(q)
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"get_leads failed: {exc}", exc)
        except Exception:
            pass
        return []


def get_leads_for_persona_ids(persona_ids: list[str], limit: int = 100, offset: int = 0) -> list:
    ids = [pid for pid in persona_ids if pid]
    if not ids:
        return []
    try:
        q = (
            get_client()
            .table("leads")
            .select("*")
            .in_("persona_id", ids)
            .order("updated_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        return _q(q)
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"get_leads_for_persona_ids failed: {exc}", exc)
        except Exception:
            pass
        return []


def update_lead(lead_ref: int, data: dict) -> None:
    _execute_with_retry(get_client().table("leads").update(data).eq("id", lead_ref))


def get_lead_by_ref(lead_ref: int) -> Optional[dict]:
    """Fetch a lead row by its integer primary key (`leads.id`)."""
    return _one(get_client().table("leads").select("*").eq("id", lead_ref).maybe_single())


def get_audiences(persona_id: Optional[str] = None) -> list[dict]:
    q = get_client().table("audiences").select("*").order("is_system").order("name")
    if persona_id:
        q = q.eq("persona_id", persona_id)
    return _q(q)


def get_audience(audience_id: str) -> Optional[dict]:
    return _one(get_client().table("audiences").select("*").eq("id", audience_id).maybe_single())


def get_audience_by_slug(persona_id: str, audience_slug: str) -> Optional[dict]:
    if not persona_id or not audience_slug:
        return None
    return _one(
        get_client()
        .table("audiences")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("slug", audience_slug)
        .maybe_single()
    )


def create_audience(data: dict) -> dict:
    payload = {
        "persona_id": data.get("persona_id"),
        "slug": _slugify(data.get("slug") or data.get("name") or "audience"),
        "name": data.get("name") or "Audience",
        "description": data.get("description"),
        "source_type": data.get("source_type") or "manual",
        "is_system": bool(data.get("is_system", False)),
        "created_by_user_id": data.get("created_by_user_id"),
    }
    return _insert_one(get_client().table("audiences").insert(payload))


def update_audience(audience_id: str, data: dict) -> Optional[dict]:
    payload = {
        "name": data.get("name"),
        "description": data.get("description"),
        "updated_at": data.get("updated_at"),
    }
    if data.get("slug"):
        payload["slug"] = _slugify(data["slug"])
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        return get_audience(audience_id)
    result = _execute_with_retry(get_client().table("audiences").update(payload).eq("id", audience_id))
    return (result.data or [None])[0] if result else None


def ensure_system_audience(
    persona_id: str,
    *,
    slug: str,
    name: str,
    description: Optional[str] = None,
    source_type: str = "manual",
    created_by_user_id: Optional[str] = None,
) -> Optional[dict]:
    existing = get_audience_by_slug(persona_id, slug)
    payload = {
        "persona_id": persona_id,
        "slug": _slugify(slug),
        "name": name,
        "description": description,
        "source_type": source_type,
        "is_system": True,
        "created_by_user_id": created_by_user_id,
    }
    if existing:
        return update_audience(existing["id"], payload) or {**existing, **payload}
    return create_audience(payload)


def ensure_import_audience(persona_id: str, created_by_user_id: Optional[str] = None) -> Optional[dict]:
    return ensure_system_audience(
        persona_id,
        slug="import",
        name="Import",
        description="Audience padrao para todos os imports CSV/Bulk da persona.",
        source_type="import",
        created_by_user_id=created_by_user_id,
    )


def ensure_system_audiences_for_persona(
    persona_id: Optional[str],
    *,
    created_by_user_id: Optional[str] = None,
) -> dict:
    """Garante que a persona tenha as audiences system padrao.

    Idempotente: pode ser chamado em qualquer entrypoint (listagem, move,
    share, login) sem efeito colateral alem de criar a `import` audience caso
    nao exista. Devolve {'import': <audience_dict_or_None>}.

    Falhas sao silenciadas para que um problema na criacao da audience nao
    derrube o endpoint chamador. Endpoints continuam funcionando com lista
    vazia de audiences caso a criacao falhe.
    """
    if not persona_id:
        return {"import": None}
    try:
        imp = ensure_import_audience(persona_id, created_by_user_id=created_by_user_id)
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.warn("supabase_client", f"ensure_system_audiences_for_persona failed: {exc}", exc)
        except Exception:
            pass
        imp = None
    return {"import": imp}


def get_lead_memberships(lead_id: int) -> list[dict]:
    rows = _q(
        get_client()
        .table("lead_audience_memberships")
        .select("id,lead_id,audience_id,membership_type,created_by_user_id,created_at")
        .eq("lead_id", lead_id)
        .order("created_at")
    )
    if not rows:
        return []
    audience_ids = [row.get("audience_id") for row in rows if row.get("audience_id")]
    audiences_by_id = (
        {
            row.get("id"): row
            for row in _q(get_client().table("audiences").select("*").in_("id", audience_ids))
        }
        if audience_ids
        else {}
    )
    return [{**row, "audience": audiences_by_id.get(row.get("audience_id"))} for row in rows]


def ensure_lead_membership(
    lead_id: int,
    audience_id: str,
    *,
    membership_type: str = "primary",
    created_by_user_id: Optional[str] = None,
) -> Optional[dict]:
    if not lead_id or not audience_id:
        return None
    payload = {
        "lead_id": lead_id,
        "audience_id": audience_id,
        "membership_type": membership_type,
        "created_by_user_id": created_by_user_id,
    }
    result = _execute_with_retry(
        get_client().table("lead_audience_memberships").upsert(payload, on_conflict="lead_id,audience_id")
    )
    return (result.data or [payload])[0] if result else payload


def delete_lead_membership(lead_id: int, audience_id: str) -> None:
    _execute_with_retry(
        get_client().table("lead_audience_memberships").delete().eq("lead_id", lead_id).eq("audience_id", audience_id)
    )


def lead_has_membership(lead_id: int, persona_id: str, audience_id: Optional[str] = None) -> bool:
    rows = _q(
        get_client()
        .table("lead_audience_memberships")
        .select("lead_id,audience_id")
        .eq("lead_id", lead_id)
        .limit(500)
    )
    if not rows:
        return False
    audience_ids = [row.get("audience_id") for row in rows if row.get("audience_id")]
    if not audience_ids:
        return False
    audience_q = get_client().table("audiences").select("id").in_("id", audience_ids).eq("persona_id", persona_id)
    if audience_id:
        audience_q = audience_q.eq("id", audience_id)
    return bool(_q(audience_q.limit(1)))


def _audience_ids_for_persona(persona_id: str, audience_id: Optional[str] = None, audience_slug: Optional[str] = None) -> list[str]:
    if audience_id:
        audience = get_audience(audience_id)
        return [audience["id"]] if audience and audience.get("persona_id") == persona_id else []
    if audience_slug:
        audience = get_audience_by_slug(persona_id, audience_slug)
        return [audience["id"]] if audience else []
    rows = _q(get_client().table("audiences").select("id").eq("persona_id", persona_id))
    return [row.get("id") for row in rows if row.get("id")]


def get_lead_refs_for_audience_scope(
    *,
    persona_id: str,
    audience_id: Optional[str] = None,
    audience_slug: Optional[str] = None,
) -> list[int]:
    audience_ids = _audience_ids_for_persona(persona_id, audience_id=audience_id, audience_slug=audience_slug)
    if not audience_ids:
        return []
    rows = _q(
        get_client()
        .table("lead_audience_memberships")
        .select("lead_id")
        .in_("audience_id", audience_ids)
        .limit(5000)
    )
    return sorted({int(row["lead_id"]) for row in rows if row.get("lead_id") is not None})


def get_leads_for_audience_scope(
    *,
    persona_id: str,
    audience_id: Optional[str] = None,
    audience_slug: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    lead_refs = get_lead_refs_for_audience_scope(persona_id=persona_id, audience_id=audience_id, audience_slug=audience_slug)
    if not lead_refs:
        return []
    page_refs = lead_refs[offset: offset + limit]
    if not page_refs:
        return []
    rows = _q(
        get_client()
        .table("leads")
        .select("*")
        .in_("id", page_refs)
        .order("updated_at", desc=True)
    )
    memberships_map = {lead_id: get_lead_memberships(lead_id) for lead_id in page_refs}
    return [{**row, "memberships": memberships_map.get(row.get("id"), [])} for row in rows]


# ── Messages ───────────────────────────────────────────────────────────────

def get_messages(lead_id: str, limit: int = 30) -> list:
    """
    Fetch messages for a lead, ordered ascending (chronological chat order).
    Primary key: lead_ref (integer) — the messages table has NO lead_id column.
    Accepts either the integer id as string ("117") or a nome string as fallback.
    """
    client = get_client()

    # Primary: lead_ref (integer) — strip non-digits and cast
    try:
        import re as _re
        digits = _re.sub(r"\D", "", lead_id or "")
        # Only use digits if they look like an integer DB id (not a phone number > 12 digits)
        if digits and len(digits) <= 10:
            rows = _q(
                client.table("messages")
                .select("*")
                .eq("lead_ref", int(digits))
                .order("created_at", desc=False)
                .order("id", desc=False)
                .limit(limit)
            )
            if rows:
                return _sort_messages_for_chat(rows)
    except Exception:
        pass

    # Fallback: filter by nome if a name string was passed
    if lead_id and not lead_id.isdigit():
        rows = _q(
            client.table("messages")
            .select("*")
            .eq("nome", lead_id)
            .order("created_at", desc=False)
            .order("id", desc=False)
            .limit(limit)
        )
        return _sort_messages_for_chat(rows)

    return []


def _sort_messages_for_chat(rows: list) -> list:
    """Return chat messages in human-readable order.

    Some WhatsApp/n8n flows persist the assistant reply row milliseconds
    before the inbound row that triggered it. Those rows share the same
    WhatsApp id, with the reply stored as `ai_reply.<wamid>`. For display and
    API consumers, the inbound message must come before its generated reply.
    """
    from datetime import datetime

    def parse_ts(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    base_by_message_id = {
        row.get("message_id"): row
        for row in rows
        if row.get("message_id") and not str(row.get("message_id")).startswith("ai_reply.")
    }

    def row_id(row: dict) -> int:
        try:
            return int(row.get("id") or 0)
        except Exception:
            return 0

    def key(row: dict):
        message_id = str(row.get("message_id") or "")
        own_ts = parse_ts(row.get("created_at"))
        own_id = row_id(row)
        if message_id.startswith("ai_reply."):
            base = base_by_message_id.get(message_id.removeprefix("ai_reply."))
            if base:
                return (parse_ts(base.get("created_at")), row_id(base), 1, own_ts, own_id)
        return (own_ts, own_id, 0, own_ts, own_id)

    return sorted(rows, key=key)


def get_recent_messages(hours: int = 24, limit: int = 500, persona_id: Optional[str] = None, lead_refs: Optional[list[int]] = None) -> list:
    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    client = get_client()
    q = (
        client.table("messages")
        .select("*")
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if lead_refs is not None:
        if not lead_refs:
            return []
        q = q.in_("lead_ref", lead_refs)
    elif persona_id:
        leads = _q(
            client.table("leads")
            .select("id")
            .eq("persona_id", persona_id)
        )
        lead_refs = [lead.get("id") for lead in leads if lead.get("id") is not None]
        if not lead_refs:
            return []
        q = q.in_("lead_ref", lead_refs)
    return _q(q)


def get_conversations(hours: int = 168, limit: int = 1000, persona_id: Optional[str] = None, lead_refs: Optional[list[int]] = None) -> list:
    """
    Returns the last message per unique conversation.

    lead_ref is the canonical conversation key. Names are only a fallback for
    orphan messages because the same contact name can exist under different
    personas.
    """
    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    client = get_client()
    messages_q = (
        client.table("messages")
        .select("id,nome,lead_ref,Lead_Stage,texto,created_at,direction,sender_type,status")
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if lead_refs is not None:
        if not lead_refs:
            return []
        messages_q = messages_q.in_("lead_ref", lead_refs)
    rows = _q(messages_q)
    # Group by conversation key (nome → lead_ref → lead_id), keep latest message
    lead_refs = sorted({row.get("lead_ref") for row in rows if row.get("lead_ref") is not None})
    leads_by_ref: dict = {}
    for idx in range(0, len(lead_refs), 200):
        chunk = lead_refs[idx:idx + 200]
        for lead in _q(
            client.table("leads")
            .select("id,lead_id,nome,persona_id,stage,interesse_produto")
            .in_("id", chunk)
        ):
            leads_by_ref[lead.get("id")] = lead

    known_lead_names = {
        (lead.get("nome") or "").strip().lower()
        for lead in leads_by_ref.values()
        if lead.get("nome")
    }
    seen: dict = {}
    for row in rows:
        lead_ref = row.get("lead_ref")
        lead = leads_by_ref.get(lead_ref) or {}
        if persona_id and lead.get("persona_id") != persona_id and lead_refs is None:
            continue
        row_name = (row.get("nome") or "").strip()
        if lead_ref is None and row_name.lower() in known_lead_names:
            continue
        key = f"lead:{lead_ref}" if lead_ref is not None else (row.get("nome") or "unknown")
        if key not in seen:
            seen[key] = {
                "key": key,
                "nome": lead.get("nome") or row.get("nome") or key,
                "lead_id": lead.get("lead_id"),
                "lead_ref": lead_ref,
                "persona_id": lead.get("persona_id"),
                "interesse_produto": lead.get("interesse_produto"),
                "Lead_Stage": row.get("Lead_Stage") or lead.get("stage") or "novo",
                "last_message": row.get("texto") or "",
                "last_direction": row.get("direction") or "",
                "last_sender_type": row.get("sender_type") or "",
                "last_at": row.get("created_at") or "",
            }
    return list(seen.values())


def insert_message(data: dict) -> None:
    _execute_with_retry(get_client().table("messages").insert(data))


# ── Knowledge Graph: nodes & edges (migration 008) ────────────────────────
# All functions are defensive: missing tables (e.g., migration 008 not applied)
# return safe defaults so the rest of the system keeps working.

_KG_TABLES_MISSING = False  # flipped to True on PGRST205 to short-circuit


def _kg_unavailable(exc: Exception) -> bool:
    """Detect 'table not found' from PostgREST/Supabase, regardless of message wording."""
    text = str(exc)
    return (
        "knowledge_nodes" in text or "knowledge_edges" in text
    ) and ("PGRST205" in text or "schema cache" in text or "Could not find the table" in text)


def _unique_violation(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "duplicate key value violates unique constraint" in text
        or "unique constraint" in text
        or "23505" in text
    )


def upsert_knowledge_node(data: dict) -> Optional[dict]:
    """Idempotent upsert of a knowledge node, keyed by (persona_id, node_type, slug).

    `data` should at minimum contain node_type, slug, title.
    Returns the inserted/updated row, or None if the table is missing.
    """
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING:
        return None
    from datetime import datetime, timezone

    required = {"node_type", "slug", "title"}
    if not required.issubset(data.keys()):
        raise ValueError(f"upsert_knowledge_node missing keys: {required - set(data.keys())}")

    client = get_client()
    persona_id = data.get("persona_id")
    try:
        q = (
            client.table("knowledge_nodes")
            .select("id,metadata,tags,summary,title,status")
            .eq("node_type", data["node_type"])
            .eq("slug", data["slug"])
        )
        q = q.eq("persona_id", persona_id) if persona_id else q.is_("persona_id", "null")
        existing = (q.limit(1).execute().data or [None])[0]
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        if _unique_violation(exc):
            # Parallel approvals can race between the select and insert.
            # Treat the duplicate as a successful idempotent upsert.
            q = (
                client.table("knowledge_nodes")
                .select("*")
                .eq("node_type", data["node_type"])
                .eq("slug", data["slug"])
            )
            q = q.eq("persona_id", persona_id) if persona_id else q.is_("persona_id", "null")
            existing = (q.limit(1).execute().data or [None])[0]
            if existing:
                return existing
        raise

    now_iso = datetime.now(timezone.utc).isoformat()
    if existing:
        # Merge tags & metadata to keep prior context.
        merged_tags = sorted(set((existing.get("tags") or []) + (data.get("tags") or [])))
        merged_meta = {**(existing.get("metadata") or {}), **(data.get("metadata") or {})}
        update = {
            "title":    data.get("title") or existing.get("title"),
            "summary":  data.get("summary") or existing.get("summary"),
            "tags":     merged_tags,
            "metadata": merged_meta,
            "status":   data.get("status") or existing.get("status") or "active",
            "updated_at": now_iso,
        }
        if data.get("source_table"):
            update["source_table"] = data["source_table"]
        if data.get("source_id"):
            update["source_id"] = data["source_id"]
        for field in ("level", "importance", "confidence"):
            if data.get(field) is not None:
                update[field] = data[field]
        try:
            r = client.table("knowledge_nodes").update(update).eq("id", existing["id"]).execute()
            return (r.data or [{**existing, **update}])[0]
        except Exception as exc:
            if _kg_unavailable(exc):
                _KG_TABLES_MISSING = True
                return None
            raise

    payload = dict(data)
    payload.setdefault("tags", [])
    payload.setdefault("metadata", {})
    payload.setdefault("status", "active")
    payload["created_at"] = now_iso
    payload["updated_at"] = now_iso
    try:
        r = client.table("knowledge_nodes").insert(payload).execute()
        return (r.data or [{}])[0]
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        if _unique_violation(exc):
            q = (
                client.table("knowledge_nodes")
                .select("*")
                .eq("node_type", data["node_type"])
                .eq("slug", data["slug"])
            )
            q = q.eq("persona_id", persona_id) if persona_id else q.is_("persona_id", "null")
            existing = (q.limit(1).execute().data or [None])[0]
            if existing:
                return existing
        raise


def get_knowledge_node(node_id: str) -> Optional[dict]:
    """Fetch a single knowledge node by UUID."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not node_id:
        return None
    try:
        return _one(get_client().table("knowledge_nodes").select("*").eq("id", node_id).maybe_single())
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def update_knowledge_node(node_id: str, data: dict) -> Optional[dict]:
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not node_id or not data:
        return None
    try:
        result = get_client().table("knowledge_nodes").update(data).eq("id", node_id).execute()
        return (result.data or [data])[0]
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def ensure_persona_knowledge_node(persona_id: str) -> Optional[dict]:
    """Ensure the graph has a protected semantic root for a persona."""
    if not persona_id:
        return None
    persona = None
    try:
        persona = _one(get_client().table("personas").select("id,slug,name").eq("id", persona_id).maybe_single())
    except Exception:
        persona = None
    return upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "persona",
        "slug": "self",
        "title": (persona or {}).get("name") or "Persona",
        "summary": "Raiz protegida da persona no grafo.",
        "tags": ["persona"],
        "metadata": {"role": "root", "protected": True},
        "status": "active",
        "level": 0,
        "importance": 1.0,
        "confidence": 1.0,
    })


def ensure_gallery_node(persona_id: str) -> Optional[dict]:
    """Ensure a protected Gallery node exists for a persona."""
    if not persona_id:
        return None
    return upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "gallery",
        "slug": "gallery-default",
        "title": "Gallery",
        "summary": "Bloco protegido para materiais visuais. Nodes ligados aqui aparecem em Assets.",
        "tags": ["gallery", "assets", "visual"],
        "metadata": {
            "protected": True,
            "system_node": True,
            "asset_scope": "visual_media",
            "open_url": "/marketing/assets",
        },
        "status": "active",
        "level": 112,
        "importance": 0.82,
        "confidence": 1.0,
    })


def sync_audience_node(audience: dict) -> Optional[dict]:
    if not audience or not audience.get("persona_id") or not audience.get("id"):
        return None
    persona = get_persona_by_id(audience["persona_id"]) or {}
    node = upsert_knowledge_node({
        "persona_id": audience["persona_id"],
        "source_table": "audiences",
        "source_id": audience["id"],
        "node_type": "audience",
        "slug": audience.get("slug") or _slugify(audience.get("name") or "audience"),
        "title": audience.get("name") or "Audience",
        "summary": audience.get("description") or "Publico ou grupo operacional de leads.",
        "tags": ["audience", audience.get("source_type") or "manual"],
        "metadata": {
            "audience_id": audience.get("id"),
            "audience_slug": audience.get("slug"),
            "source_type": audience.get("source_type"),
            "is_system": audience.get("is_system"),
            "open_url": f"/leads?audience={audience.get('slug', '')}",
            "persona_slug": persona.get("slug"),
        },
        "status": "active",
        "level": 55,
        "importance": 0.72,
        "confidence": 1.0,
    })
    # Lazy import to avoid circular dependency between supabase_client and knowledge_graph
    from services import knowledge_graph as _kg
    persona_root = _kg._ensure_persona_root(audience["persona_id"])
    if node and persona_root:
        upsert_knowledge_edge(
            source_node_id=persona_root["id"],
            target_node_id=node["id"],
            relation_type="contains",
            persona_id=audience["persona_id"],
            weight=1,
            metadata={"primary_tree": True, "created_from": "audiences"},
        )
    return node


def ensure_embedded_node(persona_id: str) -> Optional[dict]:
    """Ensure a protected Embedded/Golden Dataset destination node exists for a persona."""
    if not persona_id:
        return None
    return upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "embedded",
        "slug": "embedded-default",
        "title": "Embedded",
        "summary": "Destino protegido para FAQs publicados no Golden Dataset e enviados ao RAG.",
        "tags": ["rag", "embedded", "golden-dataset", "default"],
        "metadata": {
            "protected": True,
            "system_node": True,
            "rag_index": "default",
            "open_url": "/kb",
        },
        "status": "active",
        "level": 120,
        "importance": 0.78,
        "confidence": 1.0,
    })


def _edge_is_inactive(edge: dict | None) -> bool:
    metadata = (edge or {}).get("metadata") or {}
    return metadata.get("active") is False


def _primary_tree_metadata(metadata: Optional[dict]) -> dict:
    merged = dict(metadata or {})
    merged["primary_tree"] = True
    merged["active"] = True
    merged.pop("deleted_at", None)
    merged.pop("deleted_from", None)
    return merged


def upsert_knowledge_edge(
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    persona_id: Optional[str] = None,
    weight: float = 1.0,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Idempotent upsert keyed by (source_node_id, target_node_id, relation_type).

    Existing soft-deleted edges are reactivated. For primary tree paths, this
    also deactivates any previous active primary path pointing at the target.
    """
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING:
        return None
    if not source_node_id or not target_node_id or not relation_type:
        return None
    if source_node_id == target_node_id:
        return None  # don't allow self-loops

    client = get_client()
    try:
        existing_q = (
            client.table("knowledge_edges")
            .select("*")
            .eq("source_node_id", source_node_id)
            .eq("target_node_id", target_node_id)
            .eq("relation_type", relation_type)
            .limit(1)
            .execute()
        )
        existing = (existing_q.data or [None])[0]
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        if _unique_violation(exc):
            existing_q = (
                client.table("knowledge_edges")
                .select("*")
                .eq("source_node_id", source_node_id)
                .eq("target_node_id", target_node_id)
                .eq("relation_type", relation_type)
                .limit(1)
                .execute()
            )
            existing = (existing_q.data or [None])[0]
            if existing:
                return existing
        raise

    requested_metadata = dict(metadata or {})
    is_primary_path = requested_metadata.get("primary_tree") is True

    if is_primary_path:
        deactivate_primary_paths_for_target(target_node_id, except_source_node_id=source_node_id)

    if existing:
        update_data = {
            "persona_id": persona_id,
            "weight": weight,
            "metadata": _primary_tree_metadata(requested_metadata) if is_primary_path else {**(existing.get("metadata") or {}), **requested_metadata, "active": True},
        }
        r = client.table("knowledge_edges").update(update_data).eq("id", existing["id"]).execute()
        return (r.data or [{**existing, **update_data}])[0]
    try:
        insert_metadata = _primary_tree_metadata(requested_metadata) if is_primary_path else requested_metadata
        r = client.table("knowledge_edges").insert({
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": insert_metadata,
        }).execute()
        return (r.data or [{}])[0]
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def deactivate_primary_paths_for_target(target_node_id: str, except_source_node_id: Optional[str] = None) -> int:
    """Soft-disable active primary-tree paths to a target node."""
    if _KG_TABLES_MISSING or not target_node_id:
        return 0
    from datetime import datetime, timezone

    client = get_client()
    rows = _q(
        client.table("knowledge_edges")
        .select("id,source_node_id,metadata")
        .eq("target_node_id", target_node_id)
        .limit(500)
    )
    changed = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for row in rows:
        metadata = row.get("metadata") or {}
        if row.get("source_node_id") == except_source_node_id:
            continue
        if metadata.get("primary_tree") is not True or metadata.get("active") is False:
            continue
        next_metadata = {
            **metadata,
            "active": False,
            "deleted_at": now_iso,
            "deleted_from": "graph_ui_reparent",
        }
        _execute_with_retry(
            client.table("knowledge_edges").update({"metadata": next_metadata}).eq("id", row["id"])
        )
        changed += 1
    return changed


def delete_knowledge_edge(edge_id: str) -> bool:
    """Soft-delete a knowledge edge by id. Returns True when the request succeeds."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not edge_id:
        return False
    from datetime import datetime, timezone

    try:
        client = get_client()
        row = _one(client.table("knowledge_edges").select("*").eq("id", edge_id).maybe_single())
        if not row:
            return False
        metadata = row.get("metadata") or {}
        metadata = {
            **metadata,
            "active": False,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "deleted_from": "graph_ui",
        }
        _execute_with_retry(client.table("knowledge_edges").update({"metadata": metadata}).eq("id", edge_id))
        if row.get("relation_type") == "gallery_asset":
            mark_gallery_asset_inactive_by_edge(edge_id)
        return True
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return False
        raise


def get_knowledge_edge(edge_id: str) -> Optional[dict]:
    if not edge_id:
        return None
    return _one(get_client().table("knowledge_edges").select("*").eq("id", edge_id).maybe_single())


def get_knowledge_node_for_source(
    source_table: str,
    source_id: str,
    *,
    persona_id: Optional[str] = None,
) -> Optional[dict]:
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not source_table or not source_id:
        return None
    try:
        q = (
            get_client().table("knowledge_nodes")
            .select("*")
            .eq("source_table", source_table)
            .eq("source_id", source_id)
        )
        if persona_id:
            q = q.eq("persona_id", persona_id)
        return _one(q.maybe_single())
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def get_knowledge_node_by_slug(
    slug: str,
    *,
    persona_id: Optional[str] = None,
    node_type: Optional[str] = None,
) -> Optional[dict]:
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not slug:
        return None
    try:
        q = get_client().table("knowledge_nodes").select("*").eq("slug", slug)
        if persona_id:
            q = q.eq("persona_id", persona_id)
        if node_type:
            q = q.eq("node_type", node_type)
        rows = _q(q.limit(20))
        for row in rows:
            if row.get("status") != "deleted":
                return row
        return rows[0] if rows else None
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def get_knowledge_edge_between(
    source_node_id: str,
    target_node_id: str,
    *,
    relation_type: Optional[str] = None,
) -> Optional[dict]:
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not source_node_id or not target_node_id:
        return None
    try:
        q = (
            get_client().table("knowledge_edges")
            .select("*")
            .eq("source_node_id", source_node_id)
            .eq("target_node_id", target_node_id)
        )
        if relation_type:
            q = q.eq("relation_type", relation_type)
        rows = _q(q.limit(5))
        for row in rows:
            if not _edge_is_inactive(row):
                return row
        return rows[0] if rows else None
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def delete_knowledge_node(node_id: str) -> bool:
    """Delete a knowledge node and its graph edges by id."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not node_id:
        return False
    client = get_client()
    try:
        node = _one(client.table("knowledge_nodes").select("id,node_type,metadata").eq("id", node_id).maybe_single())
        metadata = (node or {}).get("metadata") or {}
        if (node or {}).get("node_type") in {"persona", "embedded", "gallery"} or metadata.get("protected") is True:
            return False
        _execute_with_retry(client.table("knowledge_edges").delete().eq("source_node_id", node_id))
        _execute_with_retry(client.table("knowledge_edges").delete().eq("target_node_id", node_id))
        _execute_with_retry(client.table("knowledge_nodes").delete().eq("id", node_id))
        return True
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return False
        raise


def find_knowledge_nodes(
    term: str,
    persona_id: Optional[str] = None,
    node_types: Optional[list[str]] = None,
    limit: int = 25,
) -> list[dict]:
    """Find nodes by slug, title (ILIKE), or tags membership.

    Defensive: returns [] when the table is missing or any error occurs.
    """
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING:
        return []
    if not term:
        return []
    client = get_client()
    norm = term.strip().lower()
    slug_norm = norm.replace(" ", "-")
    try:
        # Match by exact slug, then loosen by title/tags if needed.
        q = client.table("knowledge_nodes").select("*").limit(limit)
        if persona_id:
            q = q.eq("persona_id", persona_id)
        if node_types:
            q = q.in_("node_type", node_types)
        # PostgREST `or_` filter — slug exact match | title ILIKE | tag contains
        or_clause = f"slug.eq.{slug_norm},title.ilike.*{norm}*,tags.cs.{{{norm}}}"
        rows = q.or_(or_clause).execute().data or []
        return rows
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return []
        return []


def get_knowledge_neighbors(
    node_ids: list[str],
    max_edges: int = 200,
) -> tuple[list[dict], list[dict]]:
    """Return (nodes, edges) within 1 hop of the given node ids.

    Includes the seed nodes themselves. Edges are deduplicated.
    """
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not node_ids:
        return [], []
    client = get_client()
    seed_ids = list({n for n in node_ids if n})
    try:
        edges_out = (
            client.table("knowledge_edges").select("*")
            .in_("source_node_id", seed_ids).limit(max_edges).execute().data or []
        )
        edges_in = (
            client.table("knowledge_edges").select("*")
            .in_("target_node_id", seed_ids).limit(max_edges).execute().data or []
        )
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
        return [], []

    edges: dict[str, dict] = {}
    related_ids: set[str] = set(seed_ids)
    for e in [*edges_out, *edges_in]:
        if _edge_is_inactive(e):
            continue
        edges[e["id"]] = e
        related_ids.add(e["source_node_id"])
        related_ids.add(e["target_node_id"])

    try:
        nodes = (
            client.table("knowledge_nodes").select("*")
            .in_("id", list(related_ids)).execute().data or []
        )
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
        return [], []

    return nodes, list(edges.values())


def list_knowledge_nodes_by_type(
    node_types: list[str],
    persona_id: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Helper used by chat-context: enumerate canonical product/campaign nodes
    so we can detect mentions in free-form lead text without an LLM call."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING:
        return []
    client = get_client()
    try:
        q = client.table("knowledge_nodes").select("id,slug,title,node_type,tags,metadata,persona_id").in_("node_type", node_types).limit(limit)
        if persona_id:
            q = q.eq("persona_id", persona_id)
        return q.execute().data or []
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
        return []


def list_all_knowledge_graph(persona_id: Optional[str] = None, limit_nodes: int = 1500) -> tuple[list[dict], list[dict]]:
    """Return all nodes + edges (optionally scoped to persona). Used by /knowledge/graph-data."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING:
        return [], []
    client = get_client()
    try:
        nq = client.table("knowledge_nodes").select("*").limit(limit_nodes)
        if persona_id:
            nq = nq.eq("persona_id", persona_id)
        nodes = nq.execute().data or []
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
        return [], []
    if not nodes:
        return [], []
    node_ids = [n["id"] for n in nodes]
    try:
        eq_in_source = client.table("knowledge_edges").select("*").in_("source_node_id", node_ids).limit(5000).execute().data or []
    except Exception:
        eq_in_source = []
    active_edges = [edge for edge in eq_in_source if not _edge_is_inactive(edge)]
    return nodes, active_edges


def _asset_table_unavailable(exc: Exception) -> bool:
    text = str(exc)
    return "assets" in text and ("PGRST205" in text or "schema cache" in text or "Could not find" in text)


def sync_gallery_asset_node(node: dict, edge: dict) -> Optional[dict]:
    """Mirror a Gallery-linked knowledge node into the existing assets table."""
    if not node or not edge:
        return None
    client = get_client()
    metadata = node.get("metadata") or {}
    node_type = (node.get("node_type") or "").lower()
    file_path = metadata.get("file_path") or metadata.get("path") or metadata.get("url")
    ext = str(file_path).rsplit(".", 1)[-1].lower() if file_path and "." in str(file_path) else ""
    asset_type = metadata.get("asset_type") or ("gallery_node" if node_type != "asset" else "asset")
    platform_type = "image" if ext in {"png", "jpg", "jpeg", "svg", "gif", "webp"} else ("campaign" if node_type == "campaign" else "template")
    payload = {
        "persona_id": node.get("persona_id") or edge.get("persona_id"),
        "type": platform_type,
        "name": node.get("title") or node.get("slug") or "Gallery asset",
        "url": metadata.get("url") if metadata.get("url") else None,
        "metadata": {
            **metadata,
            "knowledge_node_id": node.get("id"),
            "knowledge_edge_id": edge.get("id"),
            "source_table": node.get("source_table"),
            "source_id": node.get("source_id"),
            "node_type": node_type,
            "file_path": file_path,
            "gallery_active": True,
        },
        "source": "imported",
        "asset_type": asset_type,
        "asset_function": metadata.get("asset_function") or "gallery_reference",
        "tags": node.get("tags") or [],
        "description": node.get("summary"),
        "embedding_status": "none",
        "approval_status": "approved",
        "knowledge_node_id": node.get("id"),
        "gallery_edge_id": edge.get("id"),
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        existing = _one(client.table("assets").select("id").eq("knowledge_node_id", node.get("id")).maybe_single())
        if existing:
            result = _execute_with_retry(client.table("assets").update(payload).eq("id", existing["id"]))
        else:
            result = _execute_with_retry(client.table("assets").insert(payload))
        return (result.data or [payload])[0]
    except Exception as exc:
        if _asset_table_unavailable(exc):
            return None
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"sync_gallery_asset_node failed: {exc}", exc)
        except Exception:
            pass
        return None


def _faq_publication_payload(node: dict, item: Optional[dict], edge: Optional[dict] = None) -> dict:
    metadata = node.get("metadata") or {}
    question = (
        metadata.get("question")
        or (item or {}).get("title")
        or node.get("title")
        or node.get("slug")
        or "FAQ"
    )
    answer = (
        metadata.get("answer")
        or (item or {}).get("content")
        or node.get("summary")
        or metadata.get("content")
        or metadata.get("description")
        or question
    )
    file_path = normalize_file_path(
        (item or {}).get("file_path")
        or metadata.get("file_path")
        or metadata.get("path")
        or metadata.get("url")
    )
    path_slugs = []
    for value in (
        (item or {}).get("metadata", {}).get("path_slugs"),
        metadata.get("path_slugs"),
    ):
        if isinstance(value, list) and value:
            path_slugs = [str(v) for v in value if v]
            break
    return {
        "question": question,
        "answer": answer,
        "title": question,
        "content": answer,
        "file_path": file_path,
        "path_slugs": path_slugs,
        "tags": (item or {}).get("tags") or node.get("tags") or [],
        "persona_id": (edge or {}).get("persona_id") or node.get("persona_id") or (item or {}).get("persona_id"),
    }


def sync_embedded_kb_node(node: dict, edge: dict) -> Optional[dict]:
    """Publish an Embedded-linked FAQ into the Golden Dataset + RAG tables."""
    if not node or not edge:
        return None
    from datetime import datetime, timezone
    import hashlib

    persona_id = edge.get("persona_id") or node.get("persona_id")
    if not persona_id:
        return None
    metadata = node.get("metadata") or {}
    source_table = node.get("source_table")
    source_id = node.get("source_id")

    item = None
    if source_table == "knowledge_items" and source_id:
        try:
            item = get_knowledge_item(source_id)
        except Exception:
            item = None

    node_type = (node.get("node_type") or (item or {}).get("content_type") or "other").lower()
    if node_type != "faq":
        raise ValueError("Only approved FAQ nodes can be published to the Golden Dataset")
    if item and str(item.get("status") or "").lower() not in {"approved", "embedded"}:
        raise ValueError("Approve the FAQ before publishing it to the Golden Dataset")
    faq_payload = _faq_publication_payload(node, item, edge)
    title = faq_payload["title"]
    content = faq_payload["content"]
    question = faq_payload["question"]
    answer = faq_payload["answer"]
    file_path = faq_payload["file_path"]
    path_slugs = faq_payload["path_slugs"]
    tags = faq_payload["tags"]
    kb_id = "gn_" + hashlib.md5(f"{node.get('id')}:{persona_id}".encode()).hexdigest()[:12]

    if item:
        update_knowledge_item(source_id, {
            "status": "embedded",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "persona_id": persona_id,
        })

    entry = upsert_kb_entry({
        "kb_id": kb_id,
        "persona_id": persona_id,
        "tipo": "faq",
        "categoria": node_type,
        "titulo": title,
        "conteudo": content,
        "link": file_path,
        "status": "ATIVO",
        "source": "graph_embed",
        "agent_visibility": (item or {}).get("agent_visibility") or ["SDR", "Closer", "Classifier"],
        "tags": tags,
        "embedding_status": "created",
    })
    rag_entry = None
    rag_chunks: list[dict] = []
    if entry:
        from services import knowledge_rag_intake as _rag_intake
        if _rag_intake.is_rag_eligible(node_type):
            rag_entry = upsert_knowledge_rag_entry({
                "persona_id": persona_id,
                "artifact_id": metadata.get("artifact_id"),
                "content_type": "faq",
                "semantic_level": int(node.get("level") or 50),
                "title": title,
                "question": question,
                "answer": answer,
                "content": content,
                "summary": node.get("summary") or content[:280],
                "canonical_key": f"kb:{persona_id}:{kb_id}",
                "slug": _slugify(title),
                "status": "active",
                "tags": tags,
                "products": [title] if node_type == "product" else [],
                "campaigns": [title] if node_type == "campaign" else [],
                "metadata": {
                    **metadata,
                    "kb_entry_id": entry.get("id"),
                    "knowledge_node_id": node.get("id"),
                    "graph_edge_id": edge.get("id"),
                    "node_type": node_type,
                    "original_node_type": node_type,
                    "file_path": file_path,
                    "path": file_path,
                    "path_slugs": path_slugs,
                    "question": question,
                    "answer": answer,
                    "persona_id": persona_id,
                    "source_knowledge_item_id": source_id,
                },
                "confidence": float(node.get("confidence") or 0.8),
                "importance": float(node.get("importance") or 0.7),
            })
            if rag_entry and rag_entry.get("id"):
                rag_chunks = replace_knowledge_rag_chunks(
                    rag_entry["id"],
                    persona_id,
                    [{
                        "chunk_text": content,
                        "chunk_summary": (node.get("summary") or title)[:280],
                        "metadata": {
                            "source": "graph_embed",
                            "file_path": file_path,
                            "path": file_path,
                            "path_slugs": path_slugs,
                            "question": question,
                            "answer": answer,
                            "persona_id": persona_id,
                            "knowledge_item_id": source_id,
                            "knowledge_node_id": node.get("id"),
                        },
                    }],
                )
        if item:
            next_meta = {
                **((get_knowledge_item(source_id) or item).get("metadata") or {}),
                "kb_entry_id": entry.get("id"),
                "knowledge_rag_entry_id": (rag_entry or {}).get("id"),
                "embedded_edge_id": edge.get("id"),
                "golden_dataset_file_path": file_path,
                "golden_dataset_question": question,
                "golden_dataset_answer": answer,
            }
            update_knowledge_item(source_id, {
                "status": "embedded",
                "metadata": next_meta,
            })
    return {
        "item": get_knowledge_item(source_id) if source_id and source_table == "knowledge_items" else item,
        "kb_entry": entry,
        "rag_entry": rag_entry,
        "chunks": rag_chunks,
        "embedded_edge": edge,
    }


def reset_embedded_legacy_publications(persona_id: Optional[str] = None) -> dict:
    """Deactivate Embedded links and remove Golden Dataset/RAG mirrors."""
    client = get_client()
    embedded_q = client.table("knowledge_nodes").select("id,persona_id").eq("node_type", "embedded")
    if persona_id:
        embedded_q = embedded_q.eq("persona_id", persona_id)
    embedded_nodes = _q(embedded_q.limit(500))

    report = {
        "persona_id": persona_id,
        "embedded_nodes": len(embedded_nodes),
        "edges_deactivated": 0,
        "items_reverted": 0,
        "kb_entries_deleted": 0,
        "rag_entries_deleted": 0,
        "kb_mirror_nodes_deleted": 0,
    }

    for embedded in embedded_nodes:
        edge_rows = _q(
            client.table("knowledge_edges")
            .select("*")
            .eq("target_node_id", embedded.get("id"))
            .limit(500)
        )
        for edge in edge_rows:
            if _edge_is_inactive(edge):
                continue
            metadata = {
                **(edge.get("metadata") or {}),
                "active": False,
                "deleted_from": "reset_embedded_legacy_publications",
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            }
            _execute_with_retry(client.table("knowledge_edges").update({"metadata": metadata}).eq("id", edge["id"]))
            report["edges_deactivated"] += 1

            source_node = get_knowledge_node(edge.get("source_node_id") or "")
            edge_meta = edge.get("metadata") or {}
            kb_entry_id = edge_meta.get("kb_entry_id")
            rag_entry_id = edge_meta.get("knowledge_rag_entry_id")

            item = None
            if source_node and source_node.get("source_table") == "knowledge_items" and source_node.get("source_id"):
                item = get_knowledge_item(str(source_node.get("source_id")))
                item_meta = (item or {}).get("metadata") or {}
                kb_entry_id = item_meta.get("kb_entry_id") or kb_entry_id
                rag_entry_id = item_meta.get("knowledge_rag_entry_id") or rag_entry_id

            if rag_entry_id and delete_knowledge_rag_entry(str(rag_entry_id)):
                report["rag_entries_deleted"] += 1
            if kb_entry_id and delete_kb_entry(str(kb_entry_id)):
                report["kb_entries_deleted"] += 1
                kb_node = get_knowledge_node_for_source("kb_entries", str(kb_entry_id), persona_id=embedded.get("persona_id"))
                if kb_node and delete_knowledge_node(str(kb_node.get("id"))):
                    report["kb_mirror_nodes_deleted"] += 1

            if item and item.get("id"):
                next_meta = {
                    **((item.get("metadata") or {})),
                }
                next_meta.pop("kb_entry_id", None)
                next_meta.pop("knowledge_rag_entry_id", None)
                next_meta.pop("embedded_edge_id", None)
                update_knowledge_item(str(item["id"]), {
                    "status": "approved",
                    "metadata": next_meta,
                })
                report["items_reverted"] += 1

    return report


def mark_gallery_asset_inactive_by_edge(edge_id: str) -> None:
    if not edge_id:
        return
    client = get_client()
    try:
        rows = _q(client.table("assets").select("id,metadata").eq("gallery_edge_id", edge_id).limit(50))
        for row in rows:
            metadata = {**(row.get("metadata") or {}), "gallery_active": False}
            _execute_with_retry(client.table("assets").update({"metadata": metadata}).eq("id", row["id"]))
    except Exception:
        return


def list_gallery_assets(persona_id: Optional[str] = None, limit: int = 250) -> list[dict]:
    """Return knowledge nodes connected to the protected Gallery node."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING:
        return []
    client = get_client()
    try:
        gallery_q = client.table("knowledge_nodes").select("id").eq("node_type", "gallery").eq("status", "active")
        if persona_id:
            gallery_q = gallery_q.eq("persona_id", persona_id)
        galleries = gallery_q.limit(100).execute().data or []
        gallery_ids = [row["id"] for row in galleries if row.get("id")]
        if not gallery_ids:
            return []
        source_edges = (
            client.table("knowledge_edges")
            .select("*")
            .eq("relation_type", "gallery_asset")
            .in_("source_node_id", gallery_ids)
            .limit(limit)
            .execute().data or []
        )
        target_edges = (
            client.table("knowledge_edges")
            .select("*")
            .eq("relation_type", "gallery_asset")
            .in_("target_node_id", gallery_ids)
            .limit(limit)
            .execute().data or []
        )
        edges = source_edges + target_edges
        edges = [edge for edge in edges if not _edge_is_inactive(edge)]
        content_ids = [
            edge.get("target_node_id") if edge.get("source_node_id") in gallery_ids else edge.get("source_node_id")
            for edge in edges
        ]
        content_ids = [node_id for node_id in content_ids if node_id]
        if not content_ids:
            return []
        nodes = (
            client.table("knowledge_nodes")
            .select("*")
            .in_("id", content_ids)
            .neq("status", "archived")
            .limit(limit)
            .execute().data or []
        )
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
        return []
    edge_by_content = {
        (edge.get("target_node_id") if edge.get("source_node_id") in gallery_ids else edge.get("source_node_id")): edge
        for edge in edges
    }
    out = []
    for node in nodes:
        metadata = node.get("metadata") or {}
        file_path = metadata.get("file_path") or metadata.get("path") or metadata.get("url")
        ext = str(file_path).rsplit(".", 1)[-1].lower() if file_path and "." in str(file_path) else ""
        out.append({
            "id": f"gn:{node.get('id')}",
            "title": node.get("title") or node.get("slug") or "Gallery asset",
            "status": node.get("status") or "active",
            "content_type": node.get("node_type") or "asset",
            "asset_type": metadata.get("asset_type") or node.get("node_type"),
            "asset_function": metadata.get("asset_function") or "gallery_reference",
            "file_type": ext or metadata.get("file_type") or "node",
            "file_path": file_path,
            "persona_id": node.get("persona_id"),
            "created_at": node.get("created_at"),
            "source": "gallery",
            "summary": node.get("summary"),
            "tags": node.get("tags") or [],
            "gallery_edge_id": (edge_by_content.get(node.get("id")) or {}).get("id"),
        })
    return out


# ── Registries (migration 009) ─────────────────────────────────────────────
# Cached in-memory with short TTL — config rarely changes and the graph
# endpoint reads them on every request.

_REGISTRY_TTL_SECONDS = 300
_NODE_TYPE_REGISTRY_CACHE: tuple[float, list[dict]] | None = None
_RELATION_TYPE_REGISTRY_CACHE: tuple[float, list[dict]] | None = None

# Defensive fallback: mirrors the seed inserts of migration 009.
# Used when the table is missing or empty (009 partially applied) so the
# graph endpoint still returns useful level/color/icon hints.
_NODE_TYPE_REGISTRY_FALLBACK: list[dict] = [
    {"node_type": "persona",        "label": "Persona",   "default_level":  0, "default_importance": 1.00, "color": "#7c6fff", "icon": "user",        "sort_order":  0},
    {"node_type": "entity",         "label": "Entidade",  "default_level": 10, "default_importance": 0.95, "color": "#7c6fff", "icon": "network",     "sort_order": 10},
    {"node_type": "brand",          "label": "Brand",     "default_level": 20, "default_importance": 0.90, "color": "#a78bfa", "icon": "badge",       "sort_order": 20},
    {"node_type": "campaign",       "label": "Campanha",  "default_level": 30, "default_importance": 0.80, "color": "#fb923c", "icon": "megaphone",   "sort_order": 30},
    {"node_type": "product",        "label": "Produto",   "default_level": 40, "default_importance": 0.85, "color": "#60a5fa", "icon": "box",         "sort_order": 40},
    {"node_type": "briefing",       "label": "Briefing",  "default_level": 50, "default_importance": 0.75, "color": "#c084fc", "icon": "file-text",   "sort_order": 50},
    {"node_type": "audience",       "label": "Audiência", "default_level": 55, "default_importance": 0.70, "color": "#f472b6", "icon": "users",       "sort_order": 55},
    {"node_type": "tone",           "label": "Tom",       "default_level": 60, "default_importance": 0.70, "color": "#22d3ee", "icon": "palette",     "sort_order": 60},
    {"node_type": "rule",           "label": "Regra",     "default_level": 65, "default_importance": 0.80, "color": "#f87171", "icon": "scale",       "sort_order": 65},
    {"node_type": "copy",           "label": "Copy",      "default_level": 70, "default_importance": 0.65, "color": "#64748b", "icon": "text",        "sort_order": 70},
    {"node_type": "faq",            "label": "FAQ",       "default_level": 75, "default_importance": 0.65, "color": "#4ade80", "icon": "circle-help", "sort_order": 75},
    {"node_type": "asset",          "label": "Asset",     "default_level": 80, "default_importance": 0.55, "color": "#f59e0b", "icon": "image",       "sort_order": 80},
    {"node_type": "gallery",        "label": "Gallery",   "default_level":112, "default_importance": 0.82, "color": "#f0abfc", "icon": "images",      "sort_order":112},
    {"node_type": "embedded",       "label": "Golden Dataset", "default_level":120, "default_importance": 0.78, "color": "#ffffff", "icon": "database",    "sort_order":120},
    {"node_type": "tag",            "label": "Tag",       "default_level": 90, "default_importance": 0.30, "color": "#94a3b8", "icon": "tag",         "sort_order": 90},
    {"node_type": "mention",        "label": "Menção",    "default_level": 92, "default_importance": 0.25, "color": "#94a3b8", "icon": "at-sign",     "sort_order": 92},
    {"node_type": "knowledge_item", "label": "Fila",      "default_level": 95, "default_importance": 0.40, "color": "#94a3b8", "icon": "inbox",       "sort_order": 95},
    {"node_type": "kb_entry",       "label": "Golden Dataset Entry", "default_level": 95, "default_importance": 0.50, "color": "#94a3b8", "icon": "database",    "sort_order": 96},
]

_RELATION_TYPE_REGISTRY_FALLBACK: list[dict] = [
    {"relation_type": "belongs_to_persona", "label": "pertence à persona", "inverse_label": "possui",        "default_weight": 1.00, "directional": True,  "sort_order":  10},
    {"relation_type": "defines_brand",      "label": "define brand",       "inverse_label": "é definido por", "default_weight": 0.90, "directional": True,  "sort_order":  20},
    {"relation_type": "has_tone",           "label": "usa tom",            "inverse_label": "tom de",         "default_weight": 0.80, "directional": True,  "sort_order":  30},
    {"relation_type": "about_product",      "label": "sobre produto",      "inverse_label": "tem conhecimento", "default_weight": 0.85, "directional": True, "sort_order":  40},
    {"relation_type": "part_of_campaign",   "label": "parte da campanha",  "inverse_label": "contém",         "default_weight": 0.75, "directional": True,  "sort_order":  50},
    {"relation_type": "supports_campaign",  "label": "apoia campanha",     "inverse_label": "apoiada por",    "default_weight": 0.70, "directional": True,  "sort_order":  55},
    {"relation_type": "answers_question",   "label": "responde pergunta",  "inverse_label": "é respondido por", "default_weight": 0.80, "directional": True, "sort_order":  60},
    {"relation_type": "supports_copy",      "label": "suporta copy",       "inverse_label": "é suportado por", "default_weight": 0.70, "directional": True,  "sort_order":  70},
    {"relation_type": "uses_asset",         "label": "usa asset",          "inverse_label": "é usado por",    "default_weight": 0.65, "directional": True,  "sort_order":  80},
    {"relation_type": "gallery_asset",      "label": "na gallery",         "inverse_label": "contém",         "default_weight": 0.90, "directional": True,  "sort_order":  82},
    {"relation_type": "briefed_by",         "label": "briefado por",       "inverse_label": "briefa",         "default_weight": 0.70, "directional": True,  "sort_order":  90},
    {"relation_type": "same_topic_as",      "label": "mesmo tópico",       "inverse_label": "mesmo tópico",   "default_weight": 0.45, "directional": False, "sort_order": 100},
    {"relation_type": "duplicate_of",       "label": "duplicado de",       "inverse_label": "tem duplicado",  "default_weight": 1.00, "directional": True,  "sort_order": 110},
    {"relation_type": "derived_from",       "label": "derivado de",        "inverse_label": "origina",        "default_weight": 0.90, "directional": True,  "sort_order": 120},
    {"relation_type": "contains",           "label": "contém",             "inverse_label": "contido em",     "default_weight": 0.75, "directional": True,  "sort_order": 130},
    {"relation_type": "has_tag",            "label": "tem tag",            "inverse_label": "marca",          "default_weight": 0.30, "directional": True,  "sort_order": 200},
    {"relation_type": "mentions",           "label": "menciona",           "inverse_label": "mencionado por", "default_weight": 0.30, "directional": True,  "sort_order": 210},
    {"relation_type": "visible_to_agent",   "label": "visível para agente", "inverse_label": "vê",            "default_weight": 0.50, "directional": True,  "sort_order": 220},
]


def get_node_type_registry() -> list[dict]:
    """Return the knowledge_node_type_registry rows (migration 009).

    Caches the result for _REGISTRY_TTL_SECONDS to avoid querying on every
    request. Falls back to a hardcoded mirror of the seed inserts when the
    table is missing or empty so the graph endpoint stays useful.
    """
    global _NODE_TYPE_REGISTRY_CACHE
    now = time.monotonic()
    if _NODE_TYPE_REGISTRY_CACHE and (now - _NODE_TYPE_REGISTRY_CACHE[0]) < _REGISTRY_TTL_SECONDS:
        return _NODE_TYPE_REGISTRY_CACHE[1]
    rows: list[dict] = []
    try:
        rows = (
            get_client().table("knowledge_node_type_registry")
            .select("node_type,label,default_level,default_importance,color,icon,sort_order,active")
            .execute().data or []
        )
        rows = [r for r in rows if r.get("active", True)]
    except Exception:
        rows = []
    if not rows:
        rows = _NODE_TYPE_REGISTRY_FALLBACK
    _NODE_TYPE_REGISTRY_CACHE = (now, rows)
    return rows


def get_relation_type_registry() -> list[dict]:
    """Return the knowledge_relation_type_registry rows (migration 009).

    Same cache + fallback strategy as get_node_type_registry.
    """
    global _RELATION_TYPE_REGISTRY_CACHE
    now = time.monotonic()
    if _RELATION_TYPE_REGISTRY_CACHE and (now - _RELATION_TYPE_REGISTRY_CACHE[0]) < _REGISTRY_TTL_SECONDS:
        return _RELATION_TYPE_REGISTRY_CACHE[1]
    rows: list[dict] = []
    try:
        rows = (
            get_client().table("knowledge_relation_type_registry")
            .select("relation_type,label,inverse_label,default_weight,directional,sort_order,active")
            .execute().data or []
        )
        rows = [r for r in rows if r.get("active", True)]
    except Exception:
        rows = []
    if not rows:
        rows = _RELATION_TYPE_REGISTRY_FALLBACK
    _RELATION_TYPE_REGISTRY_CACHE = (now, rows)
    return rows


# ── Insights ───────────────────────────────────────────────────────────────

def get_insights(status: Optional[str] = None, limit: int = 50) -> list:
    try:
        q = get_client().table("flow_insights").select("*").order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        return _q(q)
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"get_insights failed: {exc}", exc)
        except Exception:
            pass
        return []


def insert_insight(data: dict) -> None:
    get_client().table("flow_insights").insert(data).execute()


def update_insight(insight_id: str, data: dict) -> None:
    get_client().table("flow_insights").update(data).eq("id", insight_id).execute()


def get_open_insights_titles() -> list[str]:
    rows = _q(get_client().table("flow_insights").select("title").eq("status", "open"))
    return [r["title"] for r in rows if r.get("title")]


# ── System Health ──────────────────────────────────────────────────────────

def insert_health_snapshot(data: dict) -> None:
    get_client().table("system_health").insert(data).execute()


def get_health_history(limit: int = 30) -> list:
    rows = _q(
        get_client().table("system_health")
        .select("*")
        .order("snapshot_at", desc=True)
        .limit(limit)
    )
    return list(reversed(rows))


# ── Integration Status ──────────────────────────────────────────────────────

def upsert_integration_status(data: dict) -> None:
    client = get_client()
    persona_id = data.get("persona_id")
    service = data["service"]
    if persona_id is None:
        # maybe_single() throws 406 if duplicates exist — use limit(1) instead
        rows = client.table("integration_status").select("id").is_("persona_id", "null").eq("service", service).limit(1).execute()
        if rows.data:
            row_id = rows.data[0]["id"]
            client.table("integration_status").update(data).eq("id", row_id).execute()
        else:
            client.table("integration_status").insert(data).execute()
    else:
        client.table("integration_status").upsert(data, on_conflict="persona_id,service").execute()


def get_integration_statuses(persona_id: Optional[str] = None) -> list:
    client = get_client()
    q = client.table("integration_status").select("*").order("service").order("last_check", desc=True)
    if persona_id:
        q = q.eq("persona_id", persona_id)
    rows = _q(q)
    seen: set[str] = set()
    result = []
    for row in rows:
        key = f"{row.get('persona_id')}:{row['service']}"
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


# ── Personas ───────────────────────────────────────────────────────────────

def get_personas() -> list:
    return _q(get_client().table("personas").select("*").eq("active", True))


def get_persona(slug: str) -> Optional[dict]:
    return _one(get_client().table("personas").select("*").eq("slug", slug).maybe_single())


def get_persona_by_id(persona_id: str) -> Optional[dict]:
    return _one(get_client().table("personas").select("*").eq("id", persona_id).maybe_single())


def upsert_persona(data: dict) -> None:
    get_client().table("personas").upsert(data, on_conflict="slug").execute()


_PERSONA_ROUTING_FIELDS = (
    "process_mode",
    "outbound_webhook_url",
    "outbound_webhook_secret",
    "inbound_webhook_token",
)


def get_persona_routing(slug: str) -> Optional[dict]:
    """Returns the routing config for a persona, or None if missing.

    Falls back gracefully when migration 011 is not yet applied (older
    columns will be missing — the function returns defaults so callers can
    keep working without crashing).
    """
    persona = get_persona(slug)
    if not persona:
        return None
    migration_applied = all(field in persona for field in _PERSONA_ROUTING_FIELDS)
    legacy_bindings = get_workflow_bindings(persona.get("id")) if persona.get("id") else []
    has_legacy_n8n = any(binding.get("active", True) for binding in legacy_bindings)
    process_mode = persona.get("process_mode") if migration_applied else None
    if not process_mode:
        process_mode = "n8n" if has_legacy_n8n else "internal"
    return {
        "slug": persona.get("slug"),
        "id": persona.get("id"),
        "process_mode": process_mode,
        "outbound_webhook_url": persona.get("outbound_webhook_url"),
        "outbound_webhook_secret": persona.get("outbound_webhook_secret"),
        "inbound_webhook_token": persona.get("inbound_webhook_token"),
        "migration_applied": migration_applied,
        "routing_source": "persona_columns" if migration_applied else ("legacy_workflow_binding" if has_legacy_n8n else "default"),
    }


def update_persona_routing(slug: str, data: dict) -> Optional[dict]:
    """Partial update of persona routing fields. Ignores unknown keys."""
    payload = {k: v for k, v in (data or {}).items() if k in _PERSONA_ROUTING_FIELDS}
    if not payload:
        return get_persona_routing(slug)
    try:
        _execute_with_retry(
            get_client().table("personas").update(payload).eq("slug", slug)
        )
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"update_persona_routing failed: {exc}", exc)
        except Exception:
            pass
        raise
    return get_persona_routing(slug)


# ── Knowledge Base ─────────────────────────────────────────────────────────

def get_kb_entries(persona_id: Optional[str] = None, status: str = "ATIVO") -> list:
    q = get_client().table("kb_entries").select("id,persona_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if status:
        q = q.eq("status", status)
    return _q(q.order("prioridade"))


def get_kb_entries_for_persona_ids(persona_ids: list[str], status: str = "ATIVO") -> list:
    ids = [pid for pid in persona_ids if pid]
    if not ids:
        return []
    q = get_client().table("kb_entries").select("id,persona_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
    q = q.in_("persona_id", ids)
    if status:
        q = q.eq("status", status)
    return _q(q.order("prioridade"))


def _kb_entry_select():
    return (
        get_client()
        .table("kb_entries")
        .select("id,persona_id,kb_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
    )


def _find_kb_entry_by_key(kb_id: Optional[str], persona_id: Optional[str]) -> Optional[dict]:
    if not kb_id:
        return None
    q = _kb_entry_select().eq("kb_id", kb_id)
    q = q.eq("persona_id", persona_id) if persona_id else q.is_("persona_id", "null")
    return _one(q.maybe_single())


def _log_kb_entry_write_failure(stage: str, payload: dict, exc: Exception) -> None:
    try:
        from services import sre_logger
        sre_logger.error(
            "supabase_client",
            (
                f"kb_entries {stage} failed: {type(exc).__name__}: {exc} "
                f"(kb_id={payload.get('kb_id')!r}, persona_id={payload.get('persona_id')!r}, source={payload.get('source')!r})"
            ),
            exc,
        )
    except Exception:
        pass


def upsert_kb_entry(data: dict) -> dict:
    payload = dict(data or {})
    kb_id = payload.get("kb_id")
    persona_id = payload.get("persona_id")
    last_exc: Exception | None = None

    try:
        result = _execute_with_retry(get_client().table("kb_entries").upsert(payload, on_conflict="kb_id,persona_id"))
        rows = result.data or []
        return rows[0] if rows else (_find_kb_entry_by_key(kb_id, persona_id) or {})
    except Exception as exc:
        last_exc = exc
        _log_kb_entry_write_failure("upsert", payload, exc)

    fallback_payload = dict(payload)
    if fallback_payload.get("source") == "graph_embed":
        fallback_payload["source"] = "manual"
        try:
            result = _execute_with_retry(get_client().table("kb_entries").upsert(fallback_payload, on_conflict="kb_id,persona_id"))
            rows = result.data or []
            return rows[0] if rows else (_find_kb_entry_by_key(kb_id, persona_id) or {})
        except Exception as exc:
            last_exc = exc
            _log_kb_entry_write_failure("upsert-fallback-source", fallback_payload, exc)

    existing = _find_kb_entry_by_key(kb_id, persona_id)
    mutable = {
        key: value
        for key, value in fallback_payload.items()
        if key not in {"id", "kb_id", "persona_id", "created_at"}
    }
    try:
        if existing and existing.get("id"):
            result = _execute_with_retry(get_client().table("kb_entries").update(mutable).eq("id", existing["id"]))
            rows = result.data or []
            return rows[0] if rows else (get_kb_entry(existing["id"]) or {**existing, **mutable})
        result = _execute_with_retry(get_client().table("kb_entries").insert(fallback_payload))
        rows = result.data or []
        if rows:
            return rows[0]
        return _find_kb_entry_by_key(kb_id, persona_id) or {}
    except Exception as exc:
        _log_kb_entry_write_failure("manual-write", fallback_payload, exc)
        if last_exc:
            raise exc from last_exc
        raise


def get_kb_entry(entry_id: str) -> Optional[dict]:
    return _one(
        _kb_entry_select()
        .eq("id", entry_id)
        .maybe_single()
    )


def get_kb_entries_by_ids(ids: list) -> dict:
    """Batch lookup; avoids N+1 when enriching graph kb_entry nodes."""
    unique = [i for i in {str(x) for x in (ids or []) if x}]
    if not unique:
        return {}
    rows: list = []
    # Supabase/PostgREST .in_ has a URL length cap; chunk to be safe.
    for start in range(0, len(unique), 200):
        chunk = unique[start:start + 200]
        rows.extend(_q(
            _kb_entry_select()
            .in_("id", chunk)
        ))
    return {str(r["id"]): r for r in rows if r.get("id")}


def update_kb_entry(entry_id: str, data: dict) -> None:
    from datetime import datetime, timezone
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _execute_with_retry(get_client().table("kb_entries").update(data).eq("id", entry_id))


def delete_kb_entry(entry_id: str) -> bool:
    result = _execute_with_retry(get_client().table("kb_entries").delete().eq("id", entry_id))
    return bool(result.data)


def search_kb(query_embedding: list, persona_id: Optional[str] = None, top_k: int = 5) -> list:
    params = {"query_embedding": query_embedding, "match_count": top_k}
    if persona_id:
        params["filter_persona_id"] = persona_id
    return _q(get_client().rpc("match_kb_entries", params))


# ── Agent Logs ─────────────────────────────────────────────────────────────

_AGENT_LOGS_SCHEMA_MODE: Optional[str] = None


def _detect_agent_logs_schema_mode() -> str:
    global _AGENT_LOGS_SCHEMA_MODE
    if _AGENT_LOGS_SCHEMA_MODE:
        return _AGENT_LOGS_SCHEMA_MODE
    client = get_client()
    try:
        client.table("agent_logs").select("agent_type").limit(1).execute()
        _AGENT_LOGS_SCHEMA_MODE = "modern"
        return _AGENT_LOGS_SCHEMA_MODE
    except Exception as exc:
        text = str(exc)
        if "agent_type" in text and ("does not exist" in text or "42703" in text):
            _AGENT_LOGS_SCHEMA_MODE = "legacy"
            return _AGENT_LOGS_SCHEMA_MODE
    try:
        client.table("agent_logs").select("agent_name").limit(1).execute()
        _AGENT_LOGS_SCHEMA_MODE = "legacy"
    except Exception:
        _AGENT_LOGS_SCHEMA_MODE = "modern"
    return _AGENT_LOGS_SCHEMA_MODE


def _normalize_agent_log_row(row: dict) -> dict:
    if not isinstance(row, dict):
        return {}
    if "agent_type" in row or "action" in row or "decision" in row:
        meta = row.get("metadata") or {}
        return {
            **row,
            "agent_type": row.get("agent_type") or meta.get("component") or row.get("agent_name"),
            "action": row.get("action") or meta.get("message") or "",
            "decision": row.get("decision") or meta.get("traceback") or row.get("error_msg") or "",
            "metadata": meta,
            "level": meta.get("level") or ("ERROR" if str(row.get("action") or "").startswith("[ERROR]") else "INFO"),
            "component": meta.get("component") or row.get("agent_type") or row.get("agent_name") or "",
            "message": meta.get("message") or row.get("action") or "",
            "traceback": meta.get("traceback") or row.get("decision") or "",
            "ts": meta.get("ts") or row.get("created_at") or "",
        }

    output = row.get("output") if isinstance(row.get("output"), dict) else {}
    input_payload = row.get("input") if isinstance(row.get("input"), dict) else {}
    status = str(row.get("status") or "success").lower()
    level = "ERROR" if status in {"error", "timeout", "warn", "warning"} or row.get("error_msg") else "INFO"
    message = row.get("error_msg") or output.get("reply") or output.get("summary") or status
    metadata = {
        "level": level,
        "component": row.get("agent_name") or "agent",
        "message": message,
        "traceback": row.get("error_msg") or "",
        "ts": row.get("created_at"),
        "input": input_payload,
        "output": output,
        "latency_ms": row.get("latency_ms"),
        "model_used": row.get("model_used"),
        "legacy_schema": True,
    }
    return {
        **row,
        "agent_type": row.get("agent_name") or "agent",
        "action": f"[{level}] {str(message)[:200]}",
        "decision": row.get("error_msg") or json.dumps(output or input_payload, ensure_ascii=False)[:500],
        "metadata": metadata,
        "level": level,
        "component": row.get("agent_name") or "agent",
        "message": message,
        "traceback": row.get("error_msg") or "",
        "ts": row.get("created_at") or "",
    }


def insert_agent_log(data: dict) -> None:
    payload = dict(data or {})
    meta = payload.get("metadata") or {}
    level = str(
        meta.get("level")
        or ("ERROR" if str(payload.get("action") or "").startswith("[ERROR]") else "INFO")
    ).lower()
    legacy_payload = {
        "lead_id": payload.get("lead_id"),
        "persona_id": payload.get("persona_id"),
        "agent_name": payload.get("agent_type") or payload.get("agent_name") or meta.get("component") or "agent",
        "input": payload.get("input") if isinstance(payload.get("input"), dict) else (meta.get("input") or {}),
        "output": payload.get("output") if isinstance(payload.get("output"), dict) else {
            "action": payload.get("action"),
            "decision": payload.get("decision"),
            "metadata": meta,
        },
        "latency_ms": payload.get("latency_ms") or meta.get("latency_ms"),
        "model_used": payload.get("model_used") or meta.get("model_used"),
        "status": "error" if level == "error" else ("timeout" if level == "timeout" else "success"),
        "error_msg": payload.get("decision") if level == "error" else payload.get("error_msg"),
    }

    mode = _detect_agent_logs_schema_mode()
    attempts = [payload, legacy_payload] if mode == "modern" else [legacy_payload, payload]
    last_exc: Exception | None = None
    for candidate in attempts:
        try:
            _execute_with_retry(get_client().table("agent_logs").insert(candidate))
            return
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc


def get_agent_logs(lead_id: Optional[str] = None, limit: int = 50) -> list:
    q = get_client().table("agent_logs").select("*").order("created_at", desc=True).limit(limit)
    if lead_id:
        q = q.eq("lead_id", lead_id)
    rows = _q(q)
    return [_normalize_agent_log_row(row) for row in rows]


def get_error_logs(component: Optional[str] = None, limit: int = 100) -> list:
    rows = get_agent_logs(limit=limit)
    filtered = []
    for row in rows:
        level = str(row.get("level") or "").upper()
        if level not in {"ERROR", "WARN", "WARNING"}:
            continue
        if component and str(row.get("component") or row.get("agent_type") or "").lower() != component.lower():
            continue
        filtered.append(row)
    return filtered


# ── n8n Executions Mirror ──────────────────────────────────────────────────

def upsert_n8n_execution(data: dict) -> None:
    get_client().table("n8n_executions").upsert(data, on_conflict="n8n_id").execute()


def get_n8n_executions(limit: int = 100, status: Optional[str] = None) -> list:
    q = (
        get_client().table("n8n_executions")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit)
    )
    if status:
        q = q.eq("status", status)
    return _q(q)


def get_n8n_error_rate(hours: int = 24) -> float:
    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    all_rows = _q(
        get_client().table("n8n_executions")
        .select("status")
        .gte("started_at", since)
    )
    if not all_rows:
        return 0.0
    errors = sum(1 for r in all_rows if r.get("status") == "error")
    return errors / len(all_rows)


# ── Knowledge Sources ──────────────────────────────────────────────────────

def get_knowledge_source_by_path(path: str) -> Optional[dict]:
    return _one(get_client().table("knowledge_sources").select("*").eq("path", path).maybe_single())


def insert_knowledge_source(data: dict) -> dict:
    return _insert_one(get_client().table("knowledge_sources").insert(data))


def update_knowledge_source(source_id: str, data: dict) -> None:
    get_client().table("knowledge_sources").update(data).eq("id", source_id).execute()


def get_or_create_manual_source() -> dict:
    existing = _one(get_client().table("knowledge_sources").select("*").eq("source_type", "upload").maybe_single())
    if existing:
        return existing
    r = get_client().table("knowledge_sources").insert({"source_type": "upload", "name": "Manual Upload"}).execute()
    return (r.data or [{}])[0]


# ── Knowledge Items ────────────────────────────────────────────────────────

def get_knowledge_items(
    status: Optional[str] = None,
    persona_id: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list:
    q = (
        get_client().table("knowledge_items")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status:
        q = q.eq("status", status)
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if content_type:
        q = q.eq("content_type", content_type)
    return _q(q)


def get_knowledge_item(item_id: str) -> Optional[dict]:
    return _one(get_client().table("knowledge_items").select("*").eq("id", item_id).maybe_single())


def normalize_file_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    normalized = str(file_path).replace("\\", "/").strip()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def get_knowledge_item_by_path(file_path: str) -> Optional[dict]:
    exact = _one(
        get_client().table("knowledge_items")
        .select("*")
        .eq("file_path", file_path)
        .maybe_single()
    )
    normalized = normalize_file_path(file_path)
    if exact or not normalized or normalized == file_path:
        return exact
    return _one(
        get_client().table("knowledge_items")
        .select("*")
        .eq("file_path", normalized)
        .maybe_single()
    )


# Mirrors the CHECK constraint on knowledge_items.content_type from
# supabase/migrations/002_knowledge_platform.sql. Keep in sync if the constraint changes.
KNOWLEDGE_ITEM_CONTENT_TYPES: frozenset[str] = frozenset({
    "brand", "briefing", "product", "campaign", "copy", "asset",
    "prompt", "faq", "maker_material", "tone", "competitor",
    "audience", "rule", "other",
})

KNOWLEDGE_ITEM_STATUSES: frozenset[str] = frozenset({
    "pending", "approved", "rejected", "embedded",
})

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def validate_knowledge_item_payload(payload: dict) -> list[str]:
    """Return a list of contract violations for a knowledge_items insert payload.

    Empty list = payload is safe to send to the DB. Mirrors NOT NULL, CHECK and
    foreign-key shape requirements from the schema.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be a dict"]

    persona_id = payload.get("persona_id")
    if not persona_id:
        errors.append("persona_id is required")
    elif not isinstance(persona_id, str) or not _UUID_RE.match(persona_id):
        errors.append(f"persona_id must be a UUID string, got {persona_id!r}")

    source_id = payload.get("source_id")
    if not source_id:
        errors.append("source_id is required")
    elif not isinstance(source_id, str) or not _UUID_RE.match(source_id):
        errors.append(f"source_id must be a UUID string, got {source_id!r}")

    content_type = payload.get("content_type")
    if not content_type:
        errors.append("content_type is required")
    elif content_type not in KNOWLEDGE_ITEM_CONTENT_TYPES:
        errors.append(
            f"content_type {content_type!r} not allowed; expected one of "
            f"{sorted(KNOWLEDGE_ITEM_CONTENT_TYPES)}"
        )

    title = payload.get("title")
    if not isinstance(title, str) or len(title.strip()) < 3:
        errors.append("title must be a non-empty string of at least 3 chars")

    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        errors.append("content must be a non-empty string")

    if "tags" in payload and payload["tags"] is not None and not isinstance(payload["tags"], list):
        errors.append(f"tags must be a list, got {type(payload['tags']).__name__}")

    if "agent_visibility" in payload and payload["agent_visibility"] is not None and not isinstance(payload["agent_visibility"], list):
        errors.append(
            f"agent_visibility must be a list, got {type(payload['agent_visibility']).__name__}"
        )

    if "metadata" in payload and payload["metadata"] is not None and not isinstance(payload["metadata"], dict):
        errors.append(f"metadata must be a dict, got {type(payload['metadata']).__name__}")

    status = payload.get("status")
    if status is not None and status not in KNOWLEDGE_ITEM_STATUSES:
        errors.append(
            f"status {status!r} not allowed; expected one of {sorted(KNOWLEDGE_ITEM_STATUSES)}"
        )

    return errors


def insert_knowledge_item(data: dict) -> dict:
    data.setdefault("updated_at", __import__("datetime").datetime.utcnow().isoformat())
    return _insert_one(get_client().table("knowledge_items").insert(data))


def update_knowledge_item(item_id: str, data: dict) -> None:
    data["updated_at"] = __import__("datetime").datetime.utcnow().isoformat()
    try:
        get_client().table("knowledge_items").update(data).eq("id", item_id).execute()
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"update_knowledge_item failed id={item_id}: {exc}", exc)
        except Exception:
            pass
        raise


def delete_knowledge_item(item_id: str) -> bool:
    result = _execute_with_retry(get_client().table("knowledge_items").delete().eq("id", item_id))
    return bool(result.data)


def insert_knowledge_intake_message(data: dict) -> dict:
    return _insert_one(get_client().table("knowledge_intake_messages").insert(data))


def update_knowledge_intake_message(intake_id: str, data: dict) -> None:
    _execute_with_retry(
        get_client().table("knowledge_intake_messages").update(data).eq("id", intake_id)
    )


def upsert_knowledge_rag_entry(data: dict) -> dict:
    from datetime import datetime, timezone

    payload = dict(data)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = _execute_with_retry(
        get_client()
        .table("knowledge_rag_entries")
        .upsert(payload, on_conflict="persona_id,canonical_key")
    )
    return (result.data or [{}])[0]


def replace_knowledge_rag_chunks(rag_entry_id: str, persona_id: str, chunks: list[dict]) -> list[dict]:
    client = get_client()
    _execute_with_retry(client.table("knowledge_rag_chunks").delete().eq("rag_entry_id", rag_entry_id))
    if not chunks:
        return []
    payload = []
    for idx, chunk in enumerate(chunks):
        row = dict(chunk)
        row.setdefault("chunk_index", idx)
        row["rag_entry_id"] = rag_entry_id
        row["persona_id"] = persona_id
        payload.append(row)
    result = _execute_with_retry(client.table("knowledge_rag_chunks").insert(payload))
    return result.data or []


def delete_knowledge_rag_entry(rag_entry_id: str) -> bool:
    client = get_client()
    _execute_with_retry(client.table("knowledge_rag_chunks").delete().eq("rag_entry_id", rag_entry_id))
    result = _execute_with_retry(client.table("knowledge_rag_entries").delete().eq("id", rag_entry_id))
    return bool(result.data)


def upsert_knowledge_rag_link(data: dict) -> dict:
    result = _execute_with_retry(
        get_client()
        .table("knowledge_rag_links")
        .upsert(data, on_conflict="source_entry_id,target_entry_id,relation_type")
    )
    return (result.data or [{}])[0]


def find_knowledge_rag_entry_by_slug(
    *,
    persona_id: str,
    content_type: str,
    slug: str,
) -> Optional[dict]:
    return _one(
        get_client()
        .table("knowledge_rag_entries")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("content_type", content_type)
        .eq("slug", slug)
        .maybe_single()
    )


def get_knowledge_item_counts(persona_id: Optional[str] = None) -> dict:
    q = get_client().table("knowledge_items").select("status,content_type")
    if persona_id:
        q = q.eq("persona_id", persona_id)
    rows = _q(q)
    by_status: dict = {}
    by_type: dict = {}
    for r in rows:
        s = r["status"]
        t = r["content_type"]
        by_status[s] = by_status.get(s, 0) + 1
        by_type[t] = by_type.get(t, 0) + 1
    return {"by_status": by_status, "by_type": by_type, "total": len(rows)}


# ── Sync Runs ──────────────────────────────────────────────────────────────

def insert_sync_run(data: dict) -> dict:
    result = _execute_with_retry(get_client().table("sync_runs").insert(data))
    return (result.data or [{}])[0]


def update_sync_run(run_id: str, data: dict) -> None:
    _execute_with_retry(get_client().table("sync_runs").update(data).eq("id", run_id))


def get_sync_runs(limit: int = 20) -> list:
    return _q(
        get_client().table("sync_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit)
    )


def insert_sync_log(data: dict) -> None:
    _execute_with_retry(get_client().table("sync_logs").insert(data))


def get_sync_logs(run_id: str, limit: int = 200) -> list:
    return _q(
        get_client().table("sync_logs")
        .select("*")
        .eq("run_id", run_id)
        .order("created_at", desc=False)
        .limit(limit)
    )


# ── Workflow Bindings ──────────────────────────────────────────────────────

def get_workflow_bindings(persona_id: Optional[str] = None) -> list:
    # Try with relationship join first; fall back to plain select if PGRST205
    try:
        q = get_client().table("workflow_bindings").select("*,personas(name,slug)")
        if persona_id:
            q = q.eq("persona_id", persona_id)
        rows = _q(q)
        if rows is not None:  # _q already handles None, but check for PGRST205 path
            return rows
    except Exception:
        pass
    # Fallback: plain select without relationship join
    q = get_client().table("workflow_bindings").select("*")
    if persona_id:
        q = q.eq("persona_id", persona_id)
    return _q(q)


def get_default_whatsapp_phone_number_id(persona_id: Optional[str] = None) -> Optional[str]:
    if not persona_id:
        return None
    for binding in get_workflow_bindings(persona_id):
        value = binding.get("whatsapp_phone_number_id")
        if value and binding.get("active", True):
            return value
    return None


def upsert_workflow_binding(data: dict) -> dict:
    result = get_client().table("workflow_bindings").upsert(
        data, on_conflict="workflow_name,persona_id"
    ).execute()
    return result.data[0] if result.data else {}


# ── Brand Profiles ─────────────────────────────────────────────────────────

def get_brand_profile(persona_id: str) -> Optional[dict]:
    return _one(
        get_client().table("brand_profiles")
        .select("*")
        .eq("persona_id", persona_id)
        .maybe_single()
    )


def upsert_brand_profile(data: dict) -> dict:
    result = get_client().table("brand_profiles").upsert(
        data, on_conflict="persona_id"
    ).execute()
    return result.data[0] if result.data else {}


# ── Campaigns ──────────────────────────────────────────────────────────────

def get_campaigns(persona_id: Optional[str] = None) -> list:
    q = get_client().table("campaigns").select("*").order("created_at", desc=True)
    if persona_id:
        q = q.eq("persona_id", persona_id)
    return _q(q)


# ── System Events ──────────────────────────────────────────────────────────

# Columns that exist in the physical system_events BASE TABLE.
# Any key not in this set is silently dropped before insert to prevent PGRST204.
_SYSTEM_EVENTS_COLUMNS = frozenset({
    "event_type", "entity_type", "entity_id",
    "persona_id", "payload", "level", "source",
})


def insert_event(
    data: dict,
    level: str = "info",
    source: Optional[str] = None,
) -> Optional[dict]:
    """
    Fire-and-forget event insert. Never raises — if the DB is unavailable
    the calling code continues uninterrupted.

    Only columns present in _SYSTEM_EVENTS_COLUMNS are forwarded so that
    adding extra keys to `data` never causes a PGRST204 schema-cache error.
    """
    try:
        row = {k: v for k, v in data.items() if k in _SYSTEM_EVENTS_COLUMNS}
        row.setdefault("payload", {})
        row.setdefault("level", level)
        if source:
            row["source"] = source
        result = get_client().table("system_events").insert(row).execute()
        return (result.data or [None])[0]
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"insert_event failed: {exc}", exc)
        except Exception:
            pass
        return None


def get_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    persona_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
) -> list:
    q = (
        get_client().table("system_events")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if event_type:
        q = q.eq("event_type", event_type)
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    if level:
        q = q.eq("level", level)
    return _q(q)


# ── Pipeline Status ────────────────────────────────────────────────────────

def get_pipeline_statuses() -> list:
    return _q(
        get_client().table("pipeline_status")
        .select("*")
        .order("service")
    )


def update_pipeline_status(service: str, data: dict) -> None:
    get_client().table("pipeline_status").update(data).eq("service", service).execute()


def get_pipeline_metrics(persona_id: Optional[str] = None) -> dict:
    from datetime import datetime, timedelta
    today = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    client = get_client()

    attention_q = (
        client.table("knowledge_items")
        .select("status")
        .in_("status", ["pending", "needs_persona", "needs_category"])
    )
    approved_q = (
        client.table("knowledge_items")
        .select("id")
        .eq("status", "approved")
        .gte("updated_at", today)
    )
    kb_q = (
        client.table("kb_entries")
        .select("id")
        .eq("status", "ATIVO")
    )
    asset_q = (
        client.table("knowledge_items")
        .select("id")
        .eq("content_type", "asset")
        .in_("status", ["pending", "needs_persona"])
    )
    if persona_id:
        attention_q = attention_q.eq("persona_id", persona_id)
        approved_q = approved_q.eq("persona_id", persona_id)
        kb_q = kb_q.eq("persona_id", persona_id)
        asset_q = asset_q.eq("persona_id", persona_id)

    attention_rows = _q(attention_q)
    approved_rows = _q(approved_q)
    kb_rows = _q(kb_q)
    asset_rows = _q(asset_q)
    error_rows = [
        row for row in get_error_logs(limit=500)
        if str(row.get("created_at") or row.get("ts") or "") >= today
    ]

    return {
        "pending_attention": len(attention_rows),
        "approved_today": len(approved_rows),
        "kb_entries": len(kb_rows),
        "assets_pending": len(asset_rows),
        "errors_24h": len(error_rows),
    }


# ── Storage ───────────────────────────────────────────────────────────────

def upload_to_storage(bucket: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to Supabase Storage; returns the public URL."""
    client = get_client()
    client.storage.from_(bucket).upload(path, data, {"content-type": content_type, "upsert": "true"})
    return client.storage.from_(bucket).get_public_url(path)


# ── KB Intake tracking ─────────────────────────────────────────────────────

def insert_kb_intake(data: dict) -> dict:
    result = get_client().table("kb_intake").insert(data).execute()
    return (result.data or [{}])[0]


# ── Knowledge Items: multi-status query ───────────────────────────────────

def get_knowledge_items_multi(
    statuses: list[str],
    persona_id: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list:
    q = (
        get_client().table("knowledge_items")
        .select("*")
        .in_("status", statuses)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if content_type:
        q = q.eq("content_type", content_type)
    return _q(q)

import os
import re
import base64
import time
import unicodedata
import json
from datetime import datetime, timedelta, timezone
import httpx
from supabase import create_client, Client, ClientOptions
from typing import Any, Optional

from services.public_site import DEFAULT_FORMATS

_client: Optional[Client] = None
_UNSET = object()
EXPECTED_DB_ROLE = "brain_runtime"
_TRANSIENT_ERROR_MARKERS = (
    "Server disconnected",
    "RemoteProtocolError",
    "ReadError",
    "ConnectError",
    "TimeoutException",
    "Connection reset",
)


def _supabase_ssl_verify() -> bool:
    raw = (os.environ.get("SUPABASE_SSL_VERIFY") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    runtime = (os.environ.get("ENV") or os.environ.get("PYTHON_ENV") or "").strip().lower()
    return runtime == "production"


def _validated_db_jwt() -> str:
    token = (os.environ.get("BRAIN_DB_JWT") or "").strip()
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("BRAIN_DB_JWT must be a valid role-scoped JWT") from exc
    role = str(payload.get("role") or "")
    if role != EXPECTED_DB_ROLE:
        raise RuntimeError(
            f"BRAIN_DB_JWT role must be {EXPECTED_DB_ROLE!r}, got {role!r}"
        )
    return token


def get_client() -> Client:
    global _client
    if _client is None:
        if (os.environ.get("SUPABASE_OFFLINE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise RuntimeError(
                "Supabase access is disabled for this deterministic test run"
            )
        timeout_seconds = float(os.environ.get("SUPABASE_HTTP_TIMEOUT_SECONDS") or "120")
        http_client = httpx.Client(verify=_supabase_ssl_verify(), timeout=timeout_seconds)
        _client = create_client(
            os.environ["SUPABASE_URL"],
            _validated_db_jwt(),
            options=ClientOptions(httpx_client=http_client),
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
    retries = int(os.environ.get("SUPABASE_RETRY_ATTEMPTS") or retries)
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


# â”€â”€ Safe query helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# All public functions use _q() / _one() so that:
#   â€¢ A None result never causes AttributeError
#   â€¢ A missing table returns a safe default instead of a 500

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
    insert succeeded but PostgREST returned no row data â€” an anomalous shape that
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


# â”€â”€ Leads â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    if lead_ref is not None:
        existing = get_lead_by_ref(lead_ref)
    elif persona_id:
        existing = _one(
            client.table("leads").select("*")
            .eq("persona_id", persona_id).eq("lead_id", lead_id).maybe_single()
        )
    else:
        existing = get_lead(lead_id)
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


def get_leads(
    persona_slug: Optional[str] = None, limit: int = 100, offset: int = 0,
    since_hours: int | None = None,
) -> list:
    try:
        q = get_client().table("leads").select("*")
        if persona_slug:
            persona_id = _resolve_persona_id(persona_slug) or persona_slug
            q = q.eq("persona_id", persona_id)
        if since_hours is not None:
            q = q.gte(
                "created_at",
                (datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours)))).isoformat(),
            )
        return _q(q.order("updated_at", desc=True).range(offset, offset + limit - 1))
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"get_leads failed: {exc}", exc)
        except Exception:
            pass
        return []


def get_leads_for_persona_ids(
    persona_ids: list[str], limit: int = 100, offset: int = 0,
    since_hours: int | None = None,
) -> list:
    ids = [pid for pid in persona_ids if pid]
    if not ids:
        return []
    try:
        q = (
            get_client()
            .table("leads")
            .select("*")
            .in_("persona_id", ids)
        )
        if since_hours is not None:
            q = q.gte(
                "created_at",
                (datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours)))).isoformat(),
            )
        return _q(q.order("updated_at", desc=True).range(offset, offset + limit - 1))
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"get_leads_for_persona_ids failed: {exc}", exc)
        except Exception:
            pass
        return []


def update_lead(lead_ref: int, data: dict) -> None:
    _execute_with_retry(get_client().table("leads").update(data).eq("id", lead_ref))


def merge_commercial_note(metadata: dict, commercial_note: dict[str, str]) -> dict:
    """Apply a manual commercial-note edit into a lead's metadata.

    Shared by the admin (`routes.leads`) and client-portal (`routes.portal`)
    lead-update endpoints so an edit made from either surface lands the
    same way: the display-only `commercial_note` mirror AND
    `conversation_state.appointment_request` (the AI's actual working
    memory) both get the new values, and any now-answered field is
    dropped from `missing_fields` so the next reply doesn't ask again.
    """
    clean_note = {
        str(k).strip(): str(v).strip()
        for k, v in commercial_note.items()
        if str(k).strip() and str(v).strip()
    }
    metadata = dict(metadata or {})
    metadata["commercial_note"] = {
        **clean_note,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
    }
    conversation_state = dict(metadata.get("conversation_state") or {})
    appointment_request = dict(conversation_state.get("appointment_request") or {})
    appointment_request.update(clean_note)
    conversation_state["appointment_request"] = appointment_request
    missing_fields = list(conversation_state.get("missing_fields") or [])
    conversation_state["missing_fields"] = [
        field for field in missing_fields if field not in clean_note
    ]
    metadata["conversation_state"] = conversation_state
    return metadata


def get_lead_by_ref(lead_ref: int) -> Optional[dict]:
    """Fetch a lead row by its integer primary key (`leads.id`)."""
    return _one(get_client().table("leads").select("*").eq("id", lead_ref).maybe_single())

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
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault(
        "kind",
        "legacy_import_bucket" if (data.get("source_type") == "import" or data.get("slug") == "import") else "semantic_group",
    )
    payload = {
        "persona_id": data.get("persona_id"),
        "slug": _slugify(data.get("slug") or data.get("name") or "audience"),
        "name": data.get("name") or "Audience",
        "description": data.get("description"),
        "source_type": data.get("source_type") or "manual",
        "is_system": bool(data.get("is_system", False)),
        "created_by_user_id": data.get("created_by_user_id"),
        "metadata": metadata,
    }
    return _insert_one(get_client().table("audiences").insert(payload))


def update_audience(audience_id: str, data: dict) -> Optional[dict]:
    payload = {
        "name": data.get("name"),
        "description": data.get("description"),
        "updated_at": data.get("updated_at"),
        "metadata": data.get("metadata"),
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
    since_hours: int | None = None,
) -> list[dict]:
    lead_refs = get_lead_refs_for_audience_scope(persona_id=persona_id, audience_id=audience_id, audience_slug=audience_slug)
    if not lead_refs:
        return []
    query = (
        get_client().table("leads").select("*")
        .in_("id", lead_refs).order("updated_at", desc=True)
    )
    if since_hours is not None:
        query = query.gte(
            "created_at",
            (datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours)))).isoformat(),
        )
    query = query.range(offset, offset + limit - 1)
    rows = _q(query)
    page_refs = [int(row["id"]) for row in rows if row.get("id") is not None]
    memberships_map = {lead_id: get_lead_memberships(lead_id) for lead_id in page_refs}
    return [{**row, "memberships": memberships_map.get(row.get("id"), [])} for row in rows]


# â”€â”€ Messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_messages(lead_id: str, limit: int = 30) -> list:
    """
    Fetch the most recent `limit` messages for a lead, returned in ascending
    (chronological chat) order.

    The DB query orders descending so `.limit()` keeps the newest rows, then
    `_sort_messages_for_chat` flips them back to display order. Querying
    ascending-then-limit (the previous behavior) silently returned the
    *oldest* `limit` messages for any lead with more history than that —
    every caller expecting recent context (AI conversation history, the
    bot-echo-loop guard) was reading from the start of the conversation
    instead. Confirmed live 2026-08-02: a lead with 143 messages had its
    echo-loop guard permanently matching a 6-day-old outbound reply because
    that old row never left the first-20-messages window.
    The self-hosted schema uses ``messages.lead_id``.  ``lead_ref`` remains a
    response compatibility alias through ``_normalize_message_row``.
    """
    client = get_client()

    # Primary: lead_id in the self-hosted/local-first schema.
    try:
        import re as _re
        digits = _re.sub(r"\D", "", lead_id or "")
        if digits and len(digits) <= 10:
            rows = _q(
                client.table("messages")
                .select("*")
                .eq("lead_id", int(digits))
                .order("created_at", desc=True)
                .order("id", desc=True)
                .limit(limit)
            )
            if rows:
                return _sort_messages_for_chat([_normalize_message_row(row) for row in rows])
    except Exception:
        pass

    # Name lookup belongs to leads; messages do not carry a duplicated nome.
    if lead_id and not lead_id.isdigit():
        lead = _one(client.table("leads").select("id").eq("nome", lead_id).maybe_single())
        if lead and lead.get("id") is not None:
            rows = _q(
                client.table("messages")
                .select("*")
                .eq("lead_id", lead["id"])
                .order("created_at", desc=True)
                .order("id", desc=True)
                .limit(limit)
            )
            return _sort_messages_for_chat([_normalize_message_row(row) for row in rows])

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


def backdate_lead_messages(lead_ref: int, hours: float) -> int:
    """Test-only: shift a lead's messages.created_at backward by N hours.

    Used by the WA Validator to simulate a genuine time gap between a
    scripted phase and a later one (see migration 104).
    """
    result = get_client().rpc(
        "backdate_lead_messages", {"p_lead_ref": lead_ref, "p_hours": hours}
    ).execute()
    return int(getattr(result, "data", 0) or 0)


def _normalize_message_row(row: dict) -> dict:
    normalized = dict(row or {})
    if "texto" not in normalized and normalized.get("content") is not None:
        normalized["texto"] = normalized.get("content")
    if "canal" not in normalized and normalized.get("channel") is not None:
        normalized["canal"] = normalized.get("channel")
    if "lead_ref" not in normalized and normalized.get("lead_id") is not None:
        normalized["lead_ref"] = normalized.get("lead_id")
    if "sender_type" not in normalized and normalized.get("role") is not None:
        role = str(normalized.get("role") or "").lower()
        normalized["sender_type"] = "client" if role in {"user", "client", "human"} else "ai"
    if "message_id" not in normalized and normalized.get("sender_id") is not None:
        normalized["message_id"] = normalized.get("sender_id")
    return normalized


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
        q = q.in_("lead_id", lead_refs)
    elif persona_id:
        leads = _q(
            client.table("leads")
            .select("id")
            .eq("persona_id", persona_id)
        )
        lead_refs = [lead.get("id") for lead in leads if lead.get("id") is not None]
        if not lead_refs:
            return []
        q = q.in_("lead_id", lead_refs)
    return [_normalize_message_row(row) for row in _q(q)]

def insert_message(data: dict) -> None:
    client = get_client()
    sender_type = str(data.get("sender_type") or "").lower()
    direction = str(data.get("direction") or "").lower()
    role = data.get("role")
    if not role:
        role = "assistant" if sender_type in {"ai", "assistant"} or direction == "outbound" else "user"

    mapped = {
        "lead_id": data.get("lead_id") or data.get("lead_ref"),
        "role": role,
        "content": data.get("content") or data.get("texto") or "",
        "direction": data.get("direction"),
        "status": data.get("status"),
        "channel": data.get("channel") or data.get("canal"),
        "sender_id": data.get("sender_id") or data.get("message_id"),
        "whatsapp_phone_number_id": data.get("whatsapp_phone_number_id"),
        "external_message_id": data.get("external_message_id"),
        "channel_binding_id": data.get("channel_binding_id"),
        "correlation_id": data.get("correlation_id"),
        "metadata": data.get("metadata"),
        "created_at": data.get("created_at"),
    }
    mapped = {k: v for k, v in mapped.items() if v is not None}
    try:
        _execute_with_retry(client.table("messages").insert(mapped))
        return
    except Exception as exc:
        text = str(exc)
        if data.get("external_message_id") and any(
            marker in text.lower() for marker in ("duplicate", "unique", "23505")
        ):
            return
        current_column_mismatch = any(
            marker in text
            for marker in (
                "messages.lead_id does not exist",
                "messages.role does not exist",
                "messages.content does not exist",
                "messages.channel does not exist",
                "messages.sender_id does not exist",
            )
        )
        if not current_column_mismatch:
            raise
    # Compatibility fallback for a legacy remote schema.
    _execute_with_retry(client.table("messages").insert(data))


# â”€â”€ Knowledge Graph: nodes & edges (migration 008) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


def update_knowledge_node(node_id: str, data: dict, *, mark_related_faqs: bool = True) -> Optional[dict]:
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not node_id or not data:
        return None
    try:
        client = get_client()
        payload = dict(data)
        payload.setdefault("updated_at", __import__("datetime").datetime.utcnow().isoformat())
        result = client.table("knowledge_nodes").update(payload).eq("id", node_id).execute()
        updated = (result.data or [payload])[0]
        node_type = updated.get("node_type")
        if not node_type:
            row = (client.table("knowledge_nodes").select("id,node_type,persona_id,source_id").eq("id", node_id).limit(1).execute().data or [None])[0]
        else:
            row = updated
        if mark_related_faqs and row and row.get("node_type") in {"brand", "briefing", "audience", "product", "offer", "copy", "rule"}:
            _mark_persona_faqs_pending_regeneration(
                row.get("persona_id"),
                changed_source_id=row.get("source_id") or node_id,
                now_iso=payload["updated_at"],
            )
        return updated
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise

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


def demote_duplicate_primary_edges_for_pair(source_node_id: str, target_node_id: str, except_relation_type: Optional[str] = None) -> int:
    """Keep one visible primary-tree edge per source -> target pair.

    Alternate relation labels can remain as lineage/semantic edges, but they
    must not render as separate primary-tree branches.
    """
    if _KG_TABLES_MISSING or not source_node_id or not target_node_id:
        return 0
    client = get_client()
    rows = _q(
        client.table("knowledge_edges")
        .select("id,relation_type,metadata")
        .eq("source_node_id", source_node_id)
        .eq("target_node_id", target_node_id)
        .limit(500)
    )
    changed = 0
    for row in rows:
        if except_relation_type and (row.get("relation_type") or "").lower() == except_relation_type.lower():
            continue
        metadata = row.get("metadata") or {}
        if metadata.get("primary_tree") is not True or metadata.get("active") is False:
            continue
        next_metadata = {
            **metadata,
            "primary_tree": False,
            "visual_hidden": True,
            "active": True,
            "demoted_from_primary_tree": "duplicate_source_target",
        }
        _execute_with_retry(
            client.table("knowledge_edges").update({"metadata": next_metadata}).eq("id", row["id"])
        )
        changed += 1
    return changed


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
    original_relation_type = relation_type
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
    if is_primary_path and (relation_type or "").lower() == "about_product":
        try:
            type_rows = (
                client.table("knowledge_nodes")
                .select("id,node_type")
                .in_("id", [source_node_id, target_node_id])
                .limit(2)
                .execute()
                .data
                or []
            )
            types = {row.get("id"): (row.get("node_type") or "").lower() for row in type_rows}
            if types.get(source_node_id) == "audience" and types.get(target_node_id) == "product":
                requested_metadata.setdefault("canonicalized_relation_from", relation_type)
                relation_type = "offers_product"
                if relation_type != original_relation_type:
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
        except Exception:
            pass
    if is_primary_path and (relation_type or "").lower() == "belongs_to_persona":
        try:
            source_rows = (
                client.table("knowledge_nodes")
                .select("id,node_type")
                .eq("id", source_node_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            source_type = (source_rows[0].get("node_type") if source_rows else "").lower()
            if source_type == "persona":
                active_parents = (
                    client.table("knowledge_edges")
                    .select("source_node_id,relation_type,metadata")
                    .eq("target_node_id", target_node_id)
                    .limit(500)
                    .execute()
                    .data
                    or []
                )
                non_persona_primary = [
                    edge for edge in active_parents
                    if edge.get("source_node_id") != source_node_id
                    and not _edge_is_inactive(edge)
                    and (edge.get("metadata") or {}).get("primary_tree") is True
                ]
                if non_persona_primary:
                    requested_metadata["primary_tree"] = False
                    requested_metadata["visual_hidden"] = True
                    is_primary_path = False
        except Exception:
            pass

    if is_primary_path:
        deactivate_primary_paths_for_target(target_node_id, except_source_node_id=source_node_id)
        demote_duplicate_primary_edges_for_pair(source_node_id, target_node_id, except_relation_type=relation_type)

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
            "primary_tree": False,
            "visual_hidden": True,
            "deleted_at": now_iso,
            "deleted_from": "graph_ui_reparent",
        }
        _execute_with_retry(
            client.table("knowledge_edges").update({"metadata": next_metadata}).eq("id", row["id"])
        )
        changed += 1
    return changed

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
        rows = _q(q.order("created_at", desc=True).limit(5))
        for row in rows:
            if row.get("status") != "deleted":
                return row
        return rows[0] if rows else None
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
        # PostgREST `or_` filter â€” slug exact match | title ILIKE | tag contains
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

# Node ids are rendered into the query string, so the batch stays well under
# any gateway URL limit.
_EDGE_LOOKUP_BATCH = 100


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
    # Batched on purpose: `in_` renders every id into the query string, so a
    # large graph produced a URL the gateway rejects. The failure used to be
    # swallowed into "no edges", which is indistinguishable from a genuinely
    # edgeless graph -- and callers act on that. graph_bundle_publisher's
    # preflight, for one, would see an empty existing-edge set and wave through
    # a bundle that silently orphans every live edge. An unreadable graph must
    # raise, never look empty.
    eq_in_source: list[dict] = []
    for start in range(0, len(node_ids), _EDGE_LOOKUP_BATCH):
        batch = node_ids[start:start + _EDGE_LOOKUP_BATCH]
        try:
            rows = (
                client.table("knowledge_edges").select("*")
                .in_("source_node_id", batch).limit(5000).execute().data
            ) or []
        except Exception as exc:
            if _kg_unavailable(exc):
                _KG_TABLES_MISSING = True
                return [], []
            raise
        eq_in_source.extend(rows)
    active_edges = [edge for edge in eq_in_source if not _edge_is_inactive(edge)]
    return nodes, active_edges

# â”€â”€ Registries (migration 009) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Cached in-memory with short TTL â€” config rarely changes and the graph
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
    {"node_type": "offer",          "label": "Oferta",    "default_level": 45, "default_importance": 0.78, "color": "#38bdf8", "icon": "badge-dollar-sign", "sort_order": 45},
    {"node_type": "briefing",       "label": "Briefing",  "default_level": 50, "default_importance": 0.75, "color": "#c084fc", "icon": "file-text",   "sort_order": 50},
    {"node_type": "audience",       "label": "AudiÃªncia", "default_level": 55, "default_importance": 0.70, "color": "#f472b6", "icon": "users",       "sort_order": 55},
    {"node_type": "tone",           "label": "Tom",       "default_level": 60, "default_importance": 0.70, "color": "#22d3ee", "icon": "palette",     "sort_order": 60},
    {"node_type": "rule",           "label": "Regra",     "default_level": 65, "default_importance": 0.80, "color": "#f87171", "icon": "scale",       "sort_order": 65},
    {"node_type": "copy",           "label": "Copy",      "default_level": 70, "default_importance": 0.65, "color": "#64748b", "icon": "text",        "sort_order": 70},
    {"node_type": "faq",            "label": "FAQ",       "default_level": 75, "default_importance": 0.45, "color": "#4ade80", "icon": "circle-help", "sort_order": 75},
    {"node_type": "asset",          "label": "Asset",     "default_level": 80, "default_importance": 0.55, "color": "#f59e0b", "icon": "image",       "sort_order": 80},
    {"node_type": "gallery",        "label": "Gallery",   "default_level":112, "default_importance": 0.82, "color": "#f0abfc", "icon": "images",      "sort_order":112},
    {"node_type": "embedded",       "label": "Golden Dataset", "default_level":120, "default_importance": 0.78, "color": "#ffffff", "icon": "database",    "sort_order":120},
    {"node_type": "tag",            "label": "Tag",       "default_level": 90, "default_importance": 0.30, "color": "#94a3b8", "icon": "tag",         "sort_order": 90},
    {"node_type": "mention",        "label": "MenÃ§Ã£o",    "default_level": 92, "default_importance": 0.25, "color": "#94a3b8", "icon": "at-sign",     "sort_order": 92},
    {"node_type": "knowledge_item", "label": "Fila",      "default_level": 95, "default_importance": 0.40, "color": "#94a3b8", "icon": "inbox",       "sort_order": 95},
    {"node_type": "kb_entry",       "label": "Golden Dataset Entry", "default_level": 95, "default_importance": 0.50, "color": "#94a3b8", "icon": "database",    "sort_order": 96},
]

_RELATION_TYPE_REGISTRY_FALLBACK: list[dict] = [
    {"relation_type": "belongs_to_persona", "label": "pertence Ã  persona", "inverse_label": "possui",        "default_weight": 1.00, "directional": True,  "sort_order":  10},
    {"relation_type": "defines_brand",      "label": "define brand",       "inverse_label": "Ã© definido por", "default_weight": 0.90, "directional": True,  "sort_order":  20},
    {"relation_type": "has_tone",           "label": "usa tom",            "inverse_label": "tom de",         "default_weight": 0.80, "directional": True,  "sort_order":  30},
    {"relation_type": "about_product",      "label": "sobre produto",      "inverse_label": "tem conhecimento", "default_weight": 0.85, "directional": True, "sort_order":  40},
    {"relation_type": "part_of_campaign",   "label": "parte da campanha",  "inverse_label": "contÃ©m",         "default_weight": 0.75, "directional": True,  "sort_order":  50},
    {"relation_type": "supports_campaign",  "label": "apoia campanha",     "inverse_label": "apoiada por",    "default_weight": 0.70, "directional": True,  "sort_order":  55},
    {"relation_type": "answers_question",   "label": "responde pergunta",  "inverse_label": "Ã© respondido por", "default_weight": 0.80, "directional": True, "sort_order":  60},
    {"relation_type": "supports_copy",      "label": "suporta copy",       "inverse_label": "Ã© suportado por", "default_weight": 0.70, "directional": True,  "sort_order":  70},
    {"relation_type": "uses_asset",         "label": "usa asset",          "inverse_label": "Ã© usado por",    "default_weight": 0.65, "directional": True,  "sort_order":  80},
    {"relation_type": "gallery_asset",      "label": "na gallery",         "inverse_label": "contÃ©m",         "default_weight": 0.90, "directional": True,  "sort_order":  82},
    {"relation_type": "briefed_by",         "label": "briefado por",       "inverse_label": "briefa",         "default_weight": 0.70, "directional": True,  "sort_order":  90},
    {"relation_type": "same_topic_as",      "label": "mesmo tÃ³pico",       "inverse_label": "mesmo tÃ³pico",   "default_weight": 0.45, "directional": False, "sort_order": 100},
    {"relation_type": "duplicate_of",       "label": "duplicado de",       "inverse_label": "tem duplicado",  "default_weight": 1.00, "directional": True,  "sort_order": 110},
    {"relation_type": "derived_from",       "label": "derivado de",        "inverse_label": "origina",        "default_weight": 0.90, "directional": True,  "sort_order": 120},
    {"relation_type": "contains",           "label": "contÃ©m",             "inverse_label": "contido em",     "default_weight": 0.75, "directional": True,  "sort_order": 130},
    {"relation_type": "has_tag",            "label": "tem tag",            "inverse_label": "marca",          "default_weight": 0.30, "directional": True,  "sort_order": 200},
    {"relation_type": "mentions",           "label": "menciona",           "inverse_label": "mencionado por", "default_weight": 0.30, "directional": True,  "sort_order": 210},
    {"relation_type": "visible_to_agent",   "label": "visÃ­vel para agente", "inverse_label": "vÃª",            "default_weight": 0.50, "directional": True,  "sort_order": 220},
]

# â”€â”€ Insights â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ System Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def insert_health_snapshot(data: dict) -> None:
    get_client().table("system_health").insert(data).execute()


def ping_supabase() -> tuple[bool, Optional[str]]:
    try:
        _execute_with_retry(get_client().table("app_users").select("id").limit(1))
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_health_history(limit: int = 30) -> list:
    rows = _q(
        get_client().table("system_health")
        .select("*")
        .order("snapshot_at", desc=True)
        .limit(limit)
    )
    return list(reversed(rows))


# â”€â”€ Integration Status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def upsert_integration_status(data: dict) -> None:
    client = get_client()
    persona_id = data.get("persona_id")
    service = data["service"]
    if persona_id is None:
        # maybe_single() throws 406 if duplicates exist â€” use limit(1) instead
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


def list_user_integration_connections(user_id: str) -> list[dict[str, Any]]:
    if not user_id:
        return []
    return _q(
        get_client()
        .table("user_integration_connections")
        .select("*")
        .eq("user_id", user_id)
        .order("service")
    )


def get_user_integration_connection(user_id: str, service: str) -> Optional[dict[str, Any]]:
    if not user_id or not service:
        return None
    rows = _q(
        get_client()
        .table("user_integration_connections")
        .select("*")
        .eq("user_id", user_id)
        .eq("service", service)
        .limit(1)
    )
    return rows[0] if rows else None


def upsert_user_integration_connection(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = dict(data or {})
    now_iso = datetime.now(timezone.utc).isoformat()
    payload.setdefault("config_json", {})
    payload["updated_at"] = now_iso
    payload.setdefault("created_at", now_iso)
    result = _execute_with_retry(
        get_client()
        .table("user_integration_connections")
        .upsert(payload, on_conflict="user_id,service")
    )
    rows = result.data or []
    if rows:
        return rows[0]
    return get_user_integration_connection(payload.get("user_id"), payload.get("service"))


def list_persona_integration_connections(persona_id: str) -> list[dict[str, Any]]:
    if not persona_id:
        return []
    return _q(
        get_client()
        .table("user_integration_connections")
        .select("*")
        .eq("persona_id", persona_id)
        .order("service")
    )


def get_persona_integration_connection(
    persona_id: str,
    service: str,
) -> Optional[dict[str, Any]]:
    if not persona_id or not service:
        return None
    rows = _q(
        get_client()
        .table("user_integration_connections")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("service", service)
        .limit(1)
    )
    return rows[0] if rows else None


def save_persona_integration_connection(
    data: dict[str, Any],
) -> Optional[dict[str, Any]]:
    payload = dict(data or {})
    persona_id = str(payload.get("persona_id") or "")
    service = str(payload.get("service") or "")
    if not persona_id or not service:
        raise ValueError("persona_id and service are required")
    now_iso = datetime.now(timezone.utc).isoformat()
    payload.setdefault("config_json", {})
    payload["updated_at"] = now_iso
    existing = get_persona_integration_connection(persona_id, service)
    if existing:
        rows = (
            _execute_with_retry(
                get_client()
                .table("user_integration_connections")
                .update(payload)
                .eq("id", existing["id"])
            ).data
            or []
        )
        return rows[0] if rows else get_persona_integration_connection(persona_id, service)
    payload.setdefault("created_at", now_iso)
    rows = (
        _execute_with_retry(
            get_client().table("user_integration_connections").insert(payload)
        ).data
        or []
    )
    return rows[0] if rows else get_persona_integration_connection(persona_id, service)


# â”€â”€ Personas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_personas() -> list:
    return _q(get_client().table("personas").select("*").eq("active", True))


def get_persona(slug: str) -> Optional[dict]:
    return _one(get_client().table("personas").select("*").eq("slug", slug).maybe_single())


def get_persona_by_id(persona_id: str) -> Optional[dict]:
    return _one(get_client().table("personas").select("*").eq("id", persona_id).maybe_single())


def get_persona_configs_by_ids(
    persona_ids: list[str], *, chunk_size: int = 50,
) -> dict[str, dict]:
    """`config` de várias personas numa leitura, para decorar listas de leads.

    A tela de Mensagens precisa do `business_model` de cada lead para saber se
    o pedido é compra/entrega ou agendamento/conclusão. Uma consulta por lead
    seria N+1 numa lista de 500.
    """
    ids = sorted({str(value) for value in persona_ids if value})
    if not ids:
        return {}
    size = max(1, min(chunk_size, 100))
    configs: dict[str, dict] = {}
    for index in range(0, len(ids), size):
        for row in _q(
            get_client().table("personas").select("id,config")
            .in_("id", ids[index:index + size])
        ):
            if row.get("id"):
                configs[str(row["id"])] = dict(row.get("config") or {})
    return configs

_PERSONA_ROUTING_FIELDS = (
    "process_mode",
    "outbound_webhook_url",
    "outbound_webhook_secret",
    "inbound_webhook_token",
)


def get_persona_routing(slug: str) -> Optional[dict]:
    """Returns the routing config for a persona, or None if missing.

    Falls back gracefully when migration 011 is not yet applied (older
    columns will be missing â€” the function returns defaults so callers can
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
        "config": persona.get("config") or {},
        "outbound_webhook_url": persona.get("outbound_webhook_url"),
        "outbound_webhook_secret": persona.get("outbound_webhook_secret"),
        "inbound_webhook_token": persona.get("inbound_webhook_token"),
        "migration_applied": migration_applied,
        "routing_source": "persona_columns" if migration_applied else ("legacy_workflow_binding" if has_legacy_n8n else "default"),
    }

# â”€â”€ Knowledge Base â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_kb_entries(persona_id: Optional[str] = None, status: str = "ATIVO") -> list:
    q = get_client().table("kb_entries").select("id,persona_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if status:
        q = q.eq("status", status)
    return _q(q.order("prioridade"))

def _kb_entry_select():
    return (
        get_client()
        .table("kb_entries")
        .select("id,persona_id,kb_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
    )

_MISSING_COLUMN_RE = re.compile(r"Could not find the '([^']+)' column of '([^']+)'")

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

# â”€â”€ Agent Logs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    # Compose bootstraps the legacy table first and later expands it with the
    # modern columns. Insert the compatible superset first so NOT NULL legacy
    # fields are satisfied without intentionally generating a database error
    # for every log line.
    hybrid_payload = {
        **legacy_payload,
        **payload,
        "agent_name": legacy_payload["agent_name"],
        "status": legacy_payload["status"],
        "input": legacy_payload["input"],
        "output": legacy_payload["output"],
    }

    mode = _detect_agent_logs_schema_mode()
    attempts = (
        [hybrid_payload, payload, legacy_payload]
        if mode == "modern"
        else [legacy_payload, hybrid_payload, payload]
    )
    last_exc: Exception | None = None
    for candidate in attempts:
        try:
            _execute_with_retry(get_client().table("agent_logs").insert(candidate))
            return
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc


def get_agent_logs(
    lead_id: Optional[str] = None,
    limit: int = 50,
    persona_id: Optional[str] = None,
) -> list:
    fetch_limit = min(max(limit * 4, limit), 1000) if persona_id else limit
    q = get_client().table("agent_logs").select("*").order("created_at", desc=True).limit(fetch_limit)
    if lead_id:
        q = q.eq("lead_id", lead_id)
    rows = _q(q)
    normalized = [_normalize_agent_log_row(row) for row in rows]
    if persona_id:
        normalized = [
            row for row in normalized
            if str(
                row.get("persona_id")
                or (row.get("payload") or {}).get("persona_id")
                or (row.get("metadata") or {}).get("persona_id")
                or ""
            ) == str(persona_id)
        ]
    return normalized[:limit]


def get_error_logs(
    component: Optional[str] = None,
    limit: int = 100,
    persona_id: Optional[str] = None,
) -> list:
    rows = get_agent_logs(limit=limit, persona_id=persona_id)
    filtered = []
    for row in rows:
        level = str(row.get("level") or "").upper()
        if level not in {"ERROR", "WARN", "WARNING"}:
            continue
        if component and str(row.get("component") or row.get("agent_type") or "").lower() != component.lower():
            continue
        filtered.append(row)
    return filtered

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

# â”€â”€ Knowledge Items â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

# Mirrors the CHECK constraint on knowledge_items.content_type from
# supabase/migrations/002_knowledge_platform.sql. Keep in sync if the constraint changes.
KNOWLEDGE_ITEM_CONTENT_TYPES: frozenset[str] = frozenset({
    # Canonical fractal types (migration 039 + knowledge_taxonomy).
    "persona", "brand", "briefing", "campaign", "audience",
    "product_group", "product", "offer", "copy", "faq", "gallery", "asset",
    # Non-canonical but still accepted as input (kept for backwards-compat).
    "prompt", "maker_material", "tone", "competitor",
    "rule", "entity", "other",
})

KNOWLEDGE_ITEM_STATUSES: frozenset[str] = frozenset({
    "pending", "approved", "rejected", "embedded", "needs_update", "pending_regeneration",
})

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_KNOWLEDGE_ITEMS_MISSING_COLUMNS: set[str] = set()

def _mark_persona_faqs_pending_regeneration(persona_id: Optional[str], *, changed_source_id: Optional[str], now_iso: str) -> None:
    if not persona_id:
        return
    client = get_client()
    stale_meta = {
        "faq_status": "pending_regeneration",
        "needs_update": True,
        "stale_reason": "related_context_changed",
        "changed_source_id": changed_source_id,
        "stale_marked_at": now_iso,
    }
    try:
        faq_items = (
            client.table("knowledge_items")
            .select("id,metadata")
            .eq("persona_id", persona_id)
            .eq("content_type", "faq")
            .execute()
            .data or []
        )
        for item in faq_items:
            metadata = {**(item.get("metadata") or {}), **stale_meta}
            client.table("knowledge_items").update({
                "status": "pending_regeneration",
                "curation_status": "stale",
                "metadata": metadata,
                "updated_at": now_iso,
            }).eq("id", item["id"]).execute()
    except Exception:
        pass
    try:
        faq_nodes = (
            client.table("knowledge_nodes")
            .select("id,metadata")
            .eq("persona_id", persona_id)
            .eq("node_type", "faq")
            .execute()
            .data or []
        )
        for node in faq_nodes:
            metadata = {**(node.get("metadata") or {}), **stale_meta}
            client.table("knowledge_nodes").update({
                "status": "pending_regeneration",
                "metadata": metadata,
                "updated_at": now_iso,
            }).eq("id", node["id"]).execute()
    except Exception:
        pass

_APPROVED_SNAPSHOTS_MISSING = False

def search_active_rag_chunks(
    *,
    persona_id: str,
    query: str = "",
    limit: int = 12,
    branch_anchor_node_id: str | None = None,
    allowed_node_ids: list[str] | None = None,
    active_path_node_ids: list[str] | None = None,
    unresolved_fields: list[str] | None = None,
    graph_version: int | None = None,
) -> list[dict]:
    """Return persona-scoped Golden Dataset chunks before any legacy fallback.

    Text scoring stays deterministic and local for now; embeddings can replace
    the ranking without changing the caller contract.
    """
    if not persona_id:
        return []
    client = get_client()
    entries = _q(
        client.table("knowledge_rag_entries")
        .select("id,title,content_type,slug,status,metadata,canonical_key")
        .eq("persona_id", persona_id)
        .in_("status", ["active", "approved", "validated", "embedded"])
        .limit(2000)
    )
    entry_by_id = {str(row.get("id")): row for row in entries if row.get("id")}
    if not entry_by_id:
        return []
    chunks = _q(
        client.table("knowledge_rag_chunks")
        .select("id,rag_entry_id,persona_id,chunk_index,chunk_text,chunk_summary,metadata")
        .eq("persona_id", persona_id)
        .in_("rag_entry_id", list(entry_by_id))
        .limit(5000)
    )
    # WhatsApp questions commonly contain accents, punctuation and hyphenated
    # names (for example "Coca-Cola" / "preço").  Normalize both sides so a
    # lexical RAG fallback remains useful before embeddings are available.
    def _rag_terms(value: str) -> set[str]:
        normalized = unicodedata.normalize("NFKD", value or "")
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()
        return {part for part in re.findall(r"[a-z0-9]+", normalized) if len(part) > 1}

    terms = _rag_terms(query)
    allowed = set(allowed_node_ids or [])
    active_path = set(active_path_node_ids or [])
    pending = set(unresolved_fields or [])
    ranked: list[tuple[float, int, dict]] = []
    for chunk in chunks:
        entry = entry_by_id.get(str(chunk.get("rag_entry_id")))
        if not entry:
            continue
        metadata = {
            **(entry.get("metadata") or {}),
            **(chunk.get("metadata") or {}),
        }
        node_id = str(
            metadata.get("graph_json_node_id")
            or metadata.get("canonical_node_id")
            or metadata.get("source_node_id")
            or ""
        )
        chunk_branch = str(metadata.get("branch_anchor_node_id") or "")
        try:
            chunk_version = int(metadata.get("graph_version") or 0)
        except (TypeError, ValueError):
            chunk_version = 0
        if graph_version is not None and chunk_version not in {0, int(graph_version)}:
            continue
        if branch_anchor_node_id and not (
            chunk_branch == branch_anchor_node_id or node_id in allowed
        ):
            continue
        haystack = " ".join(
            [
                str(entry.get("title") or ""),
                str(entry.get("slug") or ""),
                str(chunk.get("chunk_text") or ""),
                str(chunk.get("chunk_summary") or ""),
            ]
        )
        normalized_haystack = " ".join(_rag_terms(haystack))
        semantic_score = sum(1 for term in terms if term in normalized_haystack)
        if terms and semantic_score == 0 and not branch_anchor_node_id:
            continue
        path_ids = set(metadata.get("path_node_ids") or [])
        path_overlap = len(path_ids & active_path) / max(1, len(active_path))
        field_key = str(metadata.get("field_key") or "")
        field_relevance = 1.0 if field_key and field_key in pending else 0.0
        try:
            priority = float(metadata.get("priority") or 0.0)
        except (TypeError, ValueError):
            priority = 0.0
        graph_proximity = 1.0 if chunk_branch == branch_anchor_node_id else path_overlap
        score = (
            float(semantic_score)
            + 1.25 * graph_proximity
            + 0.75 * path_overlap
            + 0.8 * field_relevance
            + 0.2 * priority
        )
        ranked.append(
            (
                score,
                -int(chunk.get("chunk_index") or 0),
                {**chunk, "entry": entry, "source": "golden_dataset"},
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit]]


def get_active_graph_publication(persona_id: str) -> Optional[dict]:
    if not persona_id:
        return None
    return _one(
        get_client().table("graph_publications").select("*")
        .eq("persona_id", persona_id).eq("status", "active")
        .maybe_single()
    )


def get_graph_publication_by_id(publication_id: str) -> Optional[dict]:
    """Load the immutable turn-pinned publication, regardless of active status."""
    if not publication_id:
        return None
    return _one(
        get_client().table("graph_publications").select("*")
        .eq("id", publication_id).maybe_single()
    )


def get_graph_turn_context_batch_v3(
    *, persona_id: str, lead_ref: int, message_limit: int = 8,
) -> dict:
    """Fetch publication, ledger, facts, branches and recent messages once."""
    result = get_client().rpc(
        "graph_turn_context_batch_v3",
        {
            "p_persona_id": persona_id,
            "p_lead_ref": lead_ref,
            "p_message_limit": max(1, min(int(message_limit), 20)),
        },
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def get_graph_turn_context_batch_v4(
    *, persona_id: str, lead_ref: int, message_limit: int = 8,
) -> dict:
    """Fetch v4 shared memory, falling back during a rolling deployment."""
    try:
        result = get_client().rpc(
            "graph_turn_context_batch_v4",
            {
                "p_persona_id": persona_id,
                "p_lead_ref": lead_ref,
                "p_message_limit": max(1, min(int(message_limit), 20)),
            },
        ).execute()
        value = getattr(result, "data", None)
        if isinstance(value, list):
            value = value[0] if value else {}
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    return get_graph_turn_context_batch_v3(
        persona_id=persona_id, lead_ref=lead_ref, message_limit=message_limit,
    )


def get_graph_branch_package_v3(
    *, publication_id: str, branch_node_id: str,
    chunk_ids: list[str] | None = None, node_ids: list[str] | None = None,
    limit: int = 12,
) -> dict:
    result = get_client().rpc(
        "graph_branch_package_v3",
        {
            "p_publication_id": publication_id,
            "p_branch_node_id": branch_node_id,
            "p_chunk_ids": chunk_ids or [],
            "p_node_ids": node_ids or [],
            "p_limit": max(1, min(int(limit), 12)),
        },
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}

def get_conversation_ledger(persona_id: str, lead_ref: int) -> Optional[dict]:
    if not persona_id or not lead_ref:
        return None
    journey = _one(
        get_client().table("conversation_journeys").select("id")
        .eq("persona_id", persona_id).eq("lead_ref", lead_ref)
        .eq("is_current", True).maybe_single()
    )
    if not journey:
        return None
    ledger = _one(
        get_client().table("conversation_ledgers").select("*")
        .eq("persona_id", persona_id).eq("lead_ref", lead_ref)
        .eq("journey_id", journey["id"]).maybe_single()
    )
    if not ledger:
        return None
    facts = _q(
        get_client().table("conversation_facts").select("*")
        .eq("ledger_id", ledger["id"]).eq("is_current", True).limit(1000)
    )
    ledger["facts"] = {
        str(row["field_key"]): {
            **row,
            "value": row.get("value_json"),
            "fact_id": row.get("id"),
        }
        for row in facts
    }
    grouped: dict[str, list[dict]] = {}
    for row in facts:
        grouped.setdefault(str(row["field_key"]), []).append({
            **row,
            "value": row.get("value_json"),
            "fact_id": row.get("id"),
        })
    ledger["facts_by_key"] = grouped
    ledger["active_branch_node_ids"] = get_active_ledger_branches(str(ledger["id"]))
    return ledger


def get_lead_carry_over_facts(
    persona_id: str, lead_ref: int, field_keys: list[str],
) -> list[dict]:
    """O valor `known` mais recente de cada campo, em qualquer jornada do lead.

    Diferente de get_journey_ledger_facts (uma jornada so): jornadas/pedidos
    ja registrados sao a fonte de verdade da identidade do cliente, entao a
    busca cobre o historico inteiro do lead, nao so a jornada anterior
    imediata -- um ponteiro de uma jornada so perdia o fato assim que uma
    segunda jornada fechasse antes do campo ser respondido de novo
    (confirmado ao vivo 2026-08-18).
    """
    if not persona_id or not lead_ref or not field_keys:
        return []
    try:
        result = get_client().rpc(
            "conversation_carry_over_facts_by_lead_v1",
            {"p_persona_id": persona_id, "p_lead_ref": lead_ref, "p_field_keys": field_keys},
        ).execute()
        return result.data or []
    except Exception:
        # Rolling-deploy compatibility until migration 129 is applied.
        pass
    ledgers = _q(
        get_client().table("conversation_ledgers").select("id")
        .eq("persona_id", persona_id).eq("lead_ref", lead_ref).limit(200)
    )
    ledger_ids = [row["id"] for row in ledgers if row.get("id")]
    if not ledger_ids:
        return []
    rows = _q(
        get_client().table("conversation_facts").select("*")
        .in_("ledger_id", ledger_ids).in_("field_key", field_keys)
        .eq("is_current", True).eq("status", "known")
        .order("created_at", desc=True).limit(1000)
    )
    latest_by_key: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("field_key") or "")
        if key and key not in latest_by_key:
            latest_by_key[key] = row
    return list(latest_by_key.values())

def get_current_conversation_journey(persona_id: str, lead_ref: int) -> Optional[dict]:
    if not persona_id or not lead_ref:
        return None
    return _one(
        get_client().table("conversation_journeys").select("*")
        .eq("persona_id", persona_id).eq("lead_ref", lead_ref)
        .eq("is_current", True).maybe_single()
    )


def get_journeys_by_lead_refs(
    persona_id: str, lead_refs: list[int], *, chunk_size: int = 100,
) -> list[dict]:
    """Every journey of many leads, in bounded batches.

    Same reasoning as ``get_leads_by_refs``: the conversation list paints every
    row at once, so one request per lead would be an N+1, and an unbounded
    ``in`` list would blow the PostgREST URL up.

    Deliberately *not* filtered by ``is_current``: a closed order must keep
    describing itself on screen, and the permanent "lead converted" fact lives
    in whichever journey converted first.
    """
    refs = sorted({int(value) for value in lead_refs if value is not None})
    if not persona_id or not refs:
        return []
    size = max(1, min(chunk_size, 100))
    rows: list[dict] = []
    for index in range(0, len(refs), size):
        rows.extend(_q(
            get_client().table("conversation_journeys")
            .select("lead_ref,state,is_current,converted_at,closed_at,sequence,metadata")
            .eq("persona_id", persona_id)
            .in_("lead_ref", refs[index:index + size])
        ))
    return rows


def get_latest_conversation_journey(persona_id: str, lead_ref: int) -> Optional[dict]:
    if not persona_id or not lead_ref:
        return None
    rows = _q(
        get_client().table("conversation_journeys").select("*")
        .eq("persona_id", persona_id).eq("lead_ref", lead_ref)
        .order("sequence", desc=True).limit(1)
    )
    return rows[0] if rows else None

def get_active_ledger_branches(ledger_id: str) -> list:
    if not ledger_id:
        return []
    try:
        rows = _q(
            get_client().table("conversation_ledger_branches").select("branch_anchor_node_id")
            .eq("ledger_id", ledger_id).eq("state", "active").limit(100)
        )
    except Exception:
        # migration 105 may not be applied yet on a deployment where this
        # code shipped ahead of it -- degrade to "no additional active
        # branches" (today's single-service behavior) instead of breaking
        # every single conversation turn over an optional, additive table.
        return []
    return [str(row["branch_anchor_node_id"]) for row in rows]


def get_ledger_branch_states(ledger_id: str) -> dict:
    """branch_anchor_node_id -> state, every branch ever tracked for this ledger.

    Unlike get_active_ledger_branches (state='active' only -- what every turn
    uses to seed active_branch_node_ids), this also surfaces 'completed'
    branches, so the runtime can tell "still needs its own confirmation cycle"
    apart from "already confirmed, just still open for support" once a
    journey has more than one active branch (product or service -- nothing
    here is offering-specific). Same migration-not-applied-yet tolerance as
    get_active_ledger_branches.
    """
    if not ledger_id:
        return {}
    try:
        rows = _q(
            get_client().table("conversation_ledger_branches")
            .select("branch_anchor_node_id,state")
            .eq("ledger_id", ledger_id).limit(200)
        )
    except Exception:
        return {}
    return {
        str(row.get("branch_anchor_node_id") or ""): str(row.get("state") or "")
        for row in rows or []
    }


def mark_ledger_branches_completed(ledger_id: str, branch_anchor_node_ids: list) -> None:
    """One-time grandfather write: see build_context's use in
    graph_agent_runtime_v3.py. A journey already in post_qualification_support
    the first time this code runs against it has no 'completed' row yet
    (migration 128 shipped after it was handed off); without this, every one
    of its already-confirmed branches would look indistinguishable from a
    brand new, never-confirmed one. Best-effort and idempotent (upsert), same
    tolerance as the other optional writes to this table.
    """
    if not ledger_id or not branch_anchor_node_ids:
        return
    try:
        get_client().table("conversation_ledger_branches").upsert(
            [
                {
                    "ledger_id": ledger_id, "branch_anchor_node_id": anchor,
                    "state": "completed", "completed_at": datetime.now(timezone.utc).isoformat(),
                }
                for anchor in dict.fromkeys(branch_anchor_node_ids)
            ],
            on_conflict="ledger_id,branch_anchor_node_id",
        ).execute()
    except Exception:
        pass

def get_wa_validator_session(session_id: str) -> Optional[dict]:
    """Read a WA Validator session's data blob, or None if it doesn't exist."""
    if not session_id:
        return None
    row = _one(
        get_client().table("wa_validator_sessions").select("data")
        .eq("id", session_id).maybe_single()
    )
    return row.get("data") if row else None


def upsert_wa_validator_session(
    session_id: str, data: dict, *, persona_slug: Optional[str] = None, flow_id: Optional[str] = None
) -> dict:
    """Write a WA Validator session's full data blob (create or replace)."""
    from datetime import datetime, timezone
    payload = {
        "id": session_id, "data": data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if persona_slug is not None:
        payload["persona_slug"] = persona_slug
    if flow_id is not None:
        payload["flow_id"] = flow_id
    rows = (
        get_client().table("wa_validator_sessions")
        .upsert(payload, on_conflict="id").execute().data or []
    )
    return rows[0]["data"] if rows else data


def list_wa_validator_sessions(
    limit: int = 100,
    *,
    persona_slug: str | None = None,
    since_hours: int | None = None,
) -> list[dict]:
    """Return a bounded, database-filtered WA Validator session window."""
    from datetime import datetime, timedelta, timezone

    query = get_client().table("wa_validator_sessions").select("data")
    if persona_slug:
        query = query.eq("persona_slug", persona_slug)
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours)))
        query = query.gte("created_at", cutoff.isoformat())
    rows = _q(query.order("created_at", desc=True).limit(max(1, min(int(limit), 100))))
    return [row["data"] for row in rows if row.get("data")]


def claim_wa_validator_session(session_id: str) -> dict:
    """Atomically transition one validator session from ready to running."""
    result = get_client().rpc(
        "claim_wa_validator_session", {"p_session_id": session_id}
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def enqueue_wa_validator_session(session_id: str, mode: str) -> dict:
    """Atomically enqueue a ready validator session for the worker process."""
    result = get_client().rpc(
        "enqueue_wa_validator_session",
        {"p_session_id": session_id, "p_mode": mode},
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def claim_next_wa_validator_session(worker_id: str) -> dict:
    """Lease the oldest queued validator session, if one is available."""
    result = get_client().rpc(
        "claim_next_wa_validator_session", {"p_worker_id": worker_id}
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def cleanup_wa_validator_artifacts(*, hours: int = 12, dry_run: bool = True) -> dict:
    """Inventory or transactionally remove expired canonical validator data."""
    result = get_client().rpc(
        "cleanup_wa_validator_artifacts",
        {"p_before": f"{max(1, int(hours))} hours", "p_dry_run": bool(dry_run)},
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def search_graph_rag_v3(
    *,
    persona_id: str,
    publication_id: str,
    branch_node_id: str,
    query: str,
    query_embedding: list[float] | None,
    active_path_node_ids: list[str] | None = None,
    missing_fields: list[str] | None = None,
    limit: int = 24,
) -> list[dict]:
    result = get_client().rpc(
        "graph_hybrid_search_v3",
        {
            "p_persona_id": persona_id,
            "p_publication_id": publication_id,
            "p_branch_node_id": branch_node_id,
            "p_query": query,
            "p_query_embedding": query_embedding,
            "p_active_path_node_ids": active_path_node_ids or [],
            "p_missing_fields": missing_fields or [],
            "p_limit": max(1, min(int(limit), 200)),
        },
    ).execute()
    return result.data or []


def search_graph_faq_v3(
    *,
    persona_id: str,
    publication_id: str,
    branch_node_id: str,
    query: str,
    query_embedding: list[float] | None,
    eligible_faq_node_ids: list[str],
    limit: int = 64,
) -> list[dict]:
    """Search only compiler-approved FAQ chunks inside one branch closure."""
    if not eligible_faq_node_ids:
        return []
    result = get_client().rpc(
        "graph_faq_search_v3",
        {
            "p_persona_id": persona_id,
            "p_publication_id": publication_id,
            "p_branch_node_id": branch_node_id,
            "p_query": query,
            "p_query_embedding": query_embedding,
            "p_eligible_faq_node_ids": eligible_faq_node_ids,
            "p_limit": max(1, min(int(limit), 200)),
        },
    ).execute()
    return result.data or []


def rank_graph_branches_v3(
    *,
    persona_id: str,
    publication_id: str,
    query: str,
    query_embedding: list[float] | None,
    limit: int = 8,
) -> list[dict]:
    result = get_client().rpc(
        "graph_branch_rank_v3",
        {
            "p_persona_id": persona_id,
            "p_publication_id": publication_id,
            "p_query": query,
            "p_query_embedding": query_embedding,
            "p_limit": max(1, min(int(limit), 32)),
        },
    ).execute()
    return result.data or []


def rank_graph_services_v3(
    *,
    persona_id: str,
    publication_id: str,
    query_embedding: list[float] | None,
    limit: int = 8,
) -> list[dict]:
    """Rank only chunks owned by published service anchors."""
    if query_embedding is None:
        return []
    result = get_client().rpc(
        "graph_service_rank_v3",
        {
            "p_persona_id": persona_id,
            "p_publication_id": publication_id,
            "p_query_embedding": query_embedding,
            "p_limit": max(1, min(int(limit), 32)),
        },
    ).execute()
    return result.data or []


def get_graph_rag_repair_chunks(
    *, publication_id: str, branch_node_id: str, requirements: list[dict]
) -> list[dict]:
    node_ids = [str(item.get("id")) for item in requirements if item.get("kind") == "node"]
    chunk_ids = [str(item.get("id")) for item in requirements if item.get("kind") == "chunk"]
    query = (
        get_client().table("knowledge_rag_chunks")
        .select("id,rag_entry_id,source_graph_node_id,branch_anchor_node_id,chunk_text,chunk_summary,chunk_kind,chunk_checksum,path_checksum,metadata")
        .eq("publication_id", publication_id).eq("branch_anchor_node_id", branch_node_id)
    )
    if chunk_ids and node_ids:
        # PostgREST has no portable OR builder across all supported client
        # versions; fetch two narrowly bounded sets and deduplicate below.
        chunks = _q(query.in_("id", chunk_ids).limit(200))
        nodes = _q(
            get_client().table("knowledge_rag_chunks")
            .select("id,rag_entry_id,source_graph_node_id,branch_anchor_node_id,chunk_text,chunk_summary,chunk_kind,chunk_checksum,path_checksum,metadata")
            .eq("publication_id", publication_id).eq("branch_anchor_node_id", branch_node_id)
            .in_("source_graph_node_id", node_ids).limit(200)
        )
        return list({str(row["id"]): row for row in [*chunks, *nodes]}.values())
    if chunk_ids:
        return _q(query.in_("id", chunk_ids).limit(200))
    if node_ids:
        return _q(query.in_("source_graph_node_id", node_ids).limit(200))
    return []


def commit_graph_turn_v3(**payload: Any) -> dict:
    result = get_client().rpc("commit_graph_turn_v3", payload).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def commit_graph_turn_and_outbox_v3(
    *, turn: dict, outbound_buffer: dict | None,
    outbound_message: dict | None, result_payload: dict,
) -> dict:
    result = get_client().rpc(
        "commit_graph_turn_and_outbox_v3",
        {
            "p_turn": turn,
            "p_outbound_buffer": outbound_buffer,
            "p_outbound_message": outbound_message,
            "p_result": result_payload,
        },
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def commit_graph_turn_and_outbox_v4(
    *, turn: dict, outbound_buffer: dict | None,
    outbound_message: dict | None, result_payload: dict,
) -> dict:
    """Atomic journey-aware commit with temporary v3 rolling fallback."""
    payload = {
        "p_turn": turn,
        "p_outbound_buffer": outbound_buffer,
        "p_outbound_message": outbound_message,
        "p_result": result_payload,
    }
    try:
        result = get_client().rpc("commit_graph_turn_and_outbox_v4", payload).execute()
        value = getattr(result, "data", None)
        if isinstance(value, list):
            value = value[0] if value else {}
        if isinstance(value, dict):
            return value
    except Exception:
        # A v3 fallback is safe only for a real journey.  Falling back for
        # journey_action=none would recreate the exact phantom-journey bug.
        if str(turn.get("journey_action") or "continue") == "none":
            raise
    return commit_graph_turn_and_outbox_v3(
        turn=turn, outbound_buffer=outbound_buffer,
        outbound_message=outbound_message, result_payload=result_payload,
    )


def audit_conversation_turn_v3(inbound_buffer_id: str) -> dict:
    result = get_client().rpc(
        "audit_conversation_turn_v3", {"p_inbound_id": inbound_buffer_id}
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def get_conversation_turn_proof(canonical_inbound_id: str) -> Optional[dict]:
    if not canonical_inbound_id:
        return None
    return _one(
        get_client().table("conversation_turn_proofs").select("*")
        .eq("canonical_inbound_id", canonical_inbound_id).maybe_single()
    )

def set_conversation_journey_state(**payload: Any) -> dict:
    """Estado-alvo do pedido, escolhido por um humano.

    Complementa ``record_conversation_journey_event``: aquele e append-only e
    idempotente (integracao e agente), este calcula o delta ate o alvo e sabe
    voltar atras.
    """
    result = get_client().rpc(
        "set_conversation_journey_state_v1", payload,
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def record_conversation_journey_event(**payload: Any) -> dict:
    result = get_client().rpc(
        "record_conversation_journey_event_v1", payload,
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def transition_sales_conversion_status(**payload: Any) -> dict:
    result = get_client().rpc(
        "transition_sales_conversion_status_v1", payload
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}

def list_inactivity_recovery_candidates(*, enabled_from: str, cutoff: str, limit: int = 100) -> list[dict]:
    return _q(
        get_client().table("lead_buffer").select("id,persona_id,lead_ref,created_at")
        .eq("direction", "inbound").eq("status", "buffered")
        .gte("created_at", enabled_from).lte("created_at", cutoff)
        .is_("payload->conversation_commit", "null")
        .order("created_at").limit(limit)
    )


def claim_inactivity_recovery_candidate(*, inbound_id: str) -> dict:
    result = get_client().rpc(
        "claim_inactivity_recovery_candidate_v1", {"p_inbound_id": inbound_id}
    ).execute()
    value = getattr(result, "data", None)
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}

# â”€â”€ Workflow Bindings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

def get_workflow_binding_by_id(binding_id: Optional[str]) -> Optional[dict]:
    if not binding_id:
        return None
    return _one(
        get_client().table("workflow_bindings").select("*")
        .eq("id", binding_id).maybe_single()
    )

def enqueue_whatsapp_envelope(
    *,
    buffer: dict,
    message: dict,
) -> dict:
    """Atomically create or resolve a WhatsApp message + durable buffer."""
    result = get_client().rpc(
        "enqueue_whatsapp_envelope",
        {"p_buffer": buffer, "p_message": message},
    ).execute()
    payload = getattr(result, "data", None)
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict) or not payload.get("buffer_id"):
        raise RuntimeError("enqueue_whatsapp_envelope returned an invalid result")
    return payload


def get_whatsapp_buffer_by_idempotency(idempotency_key: str) -> Optional[dict]:
    if not idempotency_key:
        return None
    return _one(
        get_client()
        .table("lead_buffer")
        .select("*")
        .eq("idempotency_key", idempotency_key)
        .maybe_single()
    )

def record_whatsapp_safety_violation(
    *,
    binding_id: str,
    lead_ref: int | None,
    violation_key: str,
    reason: str,
    level: str = "full",
) -> dict:
    result = get_client().rpc(
        "record_whatsapp_safety_violation",
        {
            "p_binding_id": binding_id,
            "p_lead_ref": lead_ref,
            "p_violation_key": violation_key,
            "p_reason": reason[:500],
            "p_level": level,
        },
    ).execute()
    payload = getattr(result, "data", None)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return payload if isinstance(payload, dict) else {}


def claim_conversation_commit(
    *,
    inbound_buffer_id: str,
    binding_id: str,
    lead_ref: int,
    correlation_id: str,
) -> dict:
    result = get_client().rpc(
        "claim_conversation_commit",
        {
            "p_inbound_buffer_id": inbound_buffer_id,
            "p_binding_id": binding_id,
            "p_lead_ref": lead_ref,
            "p_correlation_id": correlation_id,
        },
    ).execute()
    payload = getattr(result, "data", None)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return payload if isinstance(payload, dict) else {}


def complete_conversation_commit(
    *,
    inbound_buffer_id: str,
    binding_id: str,
    lead_ref: int,
    correlation_id: str,
    result_payload: dict,
) -> dict:
    result = get_client().rpc(
        "complete_conversation_commit",
        {
            "p_inbound_buffer_id": inbound_buffer_id,
            "p_binding_id": binding_id,
            "p_lead_ref": lead_ref,
            "p_correlation_id": correlation_id,
            "p_result": result_payload,
        },
    ).execute()
    payload = getattr(result, "data", None)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return payload if isinstance(payload, dict) else {}

def handoff_whatsapp_lead(lead_ref: int, *, level: str = "full") -> None:
    """Atomically set handoff_level and (for level='full') quarantine queued work."""
    _execute_with_retry(
        get_client().rpc(
            "handoff_whatsapp_lead", {"p_lead_ref": lead_ref, "p_level": level}
        )
    )


def requeue_waiting_human_whatsapp_buffer(lead_ref: int) -> int:
    """Move a lead's stuck inbound messages back into the claimable queue.

    Resuming AI on a lead does nothing on its own to messages that piled up
    in `waiting_human` while it was paused — this is the retroactive
    reprocessing step that was missing.
    """
    result = get_client().rpc(
        "requeue_waiting_human_whatsapp_buffer", {"p_lead_ref": lead_ref}
    ).execute()
    return int(getattr(result, "data", 0) or 0)


def handoff_whatsapp_lead_state(
    lead_ref: int,
    *,
    metadata: dict,
    stage: str,
    level: str = "full",
) -> None:
    """Atomically persist the cart/stage and set handoff_level.

    level='partial' keeps the lead's inbound lead_buffer rows claimable (the
    AI keeps running); only level='full' quarantines them as waiting_human.
    """
    _execute_with_retry(
        get_client().rpc(
            "handoff_whatsapp_lead_state",
            {
                "p_lead_ref": lead_ref,
                "p_metadata": metadata,
                "p_stage": stage,
                "p_level": level,
            },
        )
    )

# -- Campaign delivery one -------------------------------------------------------

def create_lead_import_batch(data: dict) -> dict:
    return _insert_one(get_client().table("lead_import_batches").insert(data))


def update_lead_import_batch(batch_id: str, data: dict) -> Optional[dict]:
    result = _execute_with_retry(
        get_client().table("lead_import_batches").update(data).eq("id", batch_id)
    )
    return (result.data or [None])[0] if result else None


def insert_lead_import_row(data: dict) -> dict:
    return _insert_one(get_client().table("lead_import_rows").insert(data))


def list_lead_import_batches(persona_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    query = get_client().table("lead_import_batches").select("*").order("created_at", desc=True).limit(limit)
    if persona_id:
        query = query.eq("persona_id", persona_id)
    return _q(query)


def get_lead_import_batch(batch_id: str) -> Optional[dict]:
    return _one(
        get_client().table("lead_import_batches").select("*").eq("id", batch_id).maybe_single()
    )


def list_lead_import_rows(batch_id: str, limit: int = 5000) -> list[dict]:
    return _q(
        get_client().table("lead_import_rows").select("*")
        .eq("batch_id", batch_id).order("row_index").limit(limit)
    )


def replace_lead_semantic_group(
    *,
    lead_id: int,
    persona_id: str,
    audience_id: str,
    created_by_user_id: Optional[str],
    idempotency_key: str,
    reason: str,
) -> dict:
    audience = get_audience(audience_id)
    if not audience or audience.get("persona_id") != persona_id:
        raise ValueError("audience does not belong to persona")
    if str((audience.get("metadata") or {}).get("kind") or "semantic_group") != "semantic_group":
        raise ValueError("audience is not a semantic group")
    result = _execute_with_retry(get_client().rpc("replace_lead_semantic_group_v1", {
        "p_lead_id": lead_id,
        "p_target_persona_id": persona_id,
        "p_audience_id": audience_id,
        "p_created_by_user_id": created_by_user_id,
        "p_idempotency_key": idempotency_key,
        "p_reason": reason,
    }))
    return {"audience": audience, "result": (result.data if result else None)}


def insert_contact_consent(data: dict, audit_payload: Optional[dict] = None) -> dict:
    event = {
        "channel": data.get("channel"),
        "purpose": data.get("purpose"),
        "campaign_id": data.get("campaign_id"),
        "import_batch_id": data.get("import_batch_id"),
        "request_message_id": data.get("request_message_id"),
        "response_message_id": data.get("response_message_id"),
        "idempotency_key": data.get("idempotency_key"),
        **(audit_payload or {}),
    }
    result = _execute_with_retry(get_client().rpc("record_contact_consent_v1", {
        "p_consent": data,
        "p_event": event,
    }))
    payload = result.data if result else None
    return payload if isinstance(payload, dict) else ((payload or [{}])[0])


def get_latest_contact_consent(
    *, lead_id: int, persona_id: str, channel: str, purpose: str,
) -> Optional[dict]:
    rows = list_contact_consents(
        lead_id=lead_id, persona_id=persona_id, channel=channel, purpose=purpose,
    )
    return rows[0] if rows else None


def list_contact_consents(
    *, lead_id: int, persona_id: str, channel: Optional[str] = None, purpose: Optional[str] = None,
) -> list[dict]:
    query = (
        get_client().table("contact_consents").select("*")
        .eq("lead_id", lead_id).eq("persona_id", persona_id)
        .order("effective_at", desc=True).order("created_at", desc=True).limit(500)
    )
    if channel:
        query = query.eq("channel", channel)
    if purpose:
        query = query.eq("purpose", purpose)
    return _q(query)


# â”€â”€ System Events â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    Fire-and-forget event insert. Never raises â€” if the DB is unavailable
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

def list_system_events(
    entity_type: Optional[str] = None,
    event_types: Optional[list[str]] = None,
    persona_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    payload_equals: Optional[dict[str, str]] = None,
    since: Optional[str] = None,
    search: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 100,
) -> list:
    """Audit-trail query over system_events.

    Filters compose with AND. `event_types` is an OR list (uses .in_()).
    `search` does ILIKE over payload::text — slow without an index, OK for
    audit volumes (capped by limit). `since` expects ISO8601.
    """
    q = (
        get_client().table("system_events")
        .select("*")
        .order("created_at", desc=True)
        .limit(max(1, min(int(limit or 100), 500)))
    )
    if entity_type:
        q = q.eq("entity_type", entity_type)
    if event_types:
        q = q.in_("event_type", list(event_types))
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if entity_id:
        q = q.eq("entity_id", entity_id)
    for key, value in (payload_equals or {}).items():
        if key not in {"persona_slug", "brand_slug", "version", "operation_id"}:
            raise ValueError(f"Unsupported system_events payload filter: {key}")
        q = q.eq(f"payload->>{key}", str(value))
    if since:
        q = q.gte("created_at", since)
    if search:
        q = q.ilike("payload", f"%{search}%")
    if level:
        q = q.eq("level", level)
    return _q(q)

def update_pipeline_status(service: str, data: dict) -> None:
    get_client().table("pipeline_status").update(data).eq("service", service).execute()

# ── Inbound WhatsApp media ───────────────────────────────────────────────
# Files a lead sends over WhatsApp land in the PRIVATE `whatsapp-media`
# bucket, never in the public `assets-raw` used by marketing uploads.
WHATSAPP_MEDIA_BUCKET = "whatsapp-media"

import os
import time
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


def _execute_with_retry(query, retries: int = 2):
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return query.execute()
        except Exception as exc:
            last_exc = exc
            if not _is_transient_transport_error(exc) or attempt >= retries:
                raise
            _reset_client()
            time.sleep(0.25 * (attempt + 1))
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
    """Execute an insert and return the first row. Returns {} if result.data is None."""
    try:
        result = _execute_with_retry(query)
        if result is None or not result.data:
            return {}
        return result.data[0]
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"insert failed: {exc}", exc)
        except Exception:
            pass
        return {}


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
        try:
            result = _execute_with_retry(client.table("leads").update(update).eq("id", existing["id"]))
            return (result.data or [{**existing, **update}])[0]
        except Exception:
            return {**existing, **update}

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
    return _insert_one(client.table("leads").insert(payload))


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


def update_lead(lead_ref: int, data: dict) -> None:
    _execute_with_retry(get_client().table("leads").update(data).eq("id", lead_ref))


def get_lead_by_ref(lead_ref: int) -> Optional[dict]:
    """Fetch a lead row by its integer primary key (`leads.id`)."""
    return _one(get_client().table("leads").select("*").eq("id", lead_ref).maybe_single())


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


def get_recent_messages(hours: int = 24, limit: int = 500, persona_id: Optional[str] = None) -> list:
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
    if persona_id:
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


def get_conversations(hours: int = 168, limit: int = 1000, persona_id: Optional[str] = None) -> list:
    """
    Returns the last message per unique conversation.

    lead_ref is the canonical conversation key. Names are only a fallback for
    orphan messages because the same contact name can exist under different
    personas.
    """
    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    client = get_client()
    rows = _q(
        client.table("messages")
        .select("id,nome,lead_ref,Lead_Stage,texto,created_at,direction,sender_type,status")
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(limit)
    )
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
        if persona_id and lead.get("persona_id") != persona_id:
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


def upsert_knowledge_edge(
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    persona_id: Optional[str] = None,
    weight: float = 1.0,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Idempotent upsert keyed by (source_node_id, target_node_id, relation_type)."""
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
            .select("id")
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

    if existing:
        return existing
    try:
        r = client.table("knowledge_edges").insert({
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": metadata or {},
        }).execute()
        return (r.data or [{}])[0]
    except Exception as exc:
        if _kg_unavailable(exc):
            _KG_TABLES_MISSING = True
            return None
        raise


def delete_knowledge_edge(edge_id: str) -> bool:
    """Delete a knowledge edge by id. Returns True when the delete request succeeds."""
    global _KG_TABLES_MISSING
    if _KG_TABLES_MISSING or not edge_id:
        return False
    try:
        _execute_with_retry(get_client().table("knowledge_edges").delete().eq("id", edge_id))
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
    return nodes, eq_in_source


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
    {"node_type": "tag",            "label": "Tag",       "default_level": 90, "default_importance": 0.30, "color": "#94a3b8", "icon": "tag",         "sort_order": 90},
    {"node_type": "mention",        "label": "Menção",    "default_level": 92, "default_importance": 0.25, "color": "#94a3b8", "icon": "at-sign",     "sort_order": 92},
    {"node_type": "knowledge_item", "label": "Fila",      "default_level": 95, "default_importance": 0.40, "color": "#94a3b8", "icon": "inbox",       "sort_order": 95},
    {"node_type": "kb_entry",       "label": "KB Entry",  "default_level": 95, "default_importance": 0.50, "color": "#94a3b8", "icon": "database",    "sort_order": 96},
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


def upsert_kb_entry(data: dict) -> dict:
    result = _execute_with_retry(get_client().table("kb_entries").upsert(data, on_conflict="kb_id,persona_id"))
    return (result.data or [{}])[0]


def get_kb_entry(entry_id: str) -> Optional[dict]:
    return _one(
        get_client().table("kb_entries")
        .select("id,persona_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
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
            get_client().table("kb_entries")
            .select("id,persona_id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,tags,agent_visibility,updated_at")
            .in_("id", chunk)
        ))
    return {str(r["id"]): r for r in rows if r.get("id")}


def update_kb_entry(entry_id: str, data: dict) -> None:
    from datetime import datetime, timezone
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _execute_with_retry(get_client().table("kb_entries").update(data).eq("id", entry_id))


def search_kb(query_embedding: list, persona_id: Optional[str] = None, top_k: int = 5) -> list:
    params = {"query_embedding": query_embedding, "match_count": top_k}
    if persona_id:
        params["filter_persona_id"] = persona_id
    return _q(get_client().rpc("match_kb_entries", params))


# ── Agent Logs ─────────────────────────────────────────────────────────────

def insert_agent_log(data: dict) -> None:
    _execute_with_retry(get_client().table("agent_logs").insert(data))


def get_agent_logs(lead_id: Optional[str] = None, limit: int = 50) -> list:
    q = get_client().table("agent_logs").select("*").order("created_at", desc=True).limit(limit)
    if lead_id:
        q = q.eq("lead_id", lead_id)
    return _q(q)


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


def get_knowledge_item_by_path(file_path: str) -> Optional[dict]:
    return _one(
        get_client().table("knowledge_items")
        .select("id,content,status")
        .eq("file_path", file_path)
        .maybe_single()
    )


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
) -> None:
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
        get_client().table("system_events").insert(row).execute()
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"insert_event failed: {exc}", exc)
        except Exception:
            pass


def get_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    persona_id: Optional[str] = None,
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
    # Recent errors from agent_logs (works even if system_events is missing)
    error_rows = _q(
        client.table("agent_logs")
        .select("id")
        .like("action", "[ERROR]%")
        .gte("created_at", today)
    )

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

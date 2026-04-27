import os
from supabase import create_client, Client
from typing import Optional

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


# ── Safe query helpers ─────────────────────────────────────────────────────
# All public functions use _q() / _one() so that:
#   • A None result never causes AttributeError
#   • A missing table returns a safe default instead of a 500

def _q(query) -> list:
    """Execute a list query; return [] on None or any exception."""
    try:
        result = query.execute()
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
        result = query.execute()
        return result.data
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.error("supabase_client", f"query failed: {exc}", exc)
        except Exception:
            pass
        return None


# ── Leads ──────────────────────────────────────────────────────────────────

def get_lead(lead_id: str) -> Optional[dict]:
    return _one(get_client().table("leads").select("*").eq("lead_id", lead_id).maybe_single())


def get_leads(persona_slug: Optional[str] = None, limit: int = 100, offset: int = 0) -> list:
    q = get_client().table("leads").select("*").order("updated_at", desc=True).range(offset, offset + limit - 1)
    return _q(q)


def update_lead(lead_ref: int, data: dict) -> None:
    get_client().table("leads").update(data).eq("id", lead_ref).execute()


# ── Messages ───────────────────────────────────────────────────────────────

def get_messages(lead_id: str, limit: int = 30) -> list:
    q = (
        get_client().table("messages")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    return list(reversed(_q(q)))


def get_recent_messages(hours: int = 24, limit: int = 500) -> list:
    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    q = (
        get_client().table("messages")
        .select("*")
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(limit)
    )
    return _q(q)


def insert_message(data: dict) -> None:
    get_client().table("messages").insert(data).execute()


# ── Insights ───────────────────────────────────────────────────────────────

def get_insights(status: Optional[str] = None, limit: int = 50) -> list:
    q = get_client().table("flow_insights").select("*").order("created_at", desc=True).limit(limit)
    if status:
        q = q.eq("status", status)
    return _q(q)


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


# ── Knowledge Base ─────────────────────────────────────────────────────────

def get_kb_entries(persona_id: Optional[str] = None, status: str = "ATIVO") -> list:
    q = get_client().table("kb_entries").select("id,tipo,categoria,produto,intencao,titulo,conteudo,link,prioridade,status,source,updated_at")
    if persona_id:
        q = q.eq("persona_id", persona_id)
    if status:
        q = q.eq("status", status)
    return _q(q.order("prioridade"))


def upsert_kb_entry(data: dict) -> None:
    get_client().table("kb_entries").upsert(data, on_conflict="kb_id,persona_id").execute()


def search_kb(query_embedding: list, persona_id: Optional[str] = None, top_k: int = 5) -> list:
    params = {"query_embedding": query_embedding, "match_count": top_k}
    if persona_id:
        params["filter_persona_id"] = persona_id
    return _q(get_client().rpc("match_kb_entries", params))


# ── Agent Logs ─────────────────────────────────────────────────────────────

def insert_agent_log(data: dict) -> None:
    get_client().table("agent_logs").insert(data).execute()


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
    result = get_client().table("knowledge_sources").insert(data).execute()
    return result.data[0]


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
    result = get_client().table("knowledge_items").insert(data).execute()
    return result.data[0]


def update_knowledge_item(item_id: str, data: dict) -> None:
    data["updated_at"] = __import__("datetime").datetime.utcnow().isoformat()
    get_client().table("knowledge_items").update(data).eq("id", item_id).execute()


def get_knowledge_item_counts() -> dict:
    rows = _q(get_client().table("knowledge_items").select("status,content_type"))
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
    result = get_client().table("sync_runs").insert(data).execute()
    return result.data[0]


def update_sync_run(run_id: str, data: dict) -> None:
    get_client().table("sync_runs").update(data).eq("id", run_id).execute()


def get_sync_runs(limit: int = 20) -> list:
    return _q(
        get_client().table("sync_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit)
    )


def insert_sync_log(data: dict) -> None:
    get_client().table("sync_logs").insert(data).execute()


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

def insert_event(data: dict) -> None:
    get_client().table("system_events").insert(data).execute()


def get_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    persona_id: Optional[str] = None,
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


def get_pipeline_metrics() -> dict:
    from datetime import datetime, timedelta
    today = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    attention_rows = _q(
        get_client().table("knowledge_items")
        .select("status")
        .in_("status", ["pending", "needs_persona", "needs_category"])
    )
    approved_rows = _q(
        get_client().table("knowledge_items")
        .select("id")
        .eq("status", "approved")
        .gte("updated_at", today)
    )
    kb_rows = _q(
        get_client().table("kb_entries")
        .select("id")
        .eq("status", "ATIVO")
    )
    asset_rows = _q(
        get_client().table("knowledge_items")
        .select("id")
        .eq("content_type", "asset")
        .in_("status", ["pending", "needs_persona"])
    )
    # Recent errors from agent_logs (works even if system_events is missing)
    error_rows = _q(
        get_client().table("agent_logs")
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

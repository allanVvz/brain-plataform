from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/n8n")
def n8n_logs(limit: int = Query(100, le=500), status: str = Query(None)):
    return supabase_client.get_n8n_executions(limit=limit, status=status)


@router.get("/agents")
def agent_logs(lead_id: str = Query(None), limit: int = Query(50, le=200)):
    return supabase_client.get_agent_logs(lead_id=lead_id, limit=limit)


@router.get("/errors")
def error_logs(
    component: str = Query(None, description="Filter by worker/component name"),
    limit: int = Query(100, le=500),
):
    """
    Returns structured error and warning logs written by the SRE logger.
    These are agent_logs rows where action starts with [ERROR] or [WARN].
    Visible at GET /logs/agents as well — this endpoint adds component filtering.
    """
    from services.supabase_client import get_client, _q
    q = (
        get_client().table("agent_logs")
        .select("*")
        .or_("action.like.[ERROR]%,action.like.[WARN]%")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if component:
        q = q.eq("agent_type", component)
    rows = _q(q)

    # Promote metadata fields to top-level for easier consumption
    for row in rows:
        meta = row.get("metadata") or {}
        row["level"] = meta.get("level", "ERROR")
        row["component"] = meta.get("component", row.get("agent_type", ""))
        row["message"] = meta.get("message", row.get("action", ""))
        row["traceback"] = meta.get("traceback", "")
        row["ts"] = meta.get("ts", row.get("created_at", ""))
    return rows


@router.get("/health-history")
def health_history(limit: int = Query(30, le=100)):
    return supabase_client.get_health_history(limit=limit)

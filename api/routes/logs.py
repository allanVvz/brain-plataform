from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/n8n")
def n8n_logs(limit: int = Query(100, le=500), status: str = Query(None)):
    return supabase_client.get_n8n_executions(limit=limit, status=status)


@router.get("/agents")
def agent_logs(
    lead_id: str = Query(None),
    component: str = Query(None),
    limit: int = Query(50, le=200),
):
    rows = supabase_client.get_agent_logs(lead_id=lead_id, limit=limit)
    if component:
        rows = [
            row for row in rows
            if str(row.get("component") or row.get("agent_type") or "").lower() == component.lower()
        ]
    return rows


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
    return supabase_client.get_error_logs(component=component, limit=limit)


@router.get("/health-history")
def health_history(limit: int = Query(30, le=100)):
    return supabase_client.get_health_history(limit=limit)

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from services import auth_service, supabase_client

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


@router.get("/audit")
def audit_logs(
    request: Request,
    entity_type: Optional[str] = Query(None, description="asset | knowledge_node | knowledge_edge | knowledge_item | sync"),
    event_type: Optional[str] = Query(None, description="CSV of event_type values (OR)"),
    persona_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO8601 lower bound on created_at"),
    search: Optional[str] = Query(None, description="ILIKE over payload"),
    limit: int = Query(200, le=500),
):
    """
    Audit trail of mutations recorded in `system_events`. Admin-only.

    Backs the "Auditoria" tab in /logs. Returns the most recent matching events
    with their actor + before/after diff payload.
    """
    user = auth_service.current_user(request)
    if not auth_service.is_admin(user):
        raise HTTPException(status_code=403, detail="Auditoria restrita a administradores.")

    event_types = None
    if event_type:
        event_types = [v.strip() for v in event_type.split(",") if v.strip()]

    return supabase_client.list_system_events(
        entity_type=entity_type,
        event_types=event_types,
        persona_id=persona_id,
        entity_id=entity_id,
        since=since,
        search=search,
        limit=limit,
    )


@router.get("/health-history")
def health_history(limit: int = Query(30, le=100)):
    return supabase_client.get_health_history(limit=limit)

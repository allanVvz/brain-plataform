from fastapi import APIRouter, HTTPException, Query, Request
from services import auth_service, supabase_client

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/n8n")
def n8n_logs(request: Request, limit: int = Query(100, le=500), status: str = Query(None)):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode ver logs globais do n8n.")
    return supabase_client.get_n8n_executions(limit=limit, status=status)


@router.get("/agents")
def agent_logs(
    request: Request,
    lead_id: str = Query(None),
    component: str = Query(None),
    persona_id: str = Query(None),
    limit: int = Query(50, le=200),
):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
        rows = supabase_client.get_agent_logs(lead_id=lead_id, limit=limit, persona_id=persona_id)
    elif auth_service.is_admin(auth_service.current_user(request)):
        rows = supabase_client.get_agent_logs(lead_id=lead_id, limit=limit)
    else:
        rows = []
        for pid in auth_service.allowed_persona_ids(request):
            rows.extend(supabase_client.get_agent_logs(lead_id=lead_id, limit=limit, persona_id=pid))
        rows = sorted(rows, key=lambda row: str(row.get("created_at") or row.get("ts") or ""), reverse=True)[:limit]
    if component:
        rows = [
            row for row in rows
            if str(row.get("component") or row.get("agent_type") or "").lower() == component.lower()
        ]
    return rows


@router.get("/errors")
def error_logs(
    request: Request,
    component: str = Query(None, description="Filter by worker/component name"),
    persona_id: str = Query(None),
    limit: int = Query(100, le=500),
):
    """
    Returns structured error and warning logs written by the SRE logger.
    These are agent_logs rows where action starts with [ERROR] or [WARN].
    Visible at GET /logs/agents as well — this endpoint adds component filtering.
    """
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
        return supabase_client.get_error_logs(component=component, limit=limit, persona_id=persona_id)
    if auth_service.is_admin(auth_service.current_user(request)):
        return supabase_client.get_error_logs(component=component, limit=limit)
    rows = []
    for pid in auth_service.allowed_persona_ids(request):
        rows.extend(supabase_client.get_error_logs(component=component, limit=limit, persona_id=pid))
    return sorted(rows, key=lambda row: str(row.get("created_at") or row.get("ts") or ""), reverse=True)[:limit]


@router.get("/health-history")
def health_history(request: Request, limit: int = Query(30, le=100)):
    if not auth_service.is_admin(auth_service.current_user(request)):
        raise HTTPException(403, "Apenas admin pode ver historico global de saude.")
    return supabase_client.get_health_history(limit=limit)

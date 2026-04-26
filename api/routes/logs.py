from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/n8n")
def n8n_logs(limit: int = Query(100, le=500), status: str = Query(None)):
    return supabase_client.get_n8n_executions(limit=limit, status=status)


@router.get("/agents")
def agent_logs(lead_id: str = Query(None), limit: int = Query(50, le=200)):
    return supabase_client.get_agent_logs(lead_id=lead_id, limit=limit)


@router.get("/health-history")
def health_history(limit: int = Query(30, le=100)):
    return supabase_client.get_health_history(limit=limit)

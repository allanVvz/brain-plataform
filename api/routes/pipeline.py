from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/status")
def pipeline_status():
    return supabase_client.get_pipeline_statuses()


@router.get("/metrics")
def pipeline_metrics():
    return supabase_client.get_pipeline_metrics()


@router.get("/events")
def pipeline_events(
    limit: int = 50,
    event_type: str = Query(None),
    persona_id: str = Query(None),
):
    return supabase_client.get_events(limit=limit, event_type=event_type, persona_id=persona_id)

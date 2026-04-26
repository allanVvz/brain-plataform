from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
def list_leads(limit: int = Query(100, le=500), offset: int = 0):
    return supabase_client.get_leads(limit=limit, offset=offset)


@router.get("/{lead_id}")
def get_lead(lead_id: str):
    lead = supabase_client.get_lead(lead_id)
    if not lead:
        from fastapi import HTTPException
        raise HTTPException(404, "Lead not found")
    return lead

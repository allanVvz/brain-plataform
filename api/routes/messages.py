from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/{lead_id}")
def get_messages(lead_id: str, limit: int = Query(50, le=200)):
    return supabase_client.get_messages(lead_id, limit=limit)


@router.get("")
def recent_messages(hours: int = Query(24, le=168)):
    return supabase_client.get_recent_messages(hours=hours, limit=500)

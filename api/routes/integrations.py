from fastapi import APIRouter, Query
from services import supabase_client

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("")
def list_integrations(persona_id: str = Query(None)):
    return supabase_client.get_integration_statuses(persona_id=persona_id)

from fastapi import APIRouter, Query, Request
from services import auth_service, supabase_client

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("")
def list_integrations(request: Request, persona_id: str = Query(None)):
    if persona_id:
        auth_service.assert_persona_access(request, persona_id=persona_id)
    return supabase_client.get_integration_statuses(persona_id=persona_id)

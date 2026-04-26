from fastapi import APIRouter, Query
from services import supabase_client
from services.knowledge_service import sync_from_sheets
import asyncio

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("")
def list_kb(persona_id: str = Query(None), status: str = "ATIVO"):
    return supabase_client.get_kb_entries(persona_id=persona_id, status=status)


@router.post("/sync")
async def sync_kb(persona_id: str, spreadsheet_id: str = Query(None)):
    count = await asyncio.to_thread(sync_from_sheets, persona_id, spreadsheet_id)
    return {"synced": count}

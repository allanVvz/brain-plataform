from fastapi import APIRouter, HTTPException, Query
from services import agents_service, event_emitter, supabase_client

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
def list_leads(
    limit: int = Query(100, le=500),
    offset: int = 0,
    persona_id: str | None = Query(None),
    persona_slug: str | None = Query(None),
):
    try:
        return supabase_client.get_leads(persona_slug=persona_id or persona_slug, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(500, f"Erro ao buscar leads: {exc}")


@router.get("/{lead_id}")
def get_lead(lead_id: str):
    lead = supabase_client.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@router.post("/{lead_ref}/pause-ai")
def pause_ai(lead_ref: int):
    """Pausa a IA para esse lead. /process passa a devolver agent_used=PAUSED."""
    ok = agents_service.pause_lead(lead_ref)
    if not ok:
        raise HTTPException(500, "Falha ao pausar lead")
    event_emitter.emit(
        "lead.ai_paused",
        entity_type="lead",
        entity_id=str(lead_ref),
        payload={"ai_paused": True, "by": "manual"},
        source="leads.pause_ai",
    )
    return {"ok": True, "lead_ref": lead_ref, "ai_paused": True}


@router.post("/{lead_ref}/resume-ai")
def resume_ai(lead_ref: int):
    """Retoma a IA para esse lead."""
    ok = agents_service.resume_lead(lead_ref)
    if not ok:
        raise HTTPException(500, "Falha ao retomar lead")
    event_emitter.emit(
        "lead.ai_resumed",
        entity_type="lead",
        entity_id=str(lead_ref),
        payload={"ai_paused": False, "by": "manual"},
        source="leads.resume_ai",
    )
    return {"ok": True, "lead_ref": lead_ref, "ai_paused": False}

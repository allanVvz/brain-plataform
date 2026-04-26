from fastapi import APIRouter, HTTPException
from schemas.persona import PersonaCreate, PersonaUpdate
from services import supabase_client

router = APIRouter(prefix="/personas", tags=["personas"])


@router.get("")
def list_personas():
    return supabase_client.get_personas()


@router.get("/{slug}")
def get_persona(slug: str):
    persona = supabase_client.get_persona(slug)
    if not persona:
        raise HTTPException(404, "Persona not found")
    return persona


@router.post("")
def create_persona(body: PersonaCreate):
    supabase_client.upsert_persona(body.model_dump())
    return supabase_client.get_persona(body.slug)


@router.patch("/{slug}")
def update_persona(slug: str, body: PersonaUpdate):
    supabase_client.upsert_persona({"slug": slug, **body.model_dump(exclude_none=True)})
    return supabase_client.get_persona(slug)

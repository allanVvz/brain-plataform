from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from services import supabase_client

router = APIRouter(tags=["health"])


@router.get("/")
def root():
    return {"name": "Brain AI", "version": "1.0.0", "status": "ok", "docs": "/docs"}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/score")
def health_score():
    history = supabase_client.get_health_history(limit=1)
    latest = history[-1] if history else None
    return latest or {"score_total": 0, "message": "no snapshot yet"}

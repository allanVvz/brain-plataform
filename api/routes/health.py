import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services import supabase_client

router = APIRouter(tags=["health"])


@router.get("/")
def root():
    return {"name": "Brain AI", "version": "1.0.0", "status": "ok", "docs": "/docs"}


@router.get("/health")
def health():
    return health_live()


@router.get("/health/live")
def health_live():
    return {
        "status": "ok",
        "service": "api",
        "workers_embedded": (os.environ.get("RUN_EMBEDDED_WORKERS") or "").strip().lower() in {"1", "true", "yes", "on"},
    }


@router.get("/health/ready")
def health_ready():
    ok, detail = supabase_client.ping_supabase()
    payload = {
        "status": "ready" if ok else "degraded",
        "checks": {
            "supabase": {
                "ok": ok,
                "detail": detail,
            }
        },
    }
    if ok:
        return payload
    return JSONResponse(payload, status_code=503)


@router.get("/health/score")
def health_score():
    history = supabase_client.get_health_history(limit=1)
    latest = history[-1] if history else None
    return latest or {"score_total": 0, "message": "no snapshot yet"}

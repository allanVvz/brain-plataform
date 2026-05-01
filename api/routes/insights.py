import asyncio
import logging
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from schemas.insight import InsightCreate, InsightUpdate
from services import supabase_client

logger = logging.getLogger("insights")

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def list_insights(status: str = Query(None), limit: int = 50):
    try:
        return supabase_client.get_insights(status=status, limit=limit)
    except Exception as exc:
        logger.error("list_insights failed (status=%r): %s\n%s", status, exc, traceback.format_exc())
        return []          # degrade gracefully — dashboard shows empty state instead of crashing


@router.patch("/{insight_id}")
def update_insight(insight_id: str, body: InsightUpdate):
    try:
        data: dict = {"status": body.status}
        if body.status == "resolved":
            data["resolved_at"] = datetime.now(timezone.utc).isoformat()
        supabase_client.update_insight(insight_id, data)
        return {"ok": True}
    except Exception as exc:
        logger.error("update_insight failed (id=%r): %s", insight_id, exc)
        raise HTTPException(500, str(exc))


@router.post("/run-validator")
async def trigger_validator():
    try:
        from agents.flow_validator.orchestrator import run as run_validator
        result = await asyncio.to_thread(run_validator)
        return result
    except Exception as exc:
        logger.error("trigger_validator failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, str(exc))

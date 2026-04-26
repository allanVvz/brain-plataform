from fastapi import APIRouter, Query
from schemas.insight import InsightCreate, InsightUpdate
from services import supabase_client
from agents.flow_validator.orchestrator import run as run_validator
from datetime import datetime, timezone
import asyncio

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def list_insights(status: str = Query(None), limit: int = 50):
    return supabase_client.get_insights(status=status, limit=limit)


@router.patch("/{insight_id}")
def update_insight(insight_id: str, body: InsightUpdate):
    data: dict = {"status": body.status}
    if body.status == "resolved":
        data["resolved_at"] = datetime.now(timezone.utc).isoformat()
    supabase_client.update_insight(insight_id, data)
    return {"ok": True}


@router.post("/run-validator")
async def trigger_validator():
    result = await asyncio.to_thread(run_validator)
    return result

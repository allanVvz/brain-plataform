"""Public compatibility endpoint for conversation decisions."""

from fastapi import APIRouter, Header

from schemas.events import LeadEvent
from services import lead_processing

router = APIRouter(tags=["process"])


@router.post("/process")
async def process(
    event: LeadEvent,
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
):
    return await lead_processing.process_lead(
        event=event,
        x_webhook_token=x_webhook_token,
    )

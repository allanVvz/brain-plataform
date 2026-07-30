from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services import auth_service, supabase_client
from services.whatsapp_providers import get_provider

router = APIRouter(prefix="/webhooks/evolution", tags=["evolution-webhook"])
logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = int(os.environ.get("EVOLUTION_WEBHOOK_MAX_BYTES", str(2 * 1024 * 1024)))
IGNORED_SUFFIXES = ("@g.us", "@broadcast", "@newsletter")


def _callback_token(binding_id: str) -> str:
    secret = (
        os.environ.get("EVOLUTION_WEBHOOK_HMAC_SECRET")
        or os.environ.get("AI_BRAIN_AUTH_SECRET")
        or ""
    )
    if not secret:
        raise HTTPException(503, "Webhook secret not configured.")
    return auth_service._b64encode(
        hmac.new(secret.encode(), binding_id.encode(), hashlib.sha256).digest()
    )


def _safe_event_id(binding_id: str, event: dict) -> str:
    stable = json.dumps({
        "binding": binding_id,
        "event": event.get("event_type"),
        "message": event.get("external_message_id"),
        "contact": event.get("external_contact_id"),
    }, sort_keys=True)
    return hashlib.sha256(stable.encode()).hexdigest()


@router.post("/{binding_id}")
async def evolution_webhook(binding_id: str, request: Request):
    callback_token = request.headers.get("x-brain-webhook-token") or ""
    expected = _callback_token(binding_id)
    if not hmac.compare_digest(callback_token.encode(), expected.encode()):
        raise HTTPException(401, "Invalid webhook token.")
    length = request.headers.get("content-length")
    if length and int(length) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Payload too large.")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Payload too large.")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON.") from exc

    binding = supabase_client.get_workflow_binding_by_id(binding_id)
    if not binding or binding.get("provider") != "evolution_baileys" or not binding.get("active"):
        raise HTTPException(404, "Binding not found.")
    provider = get_provider("evolution_baileys")
    events = provider.normalize_webhook(payload)
    accepted = 0
    ignored = 0
    for event in events:
        instance = str(event.get("instance") or "")
        if instance and instance != binding.get("provider_instance_key"):
            raise HTTPException(403, "Instance mismatch.")
        event_type = event.get("event_type")
        if event_type in {"CONNECTION_UPDATE", "QRCODE_UPDATED"}:
            event_raw = event.get("raw") or {}
            raw_state = str(event_raw.get("state") or event_raw.get("status") or "")
            normalized = {
                "open": "connected", "connected": "connected",
                "close": "disconnected", "disconnected": "disconnected",
                "connecting": "connecting",
            }.get(raw_state.lower(), "qr_ready" if event_type == "QRCODE_UPDATED" else "connecting")
            supabase_client.update_workflow_binding(binding_id, {
                "connection_status": normalized,
                "last_connection_at": datetime.now(timezone.utc).isoformat() if normalized == "connected" else binding.get("last_connection_at"),
            })
            if event_type == "CONNECTION_UPDATE":
                status_code = event_raw.get("statusCode") or event_raw.get("status_code")
                reason = event_raw.get("reason") or event_raw.get("disconnectReason") or event_raw.get("disconnect_reason")
                logger.warning(
                    "Evolution connection update binding=%s state=%s status_code=%s reason=%s",
                    binding_id,
                    raw_state[:40],
                    str(status_code)[:40],
                    str(reason)[:160],
                )
            ignored += 1
            continue
        if event_type not in {"MESSAGES_UPSERT", "MESSAGES_UPDATE", "SEND_MESSAGE"}:
            ignored += 1
            continue
        if event_type in {"MESSAGES_UPDATE", "SEND_MESSAGE"}:
            if event.get("external_message_id"):
                supabase_client.update_whatsapp_delivery_by_binding(
                    binding_id,
                    str(event["external_message_id"]),
                    str(event.get("status") or "sent"),
                )
            ignored += 1
            continue
        contact = str(event.get("external_contact_id") or "")
        if not contact or contact.endswith(IGNORED_SUFFIXES) or event.get("from_me"):
            ignored += 1
            continue
        external_id = str(event.get("external_message_id") or "")
        if not external_id:
            external_id = _safe_event_id(binding_id, event)
        lead = supabase_client.ensure_channel_lead(
            persona_id=binding["persona_id"],
            channel_binding_id=binding_id,
            external_contact_id=contact,
            display_name=None,
            metadata={
                "identities": {
                    "remote_jid": event.get("remote_jid"),
                    "remote_jid_alt": event.get("remote_jid_alt"),
                },
                "portal": {
                    "reply_state": "ready" if event.get("remote_jid_alt") or "@s.whatsapp.net" in contact else "awaiting_identification"
                },
            },
        )
        correlation_id = f"evolution:{binding_id}:{external_id}"
        supabase_client.insert_message({
            "lead_ref": lead["id"],
            "message_id": external_id,
            "external_message_id": external_id,
            "sender_type": "lead",
            "role": "user",
            "canal": "whatsapp",
            "texto": event.get("text") or "",
            "direction": "inbound",
            "status": "buffered",
            "channel_binding_id": binding_id,
            "correlation_id": correlation_id,
            "metadata": {"provider": "evolution_baileys"},
        })
        supabase_client.enqueue_whatsapp_message({
            "persona_id": binding["persona_id"],
            "lead_ref": lead["id"],
            "channel_binding_id": binding_id,
            "whatsapp_phone_number_id": None,
            "external_message_id": external_id,
            "direction": "inbound",
            "payload": {"text": event.get("text") or "", "sender": contact},
            "status": "buffered",
            "batch_key": f"{binding['persona_id']}:{lead['id']}",
            "idempotency_key": correlation_id,
            "correlation_id": correlation_id,
        })
        accepted += 1
    return JSONResponse({"ok": True, "accepted": accepted, "ignored": ignored}, status_code=202)

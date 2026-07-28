"""Canonical Meta WhatsApp ingress and delivery callbacks.

n8n is intentionally only a transport: these routes persist the source event
before any downstream work and never execute a commercial prompt.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse

from services import event_emitter, supabase_client

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
internal_router = APIRouter(prefix="/internal/whatsapp", tags=["whatsapp"])
logger = logging.getLogger("whatsapp")


def _mask(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:3]}******{phone[-4:]}" if len(phone) > 7 else "***"


def _normalize_phone(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _verify_signature(raw: bytes, signature: str | None) -> None:
    secret = (os.getenv("META_WHATSAPP_APP_SECRET") or "").strip()
    if not secret:
        allow_unsigned = (
            os.getenv("META_WHATSAPP_ALLOW_UNSIGNED_LOCAL") or ""
        ).strip().lower() in {"1", "true", "yes"}
        environment = (os.getenv("ENVIRONMENT") or "").strip().lower()
        if allow_unsigned and environment in {"local", "test", "qa"}:
            return
        raise HTTPException(503, "Meta app secret is not configured")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "invalid Meta signature")


def _binding(phone_number_id: str) -> dict[str, Any] | None:
    return supabase_client.get_active_workflow_binding_by_phone_number_id(phone_number_id)


def _allowed(binding: dict[str, Any], sender: str | None) -> bool:
    metadata = binding.get("metadata") or {}
    mode = metadata.get("mode", "disabled")
    if mode == "active":
        return True
    if mode != "test_allowlist":
        return False
    allowed = {_normalize_phone(str(x)) for x in metadata.get("allowlist", [])}
    return _normalize_phone(sender) in allowed


def _text(message: dict[str, Any]) -> str:
    kind = message.get("type") or "text"
    if kind == "text":
        return ((message.get("text") or {}).get("body") or "").strip()
    if kind == "button":
        return ((message.get("button") or {}).get("text") or "").strip()
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        return ((interactive.get("button_reply") or interactive.get("list_reply") or {}).get("title") or "").strip()
    return ""


class OutboundResult(BaseModel):
    lead_ref: int | None = None
    buffer_id: str | None = None
    wamid: str | None = None
    success: bool
    execution_id: str | None = None
    error: str | None = None
    correlation_id: str | None = None


async def _process_inbound(payload: dict[str, Any]) -> dict:
    accepted = duplicate = ignored = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = metadata.get("phone_number_id")
            if not phone_number_id:
                continue
            binding = _binding(phone_number_id)
            if not binding:
                ignored += len(value.get("messages") or [])
                continue
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts") or []}
            for message in value.get("messages") or []:
                sender = message.get("from")
                external_id = message.get("id")
                if not external_id:
                    ignored += 1
                    continue
                if not _allowed(binding, sender):
                    ignored += 1
                    supabase_client.insert_event({"event_type": "whatsapp.inbound_ignored", "entity_type": "whatsapp", "entity_id": external_id or "unknown", "persona_id": binding["persona_id"], "payload": {"sender": _mask(sender), "phone_number_id": phone_number_id}}, source="whatsapp.inbound")
                    continue
                lead = supabase_client.ensure_lead_for_persona(lead_id=sender or "", persona_slug_or_id=binding["persona_id"], nome=contacts.get(sender), canal="whatsapp", mensagem=_text(message), whatsapp_phone_number_id=phone_number_id) or {}
                correlation_id = f"wa:{external_id or int(time.time() * 1000)}"
                inserted = supabase_client.enqueue_whatsapp_message({
                    "persona_id": binding["persona_id"], "lead_ref": lead.get("id"), "whatsapp_phone_number_id": phone_number_id,
                    "external_message_id": external_id, "direction": "inbound", "payload": {"type": message.get("type"), "text": _text(message), "sender": sender, "raw": message},
                    "status": "buffered", "batch_key": f"{binding['persona_id']}:{sender}", "available_at": supabase_client.debounce_available_at(3),
                    "idempotency_key": f"meta:{binding['persona_id']}:{phone_number_id}:{external_id}", "correlation_id": correlation_id,
                })
                if not inserted:
                    duplicate += 1
                    continue
                supabase_client.insert_message({"lead_ref": lead.get("id"), "message_id": external_id, "external_message_id": external_id, "sender_type": "lead", "role": "user", "canal": "whatsapp", "texto": _text(message), "direction": "inbound", "status": "buffered", "whatsapp_phone_number_id": phone_number_id, "correlation_id": correlation_id, "metadata": {"type": message.get("type")}})
                accepted += 1
                event_emitter.emit("whatsapp.inbound_buffered", entity_type="lead", entity_id=str(lead.get("id") or ""), persona_id=binding["persona_id"], payload={"correlation_id": correlation_id, "sender": _mask(sender)}, source="whatsapp.inbound")
    return {"accepted": accepted, "duplicate": duplicate, "ignored": ignored}


def _process_status(payload: dict[str, Any]) -> dict:
    updated = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for item in ((change.get("value") or {}).get("statuses") or []):
                wamid, state = item.get("id"), item.get("status")
                if wamid and state in {"sent", "delivered", "read", "failed"}:
                    supabase_client.update_whatsapp_delivery(wamid, state, item.get("errors") or [])
                    updated += 1
    return {"updated": updated}


async def _signed_payload(request: Request, signature: str | None) -> dict[str, Any]:
    raw = await request.body()
    try:
        _verify_signature(raw, signature)
    except HTTPException:
        logger.warning("whatsapp_callback_signature_rejected bytes=%d", len(raw))
        raise
    logger.info("whatsapp_callback_signature_verified bytes=%d", len(raw))
    try:
        return await request.json()
    except Exception as exc:
        raise HTTPException(400, "invalid JSON") from exc


@router.get("")
async def meta_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's public callback verification endpoint."""
    expected = (os.getenv("META_WHATSAPP_VERIFY_TOKEN") or "").strip()
    if hub_mode != "subscribe" or not expected or not hmac.compare_digest(hub_verify_token or "", expected):
        raise HTTPException(403, "invalid Meta verify token")
    return PlainTextResponse(hub_challenge or "")


@router.post("")
async def meta_callback(request: Request, x_hub_signature_256: str | None = Header(None)) -> dict:
    """Canonical Meta callback: one URL receives inbound messages and statuses."""
    payload = await _signed_payload(request, x_hub_signature_256)
    inbound = await _process_inbound(payload) if any(
        (change.get("value") or {}).get("messages")
        for entry in payload.get("entry", []) for change in entry.get("changes", [])
    ) else {"accepted": 0, "duplicate": 0, "ignored": 0}
    delivery = _process_status(payload)
    return {**inbound, **delivery}


@router.post("/inbound")
async def inbound(request: Request, x_hub_signature_256: str | None = Header(None)) -> dict:
    return await _process_inbound(await _signed_payload(request, x_hub_signature_256))


@router.post("/status")
async def status(request: Request, x_hub_signature_256: str | None = Header(None)) -> dict:
    return _process_status(await _signed_payload(request, x_hub_signature_256))


@internal_router.post("/outbound-result")
def outbound_result(body: OutboundResult, x_webhook_token: str | None = Header(None, alias="X-Webhook-Token")) -> dict:
    expected = (os.getenv("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "internal webhook token is not configured")
    if not hmac.compare_digest((x_webhook_token or "").encode(), expected.encode()):
        raise HTTPException(401, "invalid webhook token")
    state = "sent" if body.success else "retry"
    supabase_client.complete_whatsapp_outbound(body.buffer_id, body.wamid, state, body.error, body.execution_id)
    return {"ok": True, "status": state}

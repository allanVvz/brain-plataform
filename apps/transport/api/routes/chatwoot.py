"""Signed Chatwoot webhook receiver; only the API inbox can command transport."""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Request

from repositories import chatwoot_bridge
from services import chatwoot_api

router = APIRouter(prefix="/webhooks/chatwoot", tags=["chatwoot"])


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("")
async def receive_chatwoot_event(
    request: Request,
    x_chatwoot_timestamp: str | None = Header(None),
    x_chatwoot_signature: str | None = Header(None),
) -> dict:
    config = chatwoot_api.configuration()
    if not config:
        raise HTTPException(503, "Chatwoot bridge is disabled")

    raw = await request.body()
    if not chatwoot_api.verify_webhook_signature(
        raw, x_chatwoot_timestamp, x_chatwoot_signature, config.webhook_secret,
    ):
        raise HTTPException(401, "invalid Chatwoot webhook signature")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "invalid Chatwoot webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "invalid Chatwoot webhook payload")

    account_id = _integer((payload.get("account") or {}).get("id"))
    inbox_id = _integer((payload.get("inbox") or {}).get("id"))
    conversation = payload.get("conversation") or {}
    conversation_id = _integer(conversation.get("id") or conversation.get("display_id"))
    if account_id != config.account_id or inbox_id != config.inbox_id or not conversation_id:
        return {"ok": True, "ignored": True}

    mapping = chatwoot_bridge.get_conversation_by_chatwoot_id(
        account_id, inbox_id, conversation_id,
    )
    if not mapping or str(mapping.get("channel_binding_id")) != config.binding_id:
        return {"ok": True, "ignored": True}

    event = str(payload.get("event") or "")
    if event != "message_created":
        return {"ok": True, "ignored": True}
    if (payload.get("content_attributes") or {}).get("brain_bridge_v1") is True:
        return {"ok": True, "ignored": True}

    message_id = _integer(payload.get("id"))
    sender = payload.get("sender") or {}
    sender_id = _integer(sender.get("id"))
    if not message_id or sender.get("type") != "user" or sender_id != config.agent_id:
        return {"ok": True, "ignored": True}

    is_private = bool(payload.get("private"))
    content = str(payload.get("content") or "").strip()
    message_type = str(payload.get("message_type") or "").lower()
    outgoing = message_type in {"outgoing", "1"}
    if not outgoing:
        return {"ok": True, "ignored": True}
    if is_private:
        operation = chatwoot_api.command_operation(content)
        if operation is None:
            return {"ok": True, "ignored": True}
    else:
        operation = "human_reply"
    receipt = chatwoot_bridge.enqueue_command(
        source_id=f"message:{message_id}", operation=operation,
        binding_id=config.binding_id, lead_ref=int(mapping["lead_ref"]),
        chatwoot_message_id=message_id, conversation_id=conversation_id,
    )
    return {"ok": True, "queued": receipt.get("status") not in {"completed", "ignored"}}

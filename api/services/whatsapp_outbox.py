"""Canonical WhatsApp outbox creation, always bound to the lead channel."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from services import supabase_client


def resolve_lead_binding(lead: dict[str, Any]) -> dict[str, Any]:
    binding_id = lead.get("channel_binding_id")
    if not binding_id:
        raise HTTPException(409, "Selecione um canal WhatsApp explicito para este lead.")
    binding = supabase_client.get_workflow_binding_by_id(binding_id)
    if not binding or not binding.get("active"):
        raise HTTPException(409, "O canal selecionado nao esta disponivel para esta persona.")
    if binding.get("persona_id") != lead.get("persona_id"):
        raise HTTPException(403, "O canal selecionado pertence a outra persona.")
    metadata = binding.get("metadata") or {}
    if metadata.get("safety_paused") or binding.get("connection_status") == "safety_paused":
        raise HTTPException(409, "O canal esta pausado por seguranca.")
    if metadata.get("transport_mode") not in {"provider_direct", "n8n_adapter"}:
        raise HTTPException(409, "O canal nao possui transporte canonico configurado.")
    return binding


def enqueue_outbound(*, lead: dict[str, Any], text: str, sender_type: str,
                     message_id: str, correlation_id: str,
                     idempotency_key: str | None = None,
                     metadata: dict[str, Any] | None = None,
                     media: dict[str, Any] | None = None) -> dict[str, Any]:
    binding = resolve_lead_binding(lead)
    lock_key = idempotency_key or correlation_id
    existing = supabase_client.get_whatsapp_buffer_by_idempotency(lock_key)
    if existing:
        if (
            existing.get("lead_ref") != lead["id"]
            or existing.get("channel_binding_id") != binding["id"]
        ):
            raise HTTPException(
                409,
                "A chave idempotente ja pertence a outra mensagem.",
            )
        return {
            "buffer_id": existing["id"],
            "message_id": message_id,
            "status": existing.get("status") or "pending_send",
            "deduplicated": True,
            "binding": binding,
        }
    envelope = supabase_client.enqueue_whatsapp_envelope(
        buffer={
            "persona_id": lead["persona_id"],
            "lead_ref": lead["id"],
            "channel_binding_id": binding["id"],
            "whatsapp_phone_number_id": binding.get("whatsapp_phone_number_id"),
            "direction": "outbound",
            "payload": {
                "text": text,
                "sender_type": sender_type,
                "media": media,
            },
            "status": "pending_send",
            "batch_key": f"{lead['persona_id']}:{lead['id']}",
            "idempotency_key": lock_key,
            "correlation_id": correlation_id,
        },
        message={
            "lead_id": lead["id"],
            "role": "human" if sender_type == "human" else "assistant",
            "content": text,
            "direction": "outbound",
            "status": "pending",
            "channel": "whatsapp",
            "sender_id": message_id,
            "whatsapp_phone_number_id": binding.get("whatsapp_phone_number_id"),
            "channel_binding_id": binding["id"],
            "correlation_id": correlation_id,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if envelope.get("deduplicated"):
        existing = supabase_client.get_whatsapp_buffer_by_idempotency(lock_key)
        if (
            not existing
            or existing.get("lead_ref") != lead["id"]
            or existing.get("channel_binding_id") != binding["id"]
        ):
            raise HTTPException(
                409,
                "A chave idempotente ja pertence a outra mensagem.",
            )
    return {**envelope, "binding": binding}

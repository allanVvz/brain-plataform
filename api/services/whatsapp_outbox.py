"""Canonical WhatsApp outbox creation, always bound to the lead channel."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from services import supabase_client


def _recipient_for_lead(lead: dict[str, Any]) -> str:
    """Return the canonical WhatsApp recipient or fail before queueing.

    A manual send must never create an ambiguous outbox item which a worker
    could later route to a stale JID or another channel.
    """
    import re

    identities = (lead.get("metadata") or {}).get("identities") or {}
    recipient = str(
        identities.get("remote_jid_alt")
        or lead.get("external_contact_id")
        or ""
    )
    if recipient.endswith("@s.whatsapp.net"):
        recipient = recipient.split("@", 1)[0]
    if not recipient or "@lid" in recipient:
        raise HTTPException(409, "Destinatario WhatsApp ausente ou invalido.")
    recipient = re.sub(r"\D", "", recipient)
    # E.164 is at most 15 digits.  The lower bound intentionally accepts
    # national test numbers while still rejecting ids and empty placeholders.
    if not 8 <= len(recipient) <= 15:
        raise HTTPException(409, "Destinatario WhatsApp ausente ou invalido.")
    return recipient


def validate_direct_binding(binding: dict[str, Any]) -> None:
    """Validate the provider-direct contract shared by every persona."""
    metadata = binding.get("metadata") or {}
    if metadata.get("decision_owner") != "deterministic":
        raise HTTPException(409, "A mensageria deve usar decisao deterministica.")
    if metadata.get("transport_mode") != "provider_direct":
        raise HTTPException(409, "A mensageria deve usar transporte direto pelo provider.")
    if (
        binding.get("n8n_workflow_id")
        or metadata.get("outbound_webhook_url")
        or metadata.get("n8n_outbound_webhook_url")
        or metadata.get("conversation_webhook_url")
    ):
        raise HTTPException(409, "Webhooks n8n nao sao permitidos no transporte direto.")

    provider = binding.get("provider")
    status = str(binding.get("connection_status") or "").lower()
    if provider == "meta_cloud":
        if not binding.get("whatsapp_phone_number_id"):
            raise HTTPException(409, "Mensageria Meta sem whatsapp_phone_number_id.")
        if not binding.get("provider_secret_ciphertext"):
            raise HTTPException(409, "Mensageria Meta sem credencial.")
        if status not in {"connected", "open"}:
            raise HTTPException(409, "Mensageria Meta nao esta conectada.")
        return
    if provider == "evolution_baileys":
        if not binding.get("provider_instance_key"):
            raise HTTPException(409, "Mensageria Evolution sem instancia.")
        if not binding.get("provider_secret_ciphertext"):
            raise HTTPException(409, "Mensageria Evolution sem credencial.")
        if status not in {"connected", "open"}:
            raise HTTPException(409, "Mensageria Evolution ainda aguarda conexao ou QR Code.")
        return
    raise HTTPException(409, "Provider de mensageria nao suportado.")


def resolve_lead_binding(lead: dict[str, Any]) -> dict[str, Any]:
    binding_id = lead.get("channel_binding_id")
    binding = (
        supabase_client.get_workflow_binding_by_id(binding_id)
        if binding_id
        else None
    )
    if binding and binding.get("persona_id") != lead.get("persona_id"):
        raise HTTPException(403, "O canal selecionado pertence a outra persona.")
    if not binding or not binding.get("active"):
        binding = supabase_client.get_active_whatsapp_binding(lead.get("persona_id"))
        if not binding:
            raise HTTPException(409, "Mensageria da persona nao configurada.")
        if lead.get("id"):
            supabase_client.update_lead(
                int(lead["id"]),
                {"channel_binding_id": binding["id"]},
            )
        lead["channel_binding_id"] = binding["id"]
    metadata = binding.get("metadata") or {}
    if metadata.get("safety_paused") or binding.get("connection_status") == "safety_paused":
        raise HTTPException(409, "O canal esta pausado por seguranca.")
    validate_direct_binding(binding)
    return binding


def enqueue_outbound(*, lead: dict[str, Any], text: str, sender_type: str,
                     message_id: str, correlation_id: str,
                     idempotency_key: str | None = None,
                     metadata: dict[str, Any] | None = None,
                     media: dict[str, Any] | None = None) -> dict[str, Any]:
    binding = resolve_lead_binding(lead)
    _recipient_for_lead(lead)
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

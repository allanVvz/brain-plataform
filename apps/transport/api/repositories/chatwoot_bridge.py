"""Durable queue and contact/conversation mappings for the Chatwoot bridge."""

from __future__ import annotations

from typing import Any

from repositories import transport


def enqueue_projections(binding_id: str, *, limit: int = 500) -> int:
    result = transport._execute_with_retry(
        transport.get_client().rpc(
            "enqueue_chatwoot_projection_v1",
            {"p_channel_binding_id": binding_id, "p_limit": limit},
        )
    )
    return int(getattr(result, "data", 0) or 0)


def claim_operations(worker_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    result = transport._execute_with_retry(
        transport.get_client().rpc(
            "claim_chatwoot_bridge_operations_v1",
            {"p_worker_id": worker_id, "p_limit": limit, "p_lease_seconds": 120},
        )
    )
    return list(getattr(result, "data", None) or [])


def finish_operation(
    operation_id: str,
    worker_id: str,
    status: str,
    *,
    error: str | None = None,
    retry_seconds: int = 30,
    chatwoot_message_id: int | None = None,
    chatwoot_conversation_id: int | None = None,
    transport_buffer_id: str | None = None,
) -> bool:
    result = transport._execute_with_retry(
        transport.get_client().rpc(
            "finish_chatwoot_bridge_operation_v1",
            {
                "p_operation_id": operation_id,
                "p_worker_id": worker_id,
                "p_status": status,
                "p_error": error,
                "p_retry_seconds": retry_seconds,
                "p_chatwoot_message_id": chatwoot_message_id,
                "p_chatwoot_conversation_id": chatwoot_conversation_id,
                "p_transport_buffer_id": transport_buffer_id,
            },
        )
    )
    return bool(getattr(result, "data", False))


def enqueue_command(
    *, source_id: str, operation: str, binding_id: str, lead_ref: int,
    chatwoot_message_id: int | None, conversation_id: int,
) -> dict[str, Any]:
    result = transport._execute_with_retry(
        transport.get_client().rpc(
            "enqueue_chatwoot_command_v1",
            {
                "p_source_id": source_id,
                "p_operation": operation,
                "p_channel_binding_id": binding_id,
                "p_lead_ref": lead_ref,
                "p_chatwoot_message_id": chatwoot_message_id,
                "p_chatwoot_conversation_id": conversation_id,
            },
        )
    )
    payload = getattr(result, "data", None)
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        raise RuntimeError("Chatwoot command receipt returned an invalid result")
    return payload


def get_message(message_id: int) -> dict[str, Any] | None:
    result = transport._execute_with_retry(
        transport.get_client().table("messages").select(
            "id,lead_id,role,content,direction,status,channel,sender_id,external_message_id,created_at,metadata,message_origin"
        ).eq("id", message_id).maybe_single()
    )
    return getattr(result, "data", None)


def get_conversation(binding_id: str, lead_ref: int) -> dict[str, Any] | None:
    return transport._one(
        transport.get_client().table("chatwoot_bridge_conversations").select("*")
        .eq("channel_binding_id", binding_id).eq("lead_ref", lead_ref).maybe_single()
    )


def save_conversation(row: dict[str, Any]) -> dict[str, Any]:
    result = transport._execute_with_retry(
        transport.get_client().table("chatwoot_bridge_conversations")
        .upsert(row, on_conflict="channel_binding_id,lead_ref")
    )
    rows = getattr(result, "data", None) or []
    return rows[0] if rows else row


def update_last_projected_message_id(binding_id: str, lead_ref: int, message_id: int) -> bool:
    result = transport._execute_with_retry(
        transport.get_client().table("chatwoot_bridge_conversations")
        .update({"last_projected_message_id": int(message_id)})
        .eq("channel_binding_id", binding_id).eq("lead_ref", lead_ref)
        .lt("last_projected_message_id", int(message_id)).select("id")
    )
    return bool(getattr(result, "data", None))


def get_conversation_by_chatwoot_id(
    account_id: int, inbox_id: int, conversation_id: int,
) -> dict[str, Any] | None:
    return transport._one(
        transport.get_client().table("chatwoot_bridge_conversations").select("*")
        .eq("account_id", account_id).eq("inbox_id", inbox_id)
        .eq("conversation_id", conversation_id).maybe_single()
    )


def pending_delivery_updates(*, limit: int = 50) -> list[dict[str, Any]]:
    return transport._q(
        transport.get_client().table("chatwoot_bridge_operations").select(
            "id,channel_binding_id,lead_ref,chatwoot_message_id,chatwoot_conversation_id,transport_buffer_id"
        ).eq("source_kind", "chatwoot_event").eq("operation", "human_reply")
        .eq("status", "completed").not_.is_("transport_buffer_id", "null")
        .is_("chatwoot_delivery_status", "null").order("created_at").limit(limit)
    )


def get_delivery_buffer(buffer_id: str) -> dict[str, Any] | None:
    return transport.get_whatsapp_buffer(buffer_id)


def mark_delivery_status(operation_id: str, status: str) -> bool:
    query = (
        transport.get_client().table("chatwoot_bridge_operations")
        .update({"chatwoot_delivery_status": status})
        .eq("id", operation_id).is_("chatwoot_delivery_status", "null")
        .select("id")
    )
    result = transport._execute_with_retry(query)
    return bool(getattr(result, "data", None))

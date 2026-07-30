"""Durable WhatsApp inbox/outbox dispatcher.

Meta and the dashboard only write durable rows.  This worker leases rows from
Postgres, calls Brain for inbound decisions and n8n only for transport.  It is
safe to run more than one instance because leasing uses SKIP LOCKED.
"""
from __future__ import annotations

import json
import os
import re
import socket
from typing import Any

from services import (
    conversation_runtime,
    event_emitter,
    n8n_client,
    supabase_client,
    sre_logger,
)
from services.whatsapp_providers import get_provider
from workers.base_worker import BaseWorker


def _retry_delay(attempt: int) -> int:
    """Bounded exponential backoff in seconds (5, 10, ... up to 5 minutes)."""
    return min(300, 5 * (2 ** max(0, attempt - 1)))


class WhatsAppDispatchWorker(BaseWorker):
    name = "WhatsAppDispatchWorker"
    interval = int(os.environ.get("WHATSAPP_DISPATCH_INTERVAL", "2"))

    def __init__(self) -> None:
        super().__init__()
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"

    def _run_cycle(self) -> None:
        rows = supabase_client.claim_whatsapp_buffer(self.worker_id)
        for row in rows:
            try:
                if row.get("direction") == "inbound":
                    self._dispatch_inbound(row)
                else:
                    self._dispatch_outbound(row)
            except Exception as exc:  # one poison message must not block the queue
                self._retry_or_dead_letter(row, exc)

    def _begin_attempt(self, row: dict[str, Any], kind: str) -> bool:
        if supabase_client.mark_whatsapp_attempt(
            row["id"],
            self.worker_id,
            kind,
        ):
            row["_attempt_started"] = kind
            return True
        reason = f"compromised {kind} re-execution"
        if row.get("channel_binding_id"):
            supabase_client.record_whatsapp_safety_violation(
                binding_id=row["channel_binding_id"],
                lead_ref=row.get("lead_ref"),
                violation_key=f"reexecution:{kind}:{row['id']}",
                reason=reason,
            )
        supabase_client.complete_whatsapp_buffer(
            row["id"],
            "waiting_human",
            error=reason,
        )
        return False

    def _dispatch_inbound(self, row: dict[str, Any]) -> None:
        payload = row.get("payload") or {}
        persona = supabase_client.get_persona_by_id(row["persona_id"])
        if not persona:
            raise RuntimeError("persona for inbound buffer no longer exists")
        lead = supabase_client.get_lead_by_ref(row.get("lead_ref")) if row.get("lead_ref") else {}
        inbound_text = str(payload.get("text") or "").strip()
        if inbound_text and row.get("lead_ref"):
            recent_messages = supabase_client.get_messages(str(row["lead_ref"]), limit=20) or []
            recent_outbound_echo = next(
                (
                    message
                    for message in reversed(recent_messages)
                    if message.get("direction") == "outbound"
                    and str(message.get("content") or message.get("texto") or "").strip() == inbound_text
                ),
                None,
            )
            if recent_outbound_echo:
                supabase_client.handoff_whatsapp_lead(int(row["lead_ref"]))
                supabase_client.complete_whatsapp_buffer(row["id"], "waiting_human", error="recent outbound echo")
                event_emitter.emit(
                    "whatsapp.bot_loop_suppressed",
                    entity_type="lead",
                    entity_id=str(row["lead_ref"]),
                    persona_id=row["persona_id"],
                    payload={
                        "correlation_id": row.get("correlation_id"),
                        "matched_outbound_id": recent_outbound_echo.get("id"),
                    },
                    source="workers.whatsapp",
                )
                return
        automation_mode = (
            (((persona.get("config") or {}).get("portal") or {}).get("automation_mode"))
            or "ai_with_handoff"
        )
        if (lead or {}).get("ai_paused") or automation_mode == "human_only":
            supabase_client.complete_whatsapp_buffer(row["id"], "waiting_human")
            event_emitter.emit(
                "whatsapp.inbound_waiting_human",
                entity_type="lead",
                entity_id=str(row.get("lead_ref") or ""),
                persona_id=row["persona_id"],
                payload={
                    "correlation_id": row.get("correlation_id"),
                    "ai_paused": bool((lead or {}).get("ai_paused")),
                    "automation_mode": automation_mode,
                },
                source="workers.whatsapp",
            )
            return
        binding = supabase_client.get_workflow_binding_by_id(row.get("channel_binding_id"))
        binding_metadata = (binding or {}).get("metadata") or {}
        if (
            not binding
            or not binding.get("active")
            or binding.get("persona_id") != row.get("persona_id")
        ):
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="inbound binding is missing, inactive or cross-persona",
            )
            return
        if (
            binding_metadata.get("safety_paused")
            or binding.get("connection_status") == "safety_paused"
        ):
            if row.get("lead_ref"):
                supabase_client.handoff_whatsapp_lead(int(row["lead_ref"]))
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="binding safety paused",
            )
            return
        decision_owner = binding_metadata.get("decision_owner")
        if decision_owner not in {"deterministic", "n8n_agents"}:
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="unsupported binding decision owner",
            )
            return
        if not self._begin_attempt(row, "decision"):
            return
        if decision_owner == "deterministic":
            result = conversation_runtime.execute_pipeline(
                persona_slug=persona["slug"],
                lead_ref=int(row["lead_ref"]),
                message=str(payload.get("text") or ""),
                message_id=row.get("external_message_id"),
                correlation_id=str(row.get("correlation_id") or row["id"]),
                phone_number_id=row.get("whatsapp_phone_number_id"),
                channel_binding_id=row.get("channel_binding_id"),
                inbound_buffer_id=row["id"],
            )
            if not result.get("handoff"):
                supabase_client.complete_whatsapp_buffer(row["id"], "sent")
            event_emitter.emit(
                "whatsapp.inbound_dispatched",
                entity_type="lead",
                entity_id=str(row.get("lead_ref") or ""),
                persona_id=row["persona_id"],
                payload={
                    "correlation_id": row.get("correlation_id"),
                    "conversation_mode": "deterministic",
                    "pipeline_contract": "conversation_v1",
                    "classifier": result.get("classifier"),
                    "route": result.get("route"),
                    "handoff": bool(result.get("handoff")),
                },
                source="workers.whatsapp",
            )
            return
        if decision_owner == "n8n_agents":
            webhook_url = str(
                binding_metadata.get("conversation_webhook_url") or ""
            ).strip()
            if not webhook_url:
                raise RuntimeError("n8n_agents conversation webhook is not configured")
            token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
            status, body = n8n_client.send_to_webhook(
                webhook_url,
                {
                    "buffer_id": row["id"],
                    "lead_ref": row.get("lead_ref"),
                    "persona_id": row["persona_id"],
                    "persona_slug": persona["slug"],
                    "phone_number_id": row["whatsapp_phone_number_id"],
                    "channel_binding_id": row.get("channel_binding_id"),
                    "external_message_id": row.get("external_message_id"),
                    "correlation_id": row.get("correlation_id"),
                    "message": payload.get("text") or "",
                    "pipeline_contract": "conversation_v1",
                    "decision_owner": "n8n_agents",
                },
                secret=token or None,
                timeout=45.0,
            )
            if not 200 <= status < 300:
                raise RuntimeError(f"n8n conversation returned HTTP {status}")
            try:
                n8n_result = json.loads(body)
            except Exception:
                n8n_result = {}
            if not n8n_result.get("handoff"):
                supabase_client.complete_whatsapp_buffer(row["id"], "sent")
            event_emitter.emit(
                "whatsapp.inbound_dispatched",
                entity_type="lead",
                entity_id=str(row.get("lead_ref") or ""),
                persona_id=row["persona_id"],
                payload={
                    "correlation_id": row.get("correlation_id"),
                    "conversation_mode": "n8n_agents",
                    "pipeline_contract": "conversation_v1",
                    "handoff": bool(n8n_result.get("handoff")),
                },
                source="workers.whatsapp",
            )
            return

    def _dispatch_outbound(self, row: dict[str, Any]) -> None:
        binding = supabase_client.get_workflow_binding_by_id(row.get("channel_binding_id"))
        if (
            not binding
            or not binding.get("active")
            or binding.get("persona_id") != row.get("persona_id")
        ):
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="active binding does not match outbound persona",
            )
            return
        metadata = binding.get("metadata") or {}
        if (
            metadata.get("safety_paused")
            or binding.get("connection_status") == "safety_paused"
        ):
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="binding safety paused",
            )
            return
        transport_mode = metadata.get("transport_mode")
        if transport_mode not in {"provider_direct", "n8n_adapter"}:
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="unsupported binding transport mode",
            )
            return

        correlation_id = str(row.get("correlation_id") or "")
        if not correlation_id:
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="outbound correlation id is missing",
            )
            return
        lead = (
            supabase_client.get_lead_by_ref(row.get("lead_ref"))
            if row.get("lead_ref")
            else {}
        )
        identities = ((lead or {}).get("metadata") or {}).get("identities") or {}
        recipient = str(
            identities.get("remote_jid_alt")
            or (lead or {}).get("external_contact_id")
            or ""
        )
        if recipient.endswith("@s.whatsapp.net"):
            recipient = recipient.split("@", 1)[0]
        if not recipient or "@lid" in recipient:
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="recipient identification unavailable",
            )
            return
        recipient = re.sub(r"\D", "", recipient)
        if not recipient:
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="recipient identification unavailable",
            )
            return

        if transport_mode == "provider_direct":
            outbound_payload = row.get("payload") or {}
            provider = get_provider(binding.get("provider"))
            if outbound_payload.get("media") and binding.get("provider") == "evolution_baileys":
                media = outbound_payload["media"]
                signed_url = supabase_client._storage_signed_url(
                    media.get("bucket"), media.get("path"), 3600
                )
                if not signed_url:
                    raise RuntimeError("could not create signed media URL")
                if not self._begin_attempt(row, "provider"):
                    return
                result = provider.send_media(binding, recipient, {
                    "mediatype": (
                        "image" if str(media.get("mime") or "").startswith("image/")
                        else "audio" if str(media.get("mime") or "").startswith("audio/")
                        else "document"
                    ),
                    "mimetype": media.get("mime"),
                    "media": signed_url,
                    "fileName": media.get("filename"),
                    "caption": str(outbound_payload.get("text") or ""),
                })
            else:
                if outbound_payload.get("media"):
                    supabase_client.complete_whatsapp_buffer(
                        row["id"],
                        "waiting_human",
                        error="binding provider does not support canonical media send",
                    )
                    return
                if not self._begin_attempt(row, "provider"):
                    return
                result = provider.send_text(
                    binding,
                    recipient,
                    str(outbound_payload.get("text") or ""),
                )
            external_id = (
                (result.get("key") or {}).get("id")
                or ((result.get("messages") or [{}])[0] or {}).get("id")
                or result.get("messageId")
                or result.get("id")
            )
            if not external_id:
                raise RuntimeError("provider returned no external message id")
            supabase_client.complete_whatsapp_outbound(
                row["id"],
                binding_id=binding["id"],
                correlation_id=correlation_id,
                wamid=str(external_id),
                success=True,
            )
            return

        webhook_url = str(metadata.get("n8n_outbound_webhook_url") or "").strip()
        if not webhook_url:
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error="outbound n8n webhook is not configured",
            )
            return
        if not self._begin_attempt(row, "provider"):
            return
        status, _ = n8n_client.send_to_webhook(webhook_url, {
            "buffer_id": row["id"], "lead_ref": row.get("lead_ref"), "persona_id": row["persona_id"],
            "phone_number_id": binding.get("whatsapp_phone_number_id"), "channel_binding_id": binding["id"], "to": recipient,
            "text": (row.get("payload") or {}).get("text", ""),
            "correlation_id": correlation_id,
        }, secret=(os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or None))
        if not 200 <= status < 300:
            raise RuntimeError(f"n8n outbound returned HTTP {status}")
        # The controlled adapter commits the external id through
        # /internal/whatsapp/outbound-result before responding.  If it did not,
        # this processing row expires to waiting_human and is never resent.

    def _retry_or_dead_letter(self, row: dict[str, Any], exc: Exception) -> None:
        attempts, maximum = int(row.get("attempt_count") or 1), int(row.get("max_attempts") or 5)
        error = f"{type(exc).__name__}: {str(exc)[:800]}"
        attempt_kind = row.get("_attempt_started")
        if attempt_kind:
            if row.get("channel_binding_id"):
                supabase_client.record_whatsapp_safety_violation(
                    binding_id=row["channel_binding_id"],
                    lead_ref=row.get("lead_ref"),
                    violation_key=f"attempt-failed:{attempt_kind}:{row['id']}",
                    reason=error,
                )
            supabase_client.complete_whatsapp_buffer(row["id"], "waiting_human", error=error)
            return
        if row.get("direction") == "outbound":
            supabase_client.complete_whatsapp_buffer(
                row["id"],
                "waiting_human",
                error=error,
            )
            return
        if attempts >= maximum:
            supabase_client.complete_whatsapp_buffer(row["id"], "dead_letter", error=error)
            sre_logger.error(self.name, f"dead-letter buffer={row['id']}: {error}")
            return
        supabase_client.release_whatsapp_buffer(row["id"], "retry", delay_seconds=_retry_delay(attempts), error=error)

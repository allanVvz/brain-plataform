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
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from services import (
    conversation_runtime,
    event_emitter,
    n8n_client,
    supabase_client,
    sre_logger,
)
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

    def _dispatch_inbound(self, row: dict[str, Any]) -> None:
        payload = row.get("payload") or {}
        persona = supabase_client.get_persona_by_id(row["persona_id"])
        if not persona:
            raise RuntimeError("persona for inbound buffer no longer exists")
        lead = supabase_client.get_lead_by_ref(row.get("lead_ref")) if row.get("lead_ref") else {}
        if (lead or {}).get("ai_paused"):
            supabase_client.complete_whatsapp_buffer(row["id"], "waiting_human")
            event_emitter.emit(
                "whatsapp.inbound_waiting_human",
                entity_type="lead",
                entity_id=str(row.get("lead_ref") or ""),
                persona_id=row["persona_id"],
                payload={
                    "correlation_id": row.get("correlation_id"),
                    "ai_paused": True,
                },
                source="workers.whatsapp",
            )
            return
        binding = supabase_client.get_active_workflow_binding_by_phone_number_id(
            row["whatsapp_phone_number_id"]
        )
        binding_metadata = (binding or {}).get("metadata") or {}
        canonical_binding = (
            binding
            and binding.get("persona_id") == row.get("persona_id")
            and binding_metadata.get("decision_owner")
            in {"n8n_hybrid", "n8n_agents", "deterministic"}
        )
        process_mode = str(persona.get("process_mode") or "internal")
        if canonical_binding and process_mode == "internal":
            result = conversation_runtime.execute_pipeline(
                persona_slug=persona["slug"],
                lead_ref=int(row["lead_ref"]),
                message=str(payload.get("text") or ""),
                message_id=row.get("external_message_id"),
                correlation_id=str(row.get("correlation_id") or row["id"]),
                phone_number_id=row.get("whatsapp_phone_number_id"),
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
        if canonical_binding and process_mode == "n8n":
            webhook_url = str(
                binding_metadata.get("conversation_webhook_url")
                or binding_metadata.get("webhook_url")
                or ""
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
        event = {
            "lead_id": str((lead or {}).get("lead_id") or payload.get("sender") or row.get("lead_ref") or ""),
            "lead_ref": row.get("lead_ref"),
            "nome": (lead or {}).get("nome"),
            "stage": (lead or {}).get("stage") or "novo",
            "canal": "whatsapp",
            "mensagem": payload.get("text") or "",
            "whatsapp_phone_number_id": row["whatsapp_phone_number_id"],
            "persona_slug": persona["slug"],
        }
        token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
        base = (os.environ.get("API_INTERNAL_BASE_URL") or "http://api:8080").rstrip("/")
        response = httpx.post(
            f"{base}/process", json=event,
            headers={"X-Webhook-Token": token}, timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        reply = (result.get("reply") or "").strip()
        if reply:
            outbound = supabase_client.enqueue_whatsapp_message({
                "persona_id": row["persona_id"], "lead_ref": row.get("lead_ref"),
                "whatsapp_phone_number_id": row["whatsapp_phone_number_id"],
                "direction": "outbound", "payload": {"text": reply, "sender_type": "ai"},
                "status": "pending_send", "batch_key": row["batch_key"],
                "idempotency_key": f"ai:{row['id']}",
                "correlation_id": row.get("correlation_id"),
            })
            if outbound is None:
                # A retry after a successful decision already has its outbox.
                pass
        supabase_client.complete_whatsapp_buffer(row["id"], "sent" if reply else "waiting_human")
        event_emitter.emit("whatsapp.inbound_dispatched", entity_type="lead", entity_id=str(row.get("lead_ref") or ""), persona_id=row["persona_id"], payload={"correlation_id": row.get("correlation_id"), "reply_queued": bool(reply)}, source="workers.whatsapp")

    def _dispatch_outbound(self, row: dict[str, Any]) -> None:
        binding = supabase_client.get_active_workflow_binding_by_phone_number_id(row["whatsapp_phone_number_id"])
        if not binding or binding.get("persona_id") != row.get("persona_id"):
            raise RuntimeError("active binding does not match outbound persona")
        metadata = binding.get("metadata") or {}
        webhook_url = (
            metadata.get("outbound_webhook_url")
            or metadata.get("webhook_url")
            or os.environ.get("N8N_OUTBOUND_WEBHOOK_URL")
            or ""
        ).strip()
        if not webhook_url:
            raise RuntimeError("outbound n8n webhook is not configured")
        lead = supabase_client.get_lead_by_ref(row.get("lead_ref")) if row.get("lead_ref") else {}
        recipient = re.sub(r"\D", "", str((lead or {}).get("telefone") or (lead or {}).get("lead_id") or ""))
        if not recipient:
            raise RuntimeError("outbound lead has no WhatsApp recipient")
        status, _ = n8n_client.send_to_webhook(webhook_url, {
            "buffer_id": row["id"], "lead_ref": row.get("lead_ref"), "persona_id": row["persona_id"],
            "phone_number_id": row["whatsapp_phone_number_id"], "to": recipient,
            "text": (row.get("payload") or {}).get("text", ""),
            "correlation_id": row.get("correlation_id"),
        }, secret=(os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or None))
        if not 200 <= status < 300:
            raise RuntimeError(f"n8n outbound returned HTTP {status}")
        # n8n must post /internal/whatsapp/outbound-result with the Meta wamid.
        # Once transport accepts the hand-off this row is no longer eligible for
        # a second send; delivery callbacks reconcile sent/delivered/read.
        supabase_client.complete_whatsapp_buffer(row["id"], "sent")

    def _retry_or_dead_letter(self, row: dict[str, Any], exc: Exception) -> None:
        attempts, maximum = int(row.get("attempt_count") or 1), int(row.get("max_attempts") or 5)
        error = f"{type(exc).__name__}: {str(exc)[:800]}"
        if attempts >= maximum:
            supabase_client.complete_whatsapp_buffer(row["id"], "dead_letter", error=error)
            sre_logger.error(self.name, f"dead-letter buffer={row['id']}: {error}")
            return
        supabase_client.release_whatsapp_buffer(row["id"], "retry", delay_seconds=_retry_delay(attempts), error=error)

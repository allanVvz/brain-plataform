"""Project canonical Brain messages and execute signed Chatwoot commands."""

from __future__ import annotations

import re
import socket
import uuid
from typing import Any

from repositories import chatwoot_bridge
from services import chatwoot_api, operator_messaging, runtime_client, sre_logger, supabase_client
from workers.base_worker import BaseWorker


class ChatwootBridgeWorker(BaseWorker):
    name = "ChatwootBridgeWorker"
    interval = 3

    def __init__(self) -> None:
        super().__init__()
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4()}"

    def _run_cycle(self) -> None:
        config = chatwoot_api.configuration()
        if config is None:
            return
        binding = supabase_client.get_workflow_binding_by_id(config.binding_id)
        if (
            not binding or not binding.get("active")
            or binding.get("provider") != "meta_cloud"
            or not binding.get("whatsapp_phone_number_id")
        ):
            raise RuntimeError("configured Chatwoot binding is not an active Meta Cloud binding")

        chatwoot_bridge.enqueue_projections(config.binding_id, limit=500)
        api = chatwoot_api.ChatwootApi(config)
        try:
            for operation in chatwoot_bridge.claim_operations(self.worker_id, limit=20):
                self._process_operation(api, config, operation)
            self._sync_delivery_statuses(api)
        finally:
            api.close()

    def _process_operation(self, api: chatwoot_api.ChatwootApi, config, operation: dict[str, Any]) -> None:
        try:
            kind = operation.get("operation")
            if kind == "project_message":
                message = chatwoot_bridge.get_message(int(operation["brain_message_id"]))
                if not message:
                    self._finish(operation, "ignored")
                    return
                lead_ref = int(operation["lead_ref"])
                lead = supabase_client.get_lead_by_ref(lead_ref) or {}
                if (
                    int(message.get("lead_id") or 0) != lead_ref
                    or str(lead.get("channel_binding_id") or "") != config.binding_id
                ):
                    self._finish(operation, "ignored", "message binding mismatch")
                    return
                if message.get("direction") not in {"inbound", "outbound"}:
                    self._finish(operation, "ignored")
                    return
                mapping = self._ensure_conversation(api, config, lead_ref, lead)
                content = str(message.get("content") or "").strip()
                if not content:
                    self._finish(operation, "ignored", "empty canonical message")
                    return
                source_id = f"brain-message:{message['id']}"
                existing = None
                # First delivery creates directly. If the HTTP response or DB
                # receipt was lost, reconcile from the last completed Chatwoot
                # message before retrying the non-unique source_id POST.
                if int(operation.get("attempt_count") or 1) > 1:
                    existing = api.find_message_by_source_id(
                        conversation_id=int(mapping["conversation_id"]),
                        source_id=source_id,
                        after_message_id=int(mapping.get("last_projected_message_id") or 0),
                    )
                if existing:
                    remote_message_id = int(existing.get("id") or 0) or None
                else:
                    metadata = message.get("metadata") or {}
                    message_origin = str(message.get("message_origin") or metadata.get("message_origin") or "")
                    sender_origin = (
                        "customer" if message.get("direction") == "inbound"
                        else "attendant" if message_origin == "manual" or metadata.get("source") == "chatwoot"
                        else "vitoria"
                    )
                    created = api.create_message(
                        conversation_id=int(mapping["conversation_id"]),
                        source_id=source_id,
                        content=content,
                        incoming=message.get("direction") == "inbound",
                        external_created_at=str(message.get("created_at") or "") or None,
                        content_attributes={
                            "brain_message_id": int(message["id"]),
                            "brain_sender_origin": sender_origin,
                            "brain_status": str(message.get("status") or ""),
                        },
                    )
                    remote_message_id = int(created.get("id") or 0) or None
                finished = self._finish(
                    operation, "completed",
                    chatwoot_message_id=remote_message_id,
                    chatwoot_conversation_id=int(mapping["conversation_id"]),
                )
                if finished and remote_message_id:
                    try:
                        chatwoot_bridge.update_last_projected_message_id(
                            config.binding_id, lead_ref, remote_message_id,
                        )
                    except Exception:
                        # The completed operation is already the durable
                        # receipt; a later retry can still reconcile via it.
                        sre_logger.error(self.name, f"operation={operation.get('id')} cursor_update_failed")
                return

            if kind in {"pause_ai", "resume_ai"} and not operation.get("chatwoot_message_id"):
                if kind == "pause_ai":
                    runtime_client.pause_ai(int(operation["lead_ref"]))
                else:
                    self._finish(operation, "ignored", "resume requires a private Chatwoot command")
                    return
                self._finish(operation, "completed")
                return

            mapping = chatwoot_bridge.get_conversation(
                config.binding_id, int(operation["lead_ref"]),
            )
            if not mapping or int(mapping.get("conversation_id") or 0) != int(operation.get("chatwoot_conversation_id") or 0):
                self._finish(operation, "ignored", "Chatwoot conversation mapping mismatch")
                return
            message = api.get_message(
                conversation_id=int(mapping["conversation_id"]),
                message_id=int(operation["chatwoot_message_id"]),
            )
            if not message:
                raise RuntimeError("Chatwoot message is not available yet")
            sender = message.get("sender") or {}
            if int(sender.get("id") or 0) != config.agent_id:
                self._finish(operation, "ignored", "sender is not the configured attendant")
                return

            if kind == "resume_ai":
                if not message.get("private") or str(message.get("content") or "").strip().casefold() not in {"/retomar-ia", "!retomar-ia"}:
                    self._finish(operation, "ignored", "resume command must be a private note")
                    return
                runtime_client.resume_ai(int(operation["lead_ref"]))
                self._finish(operation, "completed")
                return

            if kind == "pause_ai":
                if not message.get("private") or str(message.get("content") or "").strip().casefold() not in {"/assumir-ia", "!assumir-ia"}:
                    self._finish(operation, "ignored", "handoff command must be a private note")
                    return
                runtime_client.pause_ai(int(operation["lead_ref"]))
                self._finish(operation, "completed")
                return

            if kind != "human_reply" or message.get("private"):
                self._finish(operation, "ignored", "only public human replies can be sent")
                return
            if message.get("attachments"):
                self._finish(operation, "dead_letter", "Chatwoot attachments are not enabled for this bridge")
                return
            content = str(message.get("content") or "").strip()
            if not content:
                self._finish(operation, "ignored", "empty human message")
                return

            # Handoff is the runtime's authoritative, atomic pause. It parks
            # outstanding inbound work before the human message enters outbox.
            runtime_client.pause_ai(int(operation["lead_ref"]))
            lead = supabase_client.get_lead_by_ref(int(operation["lead_ref"])) or {}
            if not lead or str(lead.get("channel_binding_id") or "") != config.binding_id:
                self._finish(operation, "ignored", "lead binding mismatch")
                return
            dedupe_uuid = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"chatwoot:{config.account_id}:{config.inbox_id}:{operation['chatwoot_message_id']}",
            ))
            result = operator_messaging.enqueue(
                lead_ref=int(operation["lead_ref"]),
                persona_id=str(lead["persona_id"]),
                client_message_id=dedupe_uuid,
                text=content,
                metadata={
                    "source": "chatwoot",
                    "chatwoot_message_id": int(operation["chatwoot_message_id"]),
                    "chatwoot_conversation_id": int(operation["chatwoot_conversation_id"]),
                    "chatwoot_agent_id": config.agent_id,
                },
            )
            self._finish(
                operation, "completed",
                chatwoot_message_id=int(operation["chatwoot_message_id"]),
                chatwoot_conversation_id=int(operation["chatwoot_conversation_id"]),
                transport_buffer_id=str(result["buffer_id"]),
            )
        except Exception as exc:
            attempts = int(operation.get("attempt_count") or 1)
            status = "dead_letter" if attempts >= 20 else "retry"
            retry_seconds = min(3600, 5 * (2 ** min(attempts - 1, 9)))
            # Exception detail can include remote/customer data; keep it out of
            # logs and persist only the exception class for operator diagnosis.
            error = f"{type(exc).__name__}: Chatwoot bridge operation failed"
            self._finish(operation, status, error, retry_seconds=retry_seconds)
            sre_logger.error(self.name, f"operation={operation.get('id')} status={status} error_type={type(exc).__name__}")

    def _ensure_conversation(self, api, config, lead_ref: int, lead: dict) -> dict[str, Any]:
        mapping = chatwoot_bridge.get_conversation(config.binding_id, lead_ref)
        if mapping and mapping.get("conversation_id"):
            return mapping
        phone = re.sub(r"\D", "", str(
            lead.get("external_contact_id") or lead.get("telefone") or ""
        ))
        if not 8 <= len(phone) <= 15:
            raise RuntimeError("lead phone number is unavailable")
        identifier = f"brain:{config.binding_id}:{lead_ref}"
        contact = api.create_or_get_contact(
            identifier=identifier,
            name=str(lead.get("nome") or "Contato WhatsApp"),
            phone_number=f"+{phone}",
        )
        contact_id = int(contact.get("id") or 0)
        contact_inboxes = contact.get("contact_inboxes") or []
        session = next(
            (item for item in contact_inboxes
             if int(((item.get("inbox") or {}).get("id") or 0)) == config.inbox_id
             and item.get("source_id")),
            None,
        )
        if not session:
            session = next((item for item in contact_inboxes if item.get("source_id")), None)
        contact_identifier = str((session or {}).get("source_id") or "")
        if not contact_id or not contact_identifier:
            raise RuntimeError("Chatwoot contact response has no inbox session")

        source_id = f"brain-conversation:{config.binding_id}:{lead_ref}"
        conversations = api.list_conversations(contact_identifier=contact_identifier)
        conversation = next((item for item in conversations
            if int(((item.get("custom_attributes") or {}).get("brain_lead_ref") or 0)) == lead_ref), None)
        if not conversation:
            # The API Inbox may accept the conversation but lose the HTTP
            # response before the mapping transaction commits. This contact
            # identifier is unique to one Brain lead, so reuse its open
            # conversation on retry rather than creating a duplicate.
            conversation = next((item for item in conversations if item.get("status") == "open"), None)
        if not conversation:
            conversation = api.create_conversation(
                contact_identifier=contact_identifier, source_id=source_id, lead_ref=lead_ref,
            )
        conversation_id = int(conversation.get("id") or 0)
        if not conversation_id:
            raise RuntimeError("Chatwoot conversation response has no id")
        api.assign_conversation(conversation_id)
        saved = chatwoot_bridge.save_conversation({
            "channel_binding_id": config.binding_id,
            "lead_ref": lead_ref,
            "account_id": config.account_id,
            "inbox_id": config.inbox_id,
            "contact_id": contact_id,
            "contact_identifier": contact_identifier,
            "conversation_id": conversation_id,
        })
        return saved

    def _sync_delivery_statuses(self, api: chatwoot_api.ChatwootApi) -> None:
        for operation in chatwoot_bridge.pending_delivery_updates(limit=50):
            buffer = chatwoot_bridge.get_delivery_buffer(str(operation["transport_buffer_id"])) or {}
            source_status = str(buffer.get("status") or "")
            status = {
                "sent": "sent", "delivered": "delivered", "read": "read",
                "dead_letter": "failed", "waiting_human": "failed",
            }.get(source_status)
            if not status:
                continue
            api.update_message_status(
                conversation_id=int(operation["chatwoot_conversation_id"]),
                message_id=int(operation["chatwoot_message_id"]),
                status=status,
            )
            chatwoot_bridge.mark_delivery_status(str(operation["id"]), status)

    def _finish(
        self, operation: dict[str, Any], status: str, error: str | None = None,
        *, retry_seconds: int = 30, chatwoot_message_id: int | None = None,
        chatwoot_conversation_id: int | None = None, transport_buffer_id: str | None = None,
    ) -> bool:
        return chatwoot_bridge.finish_operation(
            str(operation["id"]), self.worker_id, status, error=error,
            retry_seconds=retry_seconds,
            chatwoot_message_id=chatwoot_message_id,
            chatwoot_conversation_id=chatwoot_conversation_id,
            transport_buffer_id=transport_buffer_id,
        )

"""Small, authenticated Chatwoot API client for the Tock Fatal API inbox."""

from __future__ import annotations

import os
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from utils.tls import get_ca_bundle_path


# Private-note commands an attendant types in the Chatwoot app. Nothing else in a
# private note is ever interpreted. "ligar/desligar" mirror the portal's agent
# on/off switch so the same words work in both places.
RESUME_COMMANDS = frozenset({
    "/retomar-ia", "!retomar-ia", "/ligar-ia", "/ligar-agente", "/ligar",
})
PAUSE_COMMANDS = frozenset({
    "/assumir-ia", "!assumir-ia", "/desligar-ia", "/desligar-agente", "/desligar",
})


def command_operation(content: object) -> str | None:
    """`resume_ai` / `pause_ai` for a private-note command, else None."""
    text = str(content or "").strip().casefold()
    if text in RESUME_COMMANDS:
        return "resume_ai"
    if text in PAUSE_COMMANDS:
        return "pause_ai"
    return None


def verify_webhook_signature(
    raw_body: bytes, timestamp: str | None, signature: str | None,
    secret: str, *, now: int | None = None,
) -> bool:
    try:
        stamp = int(timestamp or "")
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else int(time.time())) - stamp) > 300:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


@dataclass(frozen=True)
class ChatwootConfig:
    base_url: str
    api_token: str
    account_id: int
    inbox_id: int
    inbox_identifier: str
    binding_id: str
    webhook_secret: str
    agent_id: int


def configuration() -> ChatwootConfig | None:
    if (os.getenv("CHATWOOT_BRIDGE_ENABLED") or "").strip().lower() not in {"1", "true", "yes"}:
        return None
    base_url = (os.getenv("CHATWOOT_BASE_URL") or "").strip().rstrip("/")
    token = (os.getenv("CHATWOOT_API_ACCESS_TOKEN") or "").strip()
    inbox_identifier = (os.getenv("CHATWOOT_INBOX_IDENTIFIER") or "").strip()
    binding_id = (os.getenv("CHATWOOT_BRIDGE_BINDING_ID") or "").strip()
    secret = (os.getenv("CHATWOOT_WEBHOOK_SECRET") or "").strip()
    try:
        account_id = int(os.getenv("CHATWOOT_ACCOUNT_ID") or "")
        inbox_id = int(os.getenv("CHATWOOT_INBOX_ID") or "")
        agent_id = int(os.getenv("CHATWOOT_AGENT_ID") or "")
    except ValueError as exc:
        raise RuntimeError("Chatwoot bridge identifiers are not configured") from exc
    if not all((base_url, token, inbox_identifier, binding_id, secret)):
        raise RuntimeError("Chatwoot bridge credentials are not configured")
    if not base_url.startswith("https://"):
        raise RuntimeError("Chatwoot bridge requires an HTTPS base URL")
    return ChatwootConfig(
        base_url=base_url,
        api_token=token,
        account_id=account_id,
        inbox_id=inbox_id,
        inbox_identifier=inbox_identifier,
        binding_id=binding_id,
        webhook_secret=secret,
        agent_id=agent_id,
    )


class ChatwootApi:
    def __init__(self, config: ChatwootConfig) -> None:
        self.config = config
        self._client = httpx.Client(
            timeout=httpx.Timeout(20, connect=5), verify=get_ca_bundle_path(),
            headers={"api_access_token": config.api_token},
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self, method: str, path: str, *, json: dict | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self._client.request(
            method, self.config.base_url + path, json=json, params=params,
        )
        if response.status_code >= 400:
            # Do not include response bodies or request URLs in error text: the
            # API may echo customer text or account identifiers.
            raise RuntimeError(f"Chatwoot API returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("Chatwoot API returned invalid JSON") from exc

    def create_or_get_contact(
        self, *, identifier: str, name: str, phone_number: str,
    ) -> dict[str, Any]:
        inbox = quote(self.config.inbox_identifier, safe="")
        return self._request(
            "POST", f"/public/api/v1/inboxes/{inbox}/contacts",
            json={
                "identifier": identifier,
                "name": name or identifier,
                "phone_number": phone_number,
                "custom_attributes": {"brain_managed": True},
            },
        )

    def get_contact(self, *, contact_id: int) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/v1/accounts/{self.config.account_id}/contacts/{int(contact_id)}",
        )

    def create_contact_inbox(
        self, *, contact_id: int, source_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/accounts/{self.config.account_id}/contacts/{int(contact_id)}/contact_inboxes",
            json={"inbox_id": self.config.inbox_id, "source_id": source_id},
        )

    def list_conversations(self, *, contact_identifier: str) -> list[dict[str, Any]]:
        inbox = quote(self.config.inbox_identifier, safe="")
        contact = quote(contact_identifier, safe="")
        payload = self._request(
            "GET", f"/public/api/v1/inboxes/{inbox}/contacts/{contact}/conversations",
        )
        if isinstance(payload, dict):
            payload = payload.get("payload") or payload.get("conversations") or []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def create_conversation(
        self, *, contact_identifier: str, source_id: str, lead_ref: int,
    ) -> dict[str, Any]:
        inbox = quote(self.config.inbox_identifier, safe="")
        contact = quote(contact_identifier, safe="")
        return self._request(
            "POST", f"/public/api/v1/inboxes/{inbox}/contacts/{contact}/conversations",
            json={
                "source_id": source_id,
                "custom_attributes": {"brain_managed": True, "brain_lead_ref": int(lead_ref)},
            },
        )

    def assign_conversation(self, conversation_id: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/accounts/{self.config.account_id}/conversations/{int(conversation_id)}/assignments",
            json={"assignee_id": self.config.agent_id},
        )

    def list_messages(self, *, conversation_id: int, after_message_id: int = 0) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", f"/api/v1/accounts/{self.config.account_id}/conversations/{int(conversation_id)}/messages",
            params={"after": max(0, int(after_message_id))},
        )
        if isinstance(payload, dict):
            payload = payload.get("payload") or payload.get("messages") or []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def find_message_by_source_id(
        self, *, conversation_id: int, source_id: str, after_message_id: int,
    ) -> dict[str, Any] | None:
        cursor = max(0, int(after_message_id))
        while True:
            page = self.list_messages(conversation_id=conversation_id, after_message_id=cursor)
            found = next((item for item in page if str(item.get("source_id") or "") == source_id), None)
            if found:
                return found
            if len(page) < 100:
                return None
            next_cursor = max((int(item.get("id") or 0) for item in page), default=cursor)
            if next_cursor <= cursor:
                return None
            cursor = next_cursor

    def create_message(
        self, *, conversation_id: int,
        source_id: str, content: str, incoming: bool,
        external_created_at: str | None = None,
        content_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "content": content,
            "message_type": "incoming" if incoming else "outgoing",
            "private": False,
            "source_id": source_id,
            "content_type": "text",
            "content_attributes": {
                **(content_attributes or {}),
                "brain_bridge_v1": True,
            },
        }
        if external_created_at:
            body["external_created_at"] = external_created_at
        return self._request(
            "POST",
            f"/api/v1/accounts/{self.config.account_id}/conversations/{int(conversation_id)}/messages",
            json=body,
        )

    def get_message(self, *, conversation_id: int, message_id: int) -> dict[str, Any] | None:
        cursor = 0
        while True:
            page = self.list_messages(conversation_id=conversation_id, after_message_id=cursor)
            found = next((item for item in page if int(item.get("id") or 0) == int(message_id)), None)
            if found:
                return found
            if len(page) < 100:
                return None
            next_cursor = max((int(item.get("id") or 0) for item in page), default=cursor)
            if next_cursor <= cursor:
                return None
            cursor = next_cursor

    def update_message_status(
        self, *, conversation_id: int, message_id: int, status: str,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/v1/accounts/{self.config.account_id}/conversations/{int(conversation_id)}/messages/{int(message_id)}",
            json={"status": status},
        )

from __future__ import annotations

import base64
import os
import time
from typing import Any

import httpx

from services import secret_store
from utils.tls import get_ca_bundle_path


class EvolutionWhatsAppProvider:
    def __init__(self) -> None:
        self.base_url = (os.environ.get("EVOLUTION_API_URL") or "http://evolution-api:8080").rstrip("/")
        self.api_key = (os.environ.get("EVOLUTION_AUTHENTICATION_API_KEY") or "").strip()

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("EVOLUTION_AUTHENTICATION_API_KEY is not configured")
        response = None
        for attempt in range(12):
            try:
                with httpx.Client(
                    base_url=self.base_url,
                    timeout=httpx.Timeout(20.0, connect=5.0),
                    follow_redirects=False,
                    verify=get_ca_bundle_path(),
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                ) as client:
                    response = client.request(method, path, json=json)
                break
            except httpx.ConnectError:
                if attempt == 11:
                    raise
                time.sleep(1.0)
        if response is None:
            raise RuntimeError("Evolution API did not return a response")
        response.raise_for_status()
        if not response.content:
            return {"ok": True}
        body = response.json()
        return body if isinstance(body, dict) else {"data": body}

    def provision_instance(
        self,
        instance_name: str,
        token: str,
        webhook_url: str,
        *,
        webhook_token: str,
    ) -> dict[str, Any]:
        return self._request("POST", "/instance/create", json={
            "instanceName": instance_name,
            "integration": "WHATSAPP-BAILEYS",
            "token": token,
            # Provisioning and QR consent are separate portal actions. This
            # avoids rotating a live session or producing a QR unexpectedly.
            "qrcode": False,
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "webhookByEvents": False,
                "webhookBase64": False,
                "headers": {"X-Brain-Webhook-Token": webhook_token},
                "events": [
                    "MESSAGES_UPSERT", "MESSAGES_UPDATE", "SEND_MESSAGE",
                    "CONNECTION_UPDATE", "QRCODE_UPDATED",
                ],
            },
            "settings": {"syncFullHistory": False, "groupsIgnore": True},
        })

    @staticmethod
    def _name(binding: dict[str, Any]) -> str:
        name = str(binding.get("provider_instance_key") or "")
        if not name:
            raise RuntimeError("Evolution binding has no instance key")
        return name

    @staticmethod
    def _token(binding: dict[str, Any]) -> str | None:
        return secret_store.decrypt_secret(binding.get("provider_secret_ciphertext"))

    def get_connection_status(self, binding: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", f"/instance/connectionState/{self._name(binding)}")

    def get_qr_code(self, binding: dict[str, Any]) -> dict[str, Any]:
        connection = self.get_connection_status(binding)
        state = str((connection.get("instance") or {}).get("state") or connection.get("state") or "").lower()
        if state in {"open", "connected"}:
            return {"status": "connected", "qr": None}
        path = f"/instance/connect/{self._name(binding)}"
        normalized_qr = None
        # Evolution generates the PNG from the Baileys callback after the
        # connection has entered "connecting". Keep the wait bounded and never
        # persist or log the returned QR payload.
        for attempt in range(12):
            body = self._request("GET", path)
            qr = body.get("base64") or (body.get("qrcode") or {}).get("base64")
            normalized_qr = self._normalize_qr(qr)
            if normalized_qr:
                break
            if attempt < 11:
                time.sleep(0.75)
        return {
            "status": "qr_ready" if normalized_qr else "connecting",
            "qr": {"base64": normalized_qr} if normalized_qr else None,
        }

    @staticmethod
    def _normalize_qr(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = value.strip()
        encoded = candidate
        if candidate.startswith("data:"):
            prefix, separator, encoded = candidate.partition(",")
            if not separator or prefix.lower() != "data:image/png;base64":
                return None
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return None
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        return f"data:image/png;base64,{encoded}"

    def send_text(self, binding: dict[str, Any], recipient: str, text: str) -> dict[str, Any]:
        return self._request("POST", f"/message/sendText/{self._name(binding)}", json={
            "number": recipient,
            "text": text,
        })

    def send_media(self, binding: dict[str, Any], recipient: str, media: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/message/sendMedia/{self._name(binding)}", json={
            "number": recipient,
            **media,
        })

    def restart_instance(self, binding: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/instance/restart/{self._name(binding)}")

    def logout_instance(self, binding: dict[str, Any]) -> dict[str, Any]:
        return self._request("DELETE", f"/instance/logout/{self._name(binding)}")

    def delete_instance(self, binding: dict[str, Any]) -> dict[str, Any]:
        return self._request("DELETE", f"/instance/delete/{self._name(binding)}")

    def normalize_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        event = str(payload.get("event") or payload.get("type") or "").upper().replace(".", "_")
        data = payload.get("data") or {}
        key = data.get("key") or {}
        remote_jid = key.get("remoteJid") or data.get("remoteJid")
        remote_alt = key.get("remoteJidAlt") or data.get("remoteJidAlt")
        external_contact = remote_alt or remote_jid
        message = data.get("message") or {}
        text = (
            message.get("conversation")
            or (message.get("extendedTextMessage") or {}).get("text")
            or data.get("text")
            or ""
        )
        return [{
            "event_type": event,
            "instance": payload.get("instance") or data.get("instance"),
            "external_message_id": key.get("id") or data.get("messageId"),
            "external_contact_id": external_contact,
            "remote_jid": remote_jid,
            "remote_jid_alt": remote_alt,
            "from_me": bool(key.get("fromMe") or data.get("fromMe")),
            "status": data.get("status") or data.get("update", {}).get("status"),
            "text": text,
            "raw": data,
        }]

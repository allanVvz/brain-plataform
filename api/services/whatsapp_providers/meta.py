from __future__ import annotations

import json
from typing import Any

import httpx

from services import secret_store


class MetaWhatsAppProvider:
    """Binding-owned Meta Cloud transport."""

    def send_text(self, binding: dict[str, Any], recipient: str, text: str) -> dict[str, Any]:
        if not binding.get("whatsapp_phone_number_id"):
            raise RuntimeError("Meta binding has no phone number id")
        secret = secret_store.decrypt_secret(binding.get("provider_secret_ciphertext"))
        if not secret:
            raise RuntimeError("Meta binding has no valid credential")
        try:
            credential = json.loads(secret)
            token = str(credential.get("access_token") or "")
            api_version = str(credential.get("api_version") or "v21.0")
        except json.JSONDecodeError:
            token, api_version = secret, "v21.0"
        if not token:
            raise RuntimeError("Meta binding credential has no access token")
        response = httpx.post(
            f"https://graph.facebook.com/{api_version}/{binding['whatsapp_phone_number_id']}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "to": recipient, "type": "text",
                  "text": {"body": text}}, timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    def provision_instance(self, *_args, **_kwargs):
        raise NotImplementedError("Meta provisioning is managed by the existing integration flow")

    def normalize_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"event_type": "META_RAW", "raw": payload}]

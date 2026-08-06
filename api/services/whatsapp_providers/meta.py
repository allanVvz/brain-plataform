from __future__ import annotations

import json
from typing import Any

import httpx

from services import secret_store


def _extract_meta_error_detail(response: httpx.Response) -> str:
    """Pull Graph API's own error message out of a failed response.

    Meta returns a structured body (`{"error": {"code", "message", ...}}`)
    that explains exactly why a send was rejected (unapproved template,
    parameter mismatch, invalid recipient, ...). Without this, only the
    generic 'N Bad Request' status survives into our logs/dashboard,
    leaving every failure equally undiagnosable.
    """
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return json.dumps(payload)[:500]
    parts = [
        f"code={error.get('code')}",
        f"subcode={error.get('error_subcode')}",
        f"message={error.get('message')}",
    ]
    if error.get("error_data"):
        parts.append(f"details={error.get('error_data')}")
    return "; ".join(str(part) for part in parts)[:500]


def _raise_for_status_with_detail(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _extract_meta_error_detail(response)
        raise httpx.HTTPStatusError(
            f"{exc} | meta_error: {detail}" if detail else str(exc),
            request=exc.request,
            response=exc.response,
        ) from exc


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
        _raise_for_status_with_detail(response)
        return response.json()

    def send_template(
        self,
        binding: dict[str, Any],
        recipient: str,
        *,
        template_name: str,
        template_language: str,
        components: list[dict[str, Any]],
    ) -> dict[str, Any]:
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
        template: dict[str, Any] = {"name": template_name, "language": {"code": template_language}}
        if components:
            template["components"] = components
        response = httpx.post(
            f"https://graph.facebook.com/{api_version}/{binding['whatsapp_phone_number_id']}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "to": recipient, "type": "template",
                  "template": template}, timeout=30.0,
        )
        _raise_for_status_with_detail(response)
        return response.json()

    def provision_instance(self, *_args, **_kwargs):
        raise NotImplementedError("Meta provisioning is managed by the existing integration flow")

    def normalize_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"event_type": "META_RAW", "raw": payload}]

    # Meta Cloud has no equivalent of these Evolution/Baileys instance
    # concepts (QR pairing, restart, logout of a local session). Explicit
    # stubs so a generic `binding.provider`-dispatched call fails with a
    # clear message instead of a bare AttributeError.
    def get_connection_status(self, binding: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud bindings have no connection-status polling; use webhook status callbacks")

    def get_qr_code(self, binding: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud bindings are not paired via QR code")

    def restart_instance(self, binding: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud bindings have no local instance to restart")

    def logout_instance(self, binding: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud bindings have no local instance to log out")

    def send_media(self, binding: dict[str, Any], recipient: str, media: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Meta Cloud media send is not implemented yet")

from __future__ import annotations

from typing import Any


class MetaWhatsAppProvider:
    """Marker adapter for the existing Meta/n8n transport.

    Existing webhook validation and n8n delivery remain the compatibility
    implementation until direct Meta transport is migrated behind this class.
    """

    def provision_instance(self, *_args, **_kwargs):
        raise NotImplementedError("Meta provisioning is managed by the existing integration flow")

    def normalize_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"event_type": "META_RAW", "raw": payload}]

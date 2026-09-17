"""Retired n8n conversation provisioner compatibility surface.

Conversation decisions and model credentials belong to conversation-runtime.
Only checksum normalization remains for auditing historical workflow exports;
every mutating entry point fails closed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from services import n8n_client


_RETIRED = (
    "n8n conversation provisioning is retired; transport calls runtime directly"
)


def _workflow_checksum(workflow: dict[str, Any]) -> str:
    payload = n8n_client.workflow_checksum_payload(workflow)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def provision_validation_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise RuntimeError(_RETIRED)


def provision(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise RuntimeError(_RETIRED)


def resync_workflow_for_persona(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise RuntimeError(_RETIRED)


def check_workflow_wiring(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": _RETIRED,
        "diagnostics": {"retired": True},
    }


def check_binding(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": _RETIRED,
        "diagnostics": {"retired": True},
    }


def revoke(config: dict[str, Any] | None) -> None:
    """No-op: runtime secrets are not n8n credentials and are never revoked here."""

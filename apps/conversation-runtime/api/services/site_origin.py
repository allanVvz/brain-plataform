"""Attribute an inbound site reference without treating it as purchase intent."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from services import supabase_client


_CODE = re.compile(r"(?<![A-Za-z0-9])BI-[A-F0-9]{16}(?![A-Za-z0-9])")
_CODE_IN_MESSAGE = re.compile(
    r"(?:\s*C[oó]digo de atendimento\s*:\s*)?(?<![A-Za-z0-9])BI-[A-F0-9]{16}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def without_code(message: str) -> str:
    """Remove the transport reference before retrieval and commercial reasoning."""
    return _CODE_IN_MESSAGE.sub("", message or "").strip()


def resolve(message: str, persona_id: str) -> dict[str, Any] | None:
    """Return only audited provenance for a valid, unexpired, same-persona code."""
    match = _CODE.search(message or "")
    if not match or not persona_id:
        return None
    digest = hashlib.sha256(match.group().encode("ascii")).hexdigest()
    try:
        event = supabase_client.find_public_site_intent(persona_id, digest)
    except Exception:
        return None
    if not event or str(event.get("persona_id") or "") != persona_id:
        return None
    payload = event.get("payload") or {}
    if not isinstance(payload, dict) or payload.get("code_hash") != digest:
        return None
    try:
        expiry = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        return None
    audience_id = payload.get("audience_node_id")
    if not isinstance(audience_id, str) or not audience_id:
        return None
    return {
        "event_id": str(event["id"]),
        "audience_node_id": audience_id,
        "publication_id": str(payload.get("publication_id") or ""),
        "graph_checksum": str(payload.get("graph_checksum") or ""),
    }

"""Stable structured telemetry envelope without a vendor dependency."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def event(name: str, *, service: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "event": name,
        "service": service,
        "at": datetime.now(timezone.utc).isoformat(),
        "fields": fields or {},
    }

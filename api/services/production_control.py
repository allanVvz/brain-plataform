"""Read-only worker controls shared with host-side release orchestration."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def control_directory() -> Path | None:
    raw = str(os.environ.get("PRODUCTION_CONTROL_DIR") or "").strip()
    return Path(raw) if raw else None


def claims_pause() -> dict[str, Any] | None:
    directory = control_directory()
    if directory is None:
        return None
    marker = directory / "claims-paused.json"
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        # Fail closed. A damaged control marker cannot silently enable claims.
        return {"paused": True, "reason": "invalid_claims_pause_marker"}
    if not isinstance(value, dict):
        return {"paused": True, "reason": "invalid_claims_pause_marker"}
    return value if value.get("paused") is True else None


def claims_are_paused() -> bool:
    return claims_pause() is not None

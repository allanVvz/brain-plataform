"""Signed, short-lived principals for private Brain HTTP calls."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any


def sign_principal(claims: dict[str, Any], *, secret: str, ttl_seconds: int = 60) -> tuple[str, str]:
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("BRAIN_INTERNAL_AUTH_SECRET must contain at least 32 bytes")
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + ttl_seconds, "nonce": uuid.uuid4().hex}
    token = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), token.encode("ascii"), hashlib.sha256).hexdigest()
    return token, signature


def verify_principal(token: str, signature: str, *, secret: str) -> dict[str, Any]:
    expected = hmac.new(secret.encode("utf-8"), token.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("invalid internal principal signature")
    padded = token + "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    if not isinstance(payload, dict) or int(payload.get("exp") or 0) <= int(time.time()):
        raise ValueError("expired internal principal")
    return payload

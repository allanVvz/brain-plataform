from __future__ import annotations

import hmac
import os

from fastapi import HTTPException


def authorize_webhook_token(token: str | None) -> None:
    expected = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "internal webhook token is not configured")
    if not hmac.compare_digest(
        (token or "").encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(401, "invalid webhook token")


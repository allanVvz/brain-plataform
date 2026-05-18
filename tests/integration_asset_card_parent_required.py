#!/usr/bin/env python3
"""Without branch_hint, /assets/upload must 422 and create nothing."""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["ASSET_OCR_BACKEND"] = "mock"
os.environ["ASSET_RENAME_DISABLE_MODEL"] = "1"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


class _UploadFile:
    def __init__(self, content: bytes, filename: str, content_type: str):
        self.file = io.BytesIO(content); self.filename = filename; self.content_type = content_type
    async def read(self): return self.file.read()


class _Request:
    def __init__(self): self.state = type("S", (), {})()


def main() -> int:
    from fastapi import HTTPException
    from routes import assets as routes_assets
    from services import auth_service, supabase_client

    auth_orig = auth_service.assert_persona_access
    persona_orig = supabase_client.get_persona_by_id
    insert_orig = supabase_client.insert_asset
    inserts: list = []
    try:
        auth_service.assert_persona_access = lambda *a, **kw: None
        supabase_client.get_persona_by_id = lambda pid: {"id": pid, "slug": "tock-fatal"}
        supabase_client.insert_asset = lambda data: (inserts.append(data) or {"id": "should-not-happen"})

        try:
            asyncio.run(routes_assets.upload_asset(
                _Request(),
                file=_UploadFile(b"\x89PNG\r\n\x1a\n", "x.png", "image/png"),
                persona_id="p-1",
                branch_hint=None,  # <-- missing on purpose
                asset_function=None,
                persona_slug="tock-fatal",
            ))
        except HTTPException as exc:
            _assert(exc.status_code == 422, "endpoint responds 422 when branch_hint is missing")
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            _assert(detail.get("needs_parent") is True, "detail.needs_parent=True signals UI to pick a branch")
        else:
            raise AssertionError("expected HTTPException when branch_hint missing")

        _assert(len(inserts) == 0, "no asset row inserted when validation fails")
    finally:
        auth_service.assert_persona_access = auth_orig
        supabase_client.get_persona_by_id = persona_orig
        supabase_client.insert_asset = insert_orig

    print("PASS integration_asset_card_parent_required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

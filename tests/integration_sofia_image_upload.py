#!/usr/bin/env python3
"""Sofia/CRIAR /kb-intake/upload attaches the reading to the session and NEVER
creates a knowledge_item for the asset. Asset row is tagged upload_context='sofia_chat'."""
from __future__ import annotations

import asyncio
import io
import os
import sys
from copy import deepcopy
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


class FakeStore:
    def __init__(self) -> None:
        self.persona = {"id": "p-1", "slug": "tock-fatal", "name": "Tock Fatal"}
        self.assets_inserted: list[dict] = []
        self.asset_readings: list[dict] = []
        self.kb_intake_rows: list[dict] = []
        self.knowledge_items_inserted: list[dict] = []
        self.uploaded: list[tuple[str, str]] = []

    def upload_to_storage(self, bucket, path, data, content_type="application/octet-stream"):
        self.uploaded.append((bucket, path))
        return f"https://supa.local/{bucket}/{path}"

    def insert_kb_intake(self, data):
        row = {**deepcopy(data), "id": f"kb-{len(self.kb_intake_rows)+1}"}
        self.kb_intake_rows.append(row); return deepcopy(row)

    def insert_asset(self, data):
        row = {**deepcopy(data), "id": f"a-{len(self.assets_inserted)+1}"}
        self.assets_inserted.append(row); return deepcopy(row)

    def insert_asset_reading(self, data):
        row = {**deepcopy(data), "id": f"ar-{len(self.asset_readings)+1}"}
        self.asset_readings.append(row); return deepcopy(row)

    def insert_knowledge_item(self, data):
        row = {**deepcopy(data), "id": f"ki-NOT-EXPECTED-{len(self.knowledge_items_inserted)+1}"}
        self.knowledge_items_inserted.append(row); return deepcopy(row)


class _UploadFile:
    def __init__(self, content: bytes, filename: str, content_type: str):
        self.file = io.BytesIO(content)
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self.file.read()


def _make_session(persona_id: str, persona_slug: str) -> dict:
    return {
        "id": "sess-sofia-1",
        "stage": "collecting",
        "model": "gpt-4o-mini",
        "messages": [],
        "classification": {},
        "mission_state": {"persona_id": persona_id, "persona_slug": persona_slug},
        "persona_id": persona_id,
        "persona_slug": persona_slug,
        "asset_readings": [],
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": False},
    }


def main() -> int:
    from routes import kb_intake as routes_kb_intake
    from services import kb_intake_service, supabase_client

    store = FakeStore()
    session = _make_session(store.persona["id"], store.persona["slug"])

    # Place session directly in the in-memory cache; attach_reading reads & writes it.
    kb_intake_service._sessions[session["id"]] = session

    chat_calls: list[dict] = []

    def stub_chat(session_id: str, user_message: str, file_info=None, internal=False):
        chat_calls.append({"session_id": session_id, "file_info": file_info})
        return {"ok": True, "stage": "collecting"}

    patched_sb = ["upload_to_storage", "insert_kb_intake", "insert_asset", "insert_asset_reading", "insert_knowledge_item"]
    sb_orig = {n: getattr(supabase_client, n, None) for n in patched_sb}
    chat_orig_route = routes_kb_intake.chat
    try:
        for n in patched_sb:
            setattr(supabase_client, n, getattr(store, n))
        # Stub the chat() call routed through routes module reference so we do not
        # exercise the LLM path during the upload test.
        routes_kb_intake.chat = stub_chat

        upload = _UploadFile(b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "campanha.png", "image/png")
        result = asyncio.run(routes_kb_intake.upload_file(
            session_id=session["id"],
            message="quero usar essa imagem como referencia",
            file=upload,
        ))

        _assert(result.get("ok", True) is not False, "upload_file completes without ok=False")
        _assert(len(store.assets_inserted) == 1, "single public.assets row inserted for the Sofia upload")
        inserted = store.assets_inserted[0]
        _assert(inserted["upload_context"] == "sofia_chat", "asset tagged upload_context=sofia_chat")
        _assert(inserted["source"] == "upload", "asset source=upload")
        _assert(inserted["persona_id"] == store.persona["id"], "asset carries persona_id from the session")
        _assert(inserted["metadata"]["session_id"] == session["id"], "asset.metadata.session_id matches session")
        _assert(inserted["metadata"]["validation_status"] == "context_only", "Sofia assets stay context_only (no validation queue)")

        _assert(len(store.knowledge_items_inserted) == 0,
                "Sofia upload MUST NOT create knowledge_item (only context for the chat session)")

        live_session = kb_intake_service._get_session(session["id"]) or {}
        readings = live_session.get("asset_readings") or []
        _assert(len(readings) >= 1, "session.asset_readings populated by attach_reading()")
        first = readings[-1]
        _assert(first.get("file", {}).get("filename") == "campanha.png", "reading carries filename")
        _assert(isinstance(first.get("reading"), dict), "reading payload is a dict (asset_pipeline summary)")

        # The chat() handler still receives the file so Sofia can react, but the
        # critical contract is the absence of knowledge_item + presence of reading.
        _assert(len(chat_calls) == 1, "chat() invoked once with the file_info envelope")
        _assert(chat_calls[0]["file_info"]["filename"] == "campanha.png", "chat() received original filename")
        _assert(chat_calls[0]["file_info"].get("asset_reading") is not None,
                "chat() received asset_reading summary alongside the file")

        # Defensive: confirm the rag eligibility gate is intact for assets.
        from services import knowledge_rag_intake
        _assert(knowledge_rag_intake.is_rag_eligible("asset") is False,
                "is_rag_eligible('asset') stays False (assets never produce RAG entries)")
    finally:
        for n, fn in sb_orig.items():
            if fn is not None:
                setattr(supabase_client, n, fn)
        routes_kb_intake.chat = chat_orig_route
        kb_intake_service._sessions.pop(session["id"], None)

    print("PASS integration_sofia_image_upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

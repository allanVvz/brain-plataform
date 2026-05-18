#!/usr/bin/env python3
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
        self.persona = {"id": "p-lazy-1", "slug": "baita-conveniencia", "name": "Baita Conveniencia"}
        self.assets_inserted: list[dict] = []
        self.asset_readings: list[dict] = []
        self.kb_intake_rows: list[dict] = []
        self.knowledge_items_inserted: list[dict] = []

    def get_persona(self, slug: str):
        return deepcopy(self.persona) if slug == self.persona["slug"] else None

    def get_persona_by_id(self, persona_id: str):
        return deepcopy(self.persona) if persona_id == self.persona["id"] else None

    def insert_event(self, *args, **kwargs):
        return {}

    def upload_to_storage(self, bucket, path, data, content_type="application/octet-stream"):
        return f"https://supa.local/{bucket}/{path}"

    def insert_kb_intake(self, data):
        row = {**deepcopy(data), "id": f"kb-{len(self.kb_intake_rows)+1}"}
        self.kb_intake_rows.append(row)
        return deepcopy(row)

    def insert_asset(self, data):
        row = {**deepcopy(data), "id": f"a-{len(self.assets_inserted)+1}"}
        self.assets_inserted.append(row)
        return deepcopy(row)

    def insert_asset_reading(self, data):
        row = {**deepcopy(data), "id": f"ar-{len(self.asset_readings)+1}"}
        self.asset_readings.append(row)
        return deepcopy(row)

    def insert_knowledge_item(self, data):
        row = {**deepcopy(data), "id": f"ki-NOT-EXPECTED-{len(self.knowledge_items_inserted)+1}"}
        self.knowledge_items_inserted.append(row)
        return deepcopy(row)


class _UploadFile:
    def __init__(self, content: bytes, filename: str, content_type: str):
        self.file = io.BytesIO(content)
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self.file.read()


def main() -> int:
    from routes import kb_intake as routes_kb_intake
    from services import kb_intake_service, supabase_client

    store = FakeStore()
    patched_sb = [
        "get_persona",
        "get_persona_by_id",
        "insert_event",
        "upload_to_storage",
        "insert_kb_intake",
        "insert_asset",
        "insert_asset_reading",
        "insert_knowledge_item",
    ]
    sb_orig = {name: getattr(supabase_client, name, None) for name in patched_sb}
    chat_orig_service = kb_intake_service.chat
    chat_orig_route = routes_kb_intake.chat
    created_session_ids: list[str] = []
    chat_calls: list[dict] = []

    def fail_chat(*args, **kwargs):
        raise AssertionError("bootstrap_llm=false must not call chat/LLM")

    def upload_chat(session_id: str, user_message: str, file_info=None, internal=False):
        chat_calls.append({"session_id": session_id, "file_info": file_info, "internal": internal})
        return {"ok": True, "stage": "collecting"}

    try:
        for name in patched_sb:
            setattr(supabase_client, name, getattr(store, name))

        kb_intake_service.chat = fail_chat  # type: ignore[assignment]
        lazy = kb_intake_service.start_bootstrap_session(
            model="gpt-4o-mini",
            initial_context="persona_slug: baita-conveniencia\n## Blocos de conhecimento solicitados\n- briefing: x\n",
            agent_key="sofia",
            initial_state={"mode": "criar", "persona_slug": store.persona["slug"]},
            bootstrap_llm=False,
        )
        sid = lazy.get("session_id")
        created_session_ids.append(sid)
        _assert(bool(sid), "lazy start returns session_id")
        _assert(lazy.get("bootstrap_llm") is False, "lazy start reports bootstrap_llm=false")
        session = kb_intake_service.get_session(sid)
        _assert((session or {}).get("persona_id") == store.persona["id"], "lazy start resolves persona_id")
        _assert(((session or {}).get("mission_state") or {}).get("persona_id") == store.persona["id"], "mission_state carries persona_id")

        default_called: list[bool] = []

        def default_chat(session_id: str, user_message: str, file_info=None, internal=False):
            default_called.append(internal)
            return {
                "ok": True,
                "message": "bootstrap via llm",
                "classification": {},
                "stage": "chatting",
                "state": {},
            }

        kb_intake_service.chat = default_chat  # type: ignore[assignment]
        default = kb_intake_service.start_bootstrap_session(
            model="gpt-4o-mini",
            initial_context="persona_slug: baita-conveniencia\n",
            agent_key="sofia",
            initial_state={"mode": "criar", "persona_slug": store.persona["slug"]},
        )
        created_session_ids.append(default.get("session_id"))
        _assert(default_called == [True], "default start still calls chat internally")
        _assert(default.get("bootstrap_llm") is True, "default start reports bootstrap_llm=true")

        slug_only_session = {
            "id": "sess-slug-only",
            "stage": "collecting",
            "model": "gpt-4o-mini",
            "messages": [],
            "classification": {"persona_slug": store.persona["slug"]},
            "mission_state": {"persona_slug": store.persona["slug"]},
            "persona_slug": store.persona["slug"],
            "asset_readings": [],
            "telemetry_transcript": [],
            "telemetry_flags": {"dialog_started_emitted": False},
        }
        kb_intake_service._sessions[slug_only_session["id"]] = slug_only_session
        created_session_ids.append(slug_only_session["id"])
        routes_kb_intake.chat = upload_chat

        upload = _UploadFile(b"\x89PNG\r\n\x1a\n" + b"\x00" * 256, "campanha.png", "image/png")
        result = asyncio.run(routes_kb_intake.upload_file(
            session_id=slug_only_session["id"],
            message="",
            file=upload,
        ))
        _assert(result.get("ok", True) is not False, "upload succeeds with slug-only session")
        _assert(len(store.assets_inserted) == 1, "upload persists public.assets")
        _assert(store.assets_inserted[0]["persona_id"] == store.persona["id"], "asset uses resolved persona_id")
        _assert(len(store.asset_readings) >= 1, "upload persists asset_readings")
        _assert(len(store.knowledge_items_inserted) == 0, "upload does not create knowledge_item")
        _assert(len(chat_calls) == 1, "upload calls chat once after reading")
    finally:
        for name, fn in sb_orig.items():
            if fn is not None:
                setattr(supabase_client, name, fn)
        kb_intake_service.chat = chat_orig_service  # type: ignore[assignment]
        routes_kb_intake.chat = chat_orig_route
        for sid in created_session_ids:
            if sid:
                kb_intake_service._sessions.pop(sid, None)

    print("PASS integration_sofia_lazy_start_upload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

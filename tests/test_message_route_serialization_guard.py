"""The /kb-intake/message route must never emit a raw 500.

A non-serializable field in the chat() result (e.g. a set or a custom object
stashed in mission_state/plan_state by the tool loop) is encoded by FastAPI
AFTER the handler returns — outside its try/except — surfacing as a bare 500.
The route validates serialization inside the handler so the cause lands in
traceback_tail and the operator gets a controlled response instead.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from routes import kb_intake as route_mod  # noqa: E402


def _request():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))


def test_message_route_guards_nonserializable_chat_result(monkeypatch):
    monkeypatch.setattr(route_mod, "_assert_session_access", lambda session_id, request: {})
    # Simulate chat() returning a dict FastAPI cannot encode.
    monkeypatch.setattr(
        route_mod,
        "chat",
        lambda sid, msg: {"ok": True, "message": "x", "state": {"obj": object()}},
    )
    body = route_mod.MessageBody(session_id="missing-session", message="oi")

    # Must NOT raise (no raw 500).
    res = route_mod.send_message(body, _request())

    assert isinstance(res, dict)
    assert res["ok"] is False
    assert res["error_code"] == "INTERNAL_ERROR"
    assert res.get("traceback_tail"), "missing traceback_tail"

    # And the controlled error body must itself be JSON-serializable.
    route_mod._assert_json_serializable(res)


def test_message_route_passes_through_serializable_result(monkeypatch):
    monkeypatch.setattr(route_mod, "_assert_session_access", lambda session_id, request: {})
    good = {"ok": True, "message": "ola", "stage": "chatting", "proposed_entries": []}
    monkeypatch.setattr(route_mod, "chat", lambda sid, msg: good)
    body = route_mod.MessageBody(session_id="s", message="oi")
    res = route_mod.send_message(body, _request())
    assert res is good, res

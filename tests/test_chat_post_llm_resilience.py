"""Resilience contract for the post-LLM phase of kb_intake_service.chat().

When any deterministic step AFTER the model call fails (plan extraction,
normalization, visible summary, sofia_tools plan read, event emission), the
turn must fail gracefully:
  1. the unpaired user message is rolled back (not left dangling);
  2. the failure carries a traceback_tail;
  3. the next message still iterates normally;
  4. the transcript/message history stays paired user/assistant;
  5. save/graph are not advanced.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

os.environ.setdefault("SOFIA_TOOLS_ENABLED", "true")

from services import kb_intake_service as kis  # noqa: E402


def _make_session(sid: str) -> dict:
    sess = {
        "id": sid,
        "mode": "criar",
        "stage": "chatting",
        "status": "collecting",
        "persona_slug": "baita-conveniencia",
        "classification": {
            "persona_slug": "baita-conveniencia",
            "content_type": None,
            "asset_type": None,
            "asset_function": None,
            "title": None,
            "file_ext": "",
        },
        "messages": [],
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": True},
        "mission_state": kis._default_mission_state(""),
        "current_block_counts": {},
        "agent_name": "Sofia",
    }
    kis._sessions[sid] = sess
    return sess


def _boom(*_a, **_k):
    raise RuntimeError("boom post-llm")


def test_post_llm_failure_rolls_back_and_keeps_iterating(monkeypatch):
    sid = "test-resilience-post-llm"
    sess = _make_session(sid)

    # No real LLM / DB.
    monkeypatch.setattr(kis, "ModelRouter", lambda *a, **k: object())
    monkeypatch.setattr(kis, "_emit_kb_event", lambda *a, **k: None)
    canned = (
        "Resposta conversacional da Sofia, ainda sem plano.",
        {"tool_used": False, "tool_calls": [], "provider": "test"},
    )
    monkeypatch.setattr(kis, "_invoke_router_with_tools", lambda **k: canned)

    # --- Turn 1: force a post-LLM exception (in _extract_cls). ---
    monkeypatch.setattr(kis, "_extract_cls", _boom)
    res1 = kis.chat(sid, "primeira mensagem que dispara falha pos-LLM")

    assert res1.get("ok") is False, res1
    assert res1.get("error_code") == "POST_LLM_ERROR", res1
    # (2) traceback_tail present and points at the real cause.
    tail = res1.get("traceback_tail") or []
    assert tail, "missing traceback_tail"
    assert any("boom post-llm" in line for line in tail), tail
    # (1) user message rolled back — nothing left dangling.
    assert sess["messages"] == [], sess["messages"]
    roles = [t.get("role") for t in sess["telemetry_transcript"]]
    assert not roles or roles[-1] != "user", roles
    # (5) stage/graph not advanced.
    assert sess["stage"] == "chatting", sess["stage"]
    assert res1.get("stage") == "chatting", res1

    # --- Turn 2: restore the failing step; the session must still iterate. ---
    monkeypatch.undo()  # restores _extract_cls and re-applies module defaults
    # Re-apply the no-LLM/no-DB stubs removed by undo().
    monkeypatch.setattr(kis, "ModelRouter", lambda *a, **k: object())
    monkeypatch.setattr(kis, "_emit_kb_event", lambda *a, **k: None)
    monkeypatch.setattr(kis, "_invoke_router_with_tools", lambda **k: canned)

    res2 = kis.chat(sid, "segunda mensagem deve iterar normalmente")
    assert res2.get("ok") is True, res2

    # (4) history paired: exactly one user + one assistant.
    user_n = sum(1 for m in sess["messages"] if m["role"] == "user")
    asst_n = sum(1 for m in sess["messages"] if m["role"] == "assistant")
    assert user_n == 1 and asst_n == 1, sess["messages"]
    assert sess["messages"][-1]["role"] == "assistant", sess["messages"]
    # transcript also paired (last turn is the assistant reply).
    troles = [t.get("role") for t in sess["telemetry_transcript"]]
    assert troles and troles[-1] == "assistant", troles

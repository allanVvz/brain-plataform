#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"ok {msg}")


def _entry(content_type: str, slug: str) -> dict:
    return {
        "content_type": content_type,
        "title": slug.replace("-", " ").title(),
        "slug": slug,
        "status": "pendente_validacao",
        "content": f"Conteudo {slug}",
        "tags": [content_type],
        "metadata": {"parent_slug": "self" if content_type == "briefing" else "briefing-base"},
    }


def _plan(entries: list[dict]) -> dict:
    return {
        "source": "https://tockfatal.com",
        "persona_slug": "tock-fatal",
        "validation_policy": "human_validation_required",
        "tree_mode": "single_branch",
        "branch_policy": "single_branch_by_default",
        "entries": entries,
        "links": [],
    }


def main() -> int:
    invalid = svc.start_bootstrap_session(
        model="gpt-4o-mini",
        initial_context="",
        initial_state={"mode": "criar", "persona_slug": "todos"},
    )
    _assert(invalid.get("ok") is False, "criar rejects persona todos")
    _assert("Selecione uma persona" in invalid.get("message", ""), "invalid persona message returned")

    initial_counts = {"briefing": 1, "audience": 1, "product": 1, "copy": 1, "faq": 2}
    session = svc.create_session(
        model="gpt-4o-mini",
        initial_context=(
            "persona_slug: tock-fatal\n"
            "objetivo: Criar conhecimento de marketing em grafo.\n"
            "fonte principal: https://tockfatal.com\n"
        ),
        initial_state={
            "mode": "criar",
            "persona_slug": "tock-fatal",
            "source_url": "https://tockfatal.com",
            "initial_block_counts": initial_counts,
        },
    )
    sid = session["id"]
    session["classification"]["content_type"] = "faq"
    session["classification"]["title"] = "Plano Tock Fatal"
    svc._save_session(session)  # type: ignore[attr-defined]
    public_state = svc._session_public_state(session)  # type: ignore[attr-defined]
    _assert(public_state["persona_slug"] == "tock-fatal", "session stores selected persona")
    _assert(public_state["initial_block_counts"]["faq"] == 2, "session stores initial block counts")

    expanded_entries = [
        _entry("briefing", "briefing-base"),
        _entry("campaign", "campanha-base"),
        _entry("audience", "publico-1"),
        _entry("audience", "publico-2"),
        *[_entry("product", f"produto-{idx}") for idx in range(1, 5)],
        *[_entry("copy", f"copy-{idx}") for idx in range(1, 7)],
        *[_entry("faq", f"faq-{idx}") for idx in range(1, 9)],
        _entry("rule", "regra-base"),
    ]
    update = svc.update_session_plan(sid, _plan(expanded_entries), source="kb-intake.sidebar", last_change="teste plano vivo")
    _assert(update.get("ok") is True, "patch plan updates session")
    _assert(update.get("plan_hash"), "patch returns canonical plan hash")
    _assert(update.get("plan_state", {}).get("plan_hash") == update.get("plan_hash"), "plan_state carries same hash")
    _assert(update["current_block_counts"]["audience"] == 2, "current counts audience=2")
    _assert(update["current_block_counts"]["product"] == 4, "current counts product=4")
    _assert(update["current_block_counts"]["faq"] == 8, "current counts faq=8")

    restored = svc.get_session(sid) or {}
    restored_state = svc._session_public_state(restored)  # type: ignore[attr-defined]
    _assert((restored_state["knowledge_plan"] or {}).get("entries"), "get session can restore current plan")
    _assert(restored_state["plan_hash"] == update["plan_hash"], "reload state preserves current plan hash")
    _assert(restored_state["current_block_counts"]["faq"] == 8, "reload state preserves current faq count")

    short_plan = _plan([
        _entry("briefing", "briefing-base"),
        _entry("campaign", "campanha-base"),
        _entry("audience", "publico-1"),
        _entry("audience", "publico-2"),
        *[_entry("product", f"produto-{idx}") for idx in range(1, 5)],
        *[_entry("copy", f"copy-{idx}") for idx in range(1, 7)],
        _entry("faq", "faq-1"),
        _entry("faq", "faq-2"),
        _entry("rule", "regra-base"),
    ])
    rejected = svc.save(sid, "", short_plan)
    _assert("Plan mismatch: save payload is not the current normalized plan." == rejected.get("error"), "save blocks mismatched final plan hash")

    counts = svc.count_blocks_by_type(expanded_entries)
    _assert(counts["faq"] == 8 and counts["copy"] == 6, "shared block counter counts expanded plan")
    print("PASS integration_criar_live_plan_state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

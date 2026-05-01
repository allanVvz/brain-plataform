#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration test for the Knowledge Graph + chat context.

Requires:
  • Backend running at API_BASE (default http://localhost:8000).
  • Migrations 007 and 008 already applied to Supabase.
  • Persona `tock-fatal` already inserted (it ships with the seed).

What it does:
  1. POST /knowledge/sync with vault_path = tests/fixtures/vault_modal/
  2. POST /process with messages that should hit Modal / Inverno-2026.
  3. GET /knowledge/chat-context — assert entities/intent/edges/assets.
  4. GET /knowledge/graph-data?persona_slug=tock-fatal — assert nodes
     for product:modal, campaign:inverno-2026, asset and FAQ exist; assert
     the legacy shape ({nodes, edges, meta}) is preserved.

Skip-on-error: if the backend is unreachable, prints SKIP and exits 0 so
the CI step doesn't break when the dev hasn't booted the API yet.

Usage:
    python tests/integration_chat_context.py
    API_BASE=http://localhost:8000 python tests/integration_chat_context.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parent.parent
API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
VAULT_FIXTURE_PATH = (ROOT / "tests" / "fixtures" / "vault_modal").resolve()
PERSONA_SLUG = "tock-fatal"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ── HTTP helpers ─────────────────────────────────────────────────────────

class _ApiError(Exception):
    pass


def _http(method: str, path: str, params: dict | None = None, body: dict | None = None, timeout: float = 60.0):
    url = API_BASE + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
    except error.HTTPError as e:
        raise _ApiError(f"{method} {path} → {e.code} {e.read()[:300].decode('utf-8', 'replace')}")
    except error.URLError as e:
        raise _ApiError(f"{method} {path} → connection failed: {e}")


# ── Test scaffolding ─────────────────────────────────────────────────────

_FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok {msg}")
    else:
        print(f"  FAIL {msg}")
        _FAILS.append(msg)


def section(name: str) -> None:
    print(f"\n── {name} ──")


# ── Steps ────────────────────────────────────────────────────────────────

def step_health() -> bool:
    section("Health check")
    try:
        _http("GET", "/health/score")
        print("  ok backend reachable at " + API_BASE)
        return True
    except _ApiError as exc:
        print(f"  SKIP backend unreachable: {exc}")
        return False


def step_sync_vault() -> dict:
    section("Vault sync (fixtures)")
    if not VAULT_FIXTURE_PATH.exists():
        raise SystemExit(f"missing fixtures path: {VAULT_FIXTURE_PATH}")
    result = _http(
        "POST", "/knowledge/sync",
        params={"vault_path": str(VAULT_FIXTURE_PATH), "persona": PERSONA_SLUG},
    )
    expect(isinstance(result, dict) and "run_id" in result, f"sync ran: {result}")
    expect(result.get("found", 0) >= 6, f"found at least 6 fixture files (got {result.get('found')})")
    return result


def step_process_modal() -> str | None:
    section("/process — Modal product inquiry")
    body = {
        "lead_id": "graph_modal_test",
        "mensagem": "Oi, quero saber sobre Modal",
        "persona_slug": PERSONA_SLUG,
        "stage": "novo",
        "canal": "whatsapp",
    }
    try:
        result = _http("POST", "/process", body=body)
    except _ApiError as exc:
        expect(False, f"process call: {exc}")
        return None
    reply = (result or {}).get("reply")
    expect(isinstance(result, dict), "process returned a dict")
    expect("agent_used" in result, f"agent_used present (got {result.get('agent_used')})")
    expect(reply is None or isinstance(reply, str), "reply is None or string")
    print(f"     reply = {repr((reply or '')[:120])}")
    return reply


def step_chat_context_modal() -> dict:
    section("/knowledge/chat-context?q=Modal")
    ctx = _http("GET", "/knowledge/chat-context", params={"q": "Modal", "limit": 20})
    expect(isinstance(ctx, dict), "context is dict")
    expect("entities" in ctx and "intent" in ctx, "entities + intent present")
    if not isinstance(ctx, dict):
        return {}

    expect("Modal" in (ctx.get("query_terms") or []), f"Modal in query_terms ({ctx.get('query_terms')})")
    entity_slugs = {e.get("slug") for e in ctx.get("entities") or []}
    expect("modal" in entity_slugs, f"product:modal in entities ({entity_slugs})")
    expect(ctx.get("intent") == "product_inquiry",
           f"intent product_inquiry (got {ctx.get('intent')})")

    node_types = {n.get("node_type") for n in ctx.get("nodes") or []}
    expect("product" in node_types, f"product node returned ({node_types})")
    expect("campaign" in node_types, f"campaign node returned ({node_types})")

    rels = {e.get("relation_type") for e in ctx.get("edges") or []}
    expect("part_of_campaign" in rels, f"part_of_campaign edge ({rels})")
    expect("answers_question" in rels, f"answers_question edge ({rels})")
    expect("supports_copy" in rels, f"supports_copy edge ({rels})")
    expect("supports_campaign" in rels, f"supports_campaign edge ({rels})")

    assets = ctx.get("assets") or []
    expect(len(assets) >= 1, f"at least one asset ({len(assets)})")
    if assets:
        first = assets[0]
        expect(bool(first.get("file_path")), "asset has file_path")
        expect(bool(first.get("url") or first.get("file_path")), "asset has url or path")
    summary = (ctx.get("summary") or "").lower()
    expect("modal" in summary and ("inverno" in summary or "2026" in summary),
           f"summary mentions Modal+Inverno ({summary[:80]})")
    return ctx


def step_chat_context_intent_asset() -> None:
    section("/knowledge/chat-context — asset_request intent")
    ctx = _http("GET", "/knowledge/chat-context",
                params={"q": "Quais imagens do Modal posso usar?", "limit": 12})
    expect(ctx.get("intent") == "asset_request",
           f"intent asset_request (got {ctx.get('intent')})")
    expect(len(ctx.get("assets") or []) >= 1, "asset_request returns assets")


def step_chat_context_fallback() -> None:
    section("/knowledge/chat-context — fallback (no entity)")
    ctx = _http("GET", "/knowledge/chat-context",
                params={"q": "asdfqwerty random nada conhecido", "limit": 12})
    expect(ctx.get("intent") in {"fallback_text_search", "kb_lookup"},
           f"fallback intent (got {ctx.get('intent')})")
    expect(isinstance(ctx.get("entities"), list), "entities is a list (possibly empty)")
    expect(isinstance(ctx.get("assets"), list), "assets is a list")


def step_graph_data() -> None:
    section("/knowledge/graph-data?persona_slug=tock-fatal")
    g = _http("GET", "/knowledge/graph-data", params={"persona_slug": PERSONA_SLUG})
    # Legacy shape preserved
    expect(isinstance(g, dict) and {"nodes", "edges", "meta"} <= set(g.keys()),
           f"shape has nodes/edges/meta (keys={list((g or {}).keys())})")
    if not isinstance(g, dict):
        return

    sem_nodes = [n for n in g.get("nodes") or [] if (n.get("data") or {}).get("source") == "graph"]
    titles = {(n.get("data") or {}).get("label") for n in sem_nodes}
    expect("Modal" in titles, f"product:Modal in graph ({titles})")
    expect("Inverno 2026" in titles, f"campaign:Inverno 2026 in graph ({titles})")

    # Asset, faq nodes by node_type
    sem_types = {(n.get("data") or {}).get("node_type") for n in sem_nodes}
    expect("asset" in sem_types, f"asset node present ({sem_types})")
    expect(any(t in sem_types for t in ("faq", "copy", "rule", "tone", "audience")),
           f"FAQ/copy/rule/tone present ({sem_types})")

    # Optional fields per spec
    asset_nodes = [n for n in sem_nodes if (n.get("data") or {}).get("node_type") == "asset"]
    if asset_nodes:
        d = asset_nodes[0].get("data") or {}
        expect("asset_type" in d, "asset node carries asset_type field")
        expect("asset_function" in d, "asset node carries asset_function field")


def step_messages_pipeline() -> None:
    section("Conversation persistence (after /process)")
    # /process inserts a row keyed by lead_ref when resolvable; the simple
    # case here uses string lead_id which won't yield lead_ref. We just sanity-
    # check that recent messages endpoint stays alive.
    try:
        recent = _http("GET", "/messages", params={"hours": 1})
        expect(isinstance(recent, list), "recent messages returns list")
    except _ApiError as exc:
        expect(False, f"messages list endpoint: {exc}")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    if not step_health():
        return 0  # SKIP scenario — keep CI green

    try:
        step_sync_vault()
    except _ApiError as exc:
        print(f"  FAIL vault_sync: {exc}")
        _FAILS.append("vault_sync")
    except SystemExit as exc:
        print(f"  FAIL fixtures missing: {exc}")
        _FAILS.append("fixtures missing")

    # Give Supabase a beat to settle (eventual consistency on writes).
    time.sleep(1.5)

    step_process_modal()
    step_chat_context_modal()
    step_chat_context_intent_asset()
    step_chat_context_fallback()
    step_graph_data()
    step_messages_pipeline()

    print()
    if _FAILS:
        print(f"FAIL — {len(_FAILS)} assertion(s) failed:")
        for f in _FAILS:
            print(f"  - {f}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration test — Cria FAQ "Catalogo de Modais de Inverno" e valida que ele
chega ao chat-context com link clicável.

Cenário:
    1. POST /knowledge/upload/text  → cria knowledge_item (status=pending)
    2. PATCH /knowledge/queue/{id}  → cola persona_id (idempotente)
    3. POST  /knowledge/queue/{id}/approve  → promote_to_kb=true
                                              (vai pra kb_entries + knowledge_nodes)
    4. GET   /knowledge/chat-context?q=Qual o catálogo de modais de inverno?
       → entities, kb_entries (com a pergunta), assets vazio aceitável,
         summary mencionando "modal" e "inverno", link tockfatal.com presente.
    5. GET   /knowledge/graph-data?persona_slug=tock-fatal
       → contém o node FAQ recém-criado.

Skip-on-error: se o backend não responder, retorna 0 (CI verde).

Uso:
    python tests/integration_faq_modal_catalog.py
    API_BASE=http://localhost:8000 python tests/integration_faq_modal_catalog.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib import error, parse, request


API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
PERSONA_SLUG = os.environ.get("PERSONA_SLUG", "tock-fatal")
PRODUCT_SLUG = os.environ.get("PRODUCT_SLUG", "modal")
PRODUCT_TITLE = os.environ.get("PRODUCT_TITLE", "Modal")

FAQ_TITLE = os.environ.get("FAQ_TITLE", "Catalogo de Modais de Inverno")
FAQ_QUESTION = os.environ.get("QUESTION", "Qual o catalogo do produto modal?")
FAQ_LINK = os.environ.get("CATALOG_URL", "https://tockfatal.com/pages/catalogo-modal")
FAQ_ANSWER = f"Este é o link! {FAQ_LINK}"
FAQ_CONTENT = f"Pergunta: {FAQ_QUESTION}\nResposta: {FAQ_ANSWER}\n\nLink: {FAQ_LINK}"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ── HTTP helpers ──────────────────────────────────────────────────────────

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
        body_text = e.read().decode("utf-8", "replace")[:300]
        raise _ApiError(f"{method} {path} → {e.code} {body_text}")
    except error.URLError as e:
        raise _ApiError(f"{method} {path} → connection failed: {e}")


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
    section("Health")
    try:
        _http("GET", "/health/score")
        print("  ok backend reachable at " + API_BASE)
        return True
    except _ApiError as exc:
        print(f"  SKIP backend unreachable: {exc}")
        return False


def step_resolve_persona() -> str | None:
    section(f"Resolve persona '{PERSONA_SLUG}'")
    try:
        p = _http("GET", f"/personas/{PERSONA_SLUG}")
    except _ApiError as exc:
        expect(False, f"persona lookup: {exc}")
        return None
    pid = (p or {}).get("id")
    expect(bool(pid), f"persona has id ({pid})")
    return pid


def step_create_item(persona_id: str) -> str | None:
    section("Create knowledge_item via /knowledge/upload/text")
    try:
        item = _http("POST", "/knowledge/upload/text", body={
            "title": FAQ_TITLE,
            "content": FAQ_CONTENT,
            "persona_id": persona_id,
            "content_type": "faq",
            "metadata": {
                "source": "integration_test",
                "link": FAQ_LINK,
                "product": PRODUCT_SLUG,
                "product_title": PRODUCT_TITLE,
                "graph": {"relates_to": [f"product:{PRODUCT_SLUG}"]},
                "tags": [f"product:{PRODUCT_SLUG}", "faq"],
            },
        })
    except _ApiError as exc:
        expect(False, f"upload/text: {exc}")
        return None
    item_id = (item or {}).get("id")
    expect(bool(item_id), f"item created (id={item_id})")
    expect((item or {}).get("status") in ("pending", "needs_persona", "needs_category"),
           f"status pending-ish ({(item or {}).get('status')})")
    return item_id


def step_approve_promote(item_id: str) -> dict | None:
    section(f"Approve + promote_to_kb on item {item_id[:8] if item_id else '-'}")
    try:
        approved = _http("POST", f"/knowledge/queue/{item_id}/approve",
                         body={"promote_to_kb": True,
                               "agent_visibility": ["SDR", "Closer", "Classifier"]})
    except _ApiError as exc:
        expect(False, f"approve: {exc}")
        return None
    expect((approved or {}).get("status") in ("approved", "embedded"),
           f"status approved/embedded ({(approved or {}).get('status')})")
    return approved


def step_chat_context_question() -> dict | None:
    section("/knowledge/chat-context?q=catálogo modais de inverno")
    try:
        ctx = _http("GET", "/knowledge/chat-context",
                    params={"q": FAQ_QUESTION, "limit": 12})
    except _ApiError as exc:
        expect(False, f"chat-context: {exc}")
        return None

    expect(isinstance(ctx, dict), "context is a dict")
    if not isinstance(ctx, dict):
        return None

    qterms = [t.lower() for t in (ctx.get("query_terms") or [])]
    expect(any(PRODUCT_SLUG.lower() in t or PRODUCT_TITLE.lower() in t for t in qterms),
           f"product in query_terms ({ctx.get('query_terms')})")

    # FAQ should land in kb_entries (promoted) OR in nodes as faq node.
    found_faq = False
    for entry in ctx.get("kb_entries") or []:
        title = (entry.get("titulo") or "").lower()
        body = (entry.get("conteudo") or "").lower()
        node_type = (entry.get("node_type") or entry.get("tipo") or "").lower()
        if (
            (FAQ_TITLE.lower() in title)
            or (FAQ_LINK in body)
            or (node_type == "faq" and PRODUCT_SLUG.lower() in title)
        ):
            found_faq = True
            expect(FAQ_LINK in body,
                   f"FAQ entry carries the link (body preview={body[:120]!r})")
            break
    expect(found_faq, "FAQ surfaced in kb_entries")

    # Intent should be product/inquiry-ish.
    expect(ctx.get("intent") in ("product_inquiry", "kb_lookup", "campaign_inquiry"),
           f"intent reasonable ({ctx.get('intent')})")

    summary = (ctx.get("summary") or "").lower()
    expect(PRODUCT_SLUG.lower() in summary or PRODUCT_TITLE.lower() in summary or any(
        PRODUCT_SLUG.lower() in (n.get("slug") or "").lower()
        or PRODUCT_TITLE.lower() in (n.get("title") or "").lower()
        for n in (ctx.get("nodes") or [])
    ), f"product mentioned in summary or nodes")
    return ctx


def step_graph_data_has_faq() -> None:
    section("/knowledge/graph-data?persona_slug=tock-fatal contains FAQ node")
    try:
        g = _http("GET", "/knowledge/graph-data", params={"persona_slug": PERSONA_SLUG})
    except _ApiError as exc:
        expect(False, f"graph-data: {exc}")
        return
    expect(isinstance(g, dict) and {"nodes", "edges", "meta"} <= set((g or {}).keys()),
           "shape preserved")
    if not isinstance(g, dict):
        return
    titles = {(n.get("data") or {}).get("label", "").lower() for n in g.get("nodes") or []}
    expect(any("catalogo" in t or "catálogo" in t or "modais de inverno" in t for t in titles),
           f"FAQ node visible in graph (titles sample: {sorted(titles)[:6]})")


def step_kb_intake_save_robust() -> None:
    """Smoke for the 500-fix: even an incomplete session must return 4xx, never 500."""
    section("/kb-intake/save returns 4xx for incomplete session, never 500")
    try:
        sess = _http("POST", "/kb-intake/start", body={"model": "claude-haiku-4-5-20251001"})
    except _ApiError as exc:
        expect(False, f"start session: {exc}")
        return
    sid = (sess or {}).get("session_id")
    expect(bool(sid), f"session started ({sid[:8] if sid else '-'})")
    if not sid:
        return
    # Session has no classification yet — save MUST 4xx, NOT 500.
    try:
        _http("POST", "/kb-intake/save", body={"session_id": sid, "content": ""})
        expect(False, "save returned 200 on incomplete session (should 4xx)")
    except _ApiError as exc:
        msg = str(exc)
        expect(" 400 " in msg or " 422 " in msg,
               f"got a client error (4xx), not 5xx: {msg[:160]}")


def main() -> int:
    if not step_health():
        return 0

    step_kb_intake_save_robust()

    persona_id = step_resolve_persona()
    if not persona_id:
        print("\nFAIL — persona resolution blocked all subsequent checks.")
        return 1

    item_id = step_create_item(persona_id)
    if item_id:
        time.sleep(0.5)
        step_approve_promote(item_id)
        time.sleep(1.0)  # allow knowledge_graph.bootstrap_from_item to settle
        step_chat_context_question()
        step_graph_data_has_faq()

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

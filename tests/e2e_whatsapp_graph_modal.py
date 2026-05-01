#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E test — WhatsApp Web + Sofia bot, Knowledge Graph validation.

Mirrors `tests/e2e_whatsapp_web_sofia.py` but the message and the validation
are tied to the Modal product / Inverno 2026 campaign, so we exercise the
full pipeline:

    user → WhatsApp Web → Sofia → n8n → /process → reply
                                    └→ /messages persists
                                    └→ /knowledge/chat-context surfaces
                                       Modal + Inverno 2026 + assets

Validation differs from the original Sofia smoke:
    - reply must mention Modal / inverno
    - chat-context endpoint must return product:modal entity + assets

Opt-in: not run automatically. Requires manual QR scan on first use.
Persistent profile lives in `.test-browser-profile/whatsapp-graph-modal/`.

Usage:
    python tests/e2e_whatsapp_graph_modal.py
    BOT_NAME=Sofia WA_TEST_CHAT_NAME=Sofia python tests/e2e_whatsapp_graph_modal.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "bot_contact_map.json"
PROFILE_DIR = ROOT / ".test-browser-profile" / "whatsapp-graph-modal"
ARTIFACTS_DIR = ROOT / "test-artifacts" / "wa-graph-modal"
API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")

DEFAULT_BOT = "Sofia"
DEFAULT_TEST_MESSAGE = (
    "teste graph modal {ts} - oi sofia, quero saber sobre modal da campanha "
    "inverno 2026. tem imagens ou detalhes?"
)
WAIT_REPLY_SECONDS = 90
QR_TIMEOUT_SECONDS = 300
WHATSAPP_URL = "https://web.whatsapp.com"

TECHNICAL_ERROR_MARKERS = [
    "undefined", "null", "traceback", "parser failed", "exception",
    "erro técnico", "internal server error", "stacktrace",
]
GRAPH_KEYWORDS = ["modal", "inverno", "2026", "campanha", "tecido"]

APP_SHELL_SELECTOR = "div#pane-side, div[id='pane-side'], div[data-list-scroll-container='true']"
SEARCH_SELECTORS = [
    "div[contenteditable='true'][aria-label*='Pesquisar' i]",
    "div[contenteditable='true'][aria-label*='Search' i]",
    "div[role='textbox'][contenteditable='true'][aria-label*='Pesquisar' i]",
    "div[role='textbox'][contenteditable='true'][aria-label*='Search' i]",
    "div[contenteditable='true'][data-tab='3']",
]
INPUT_SELECTORS = [
    "div[contenteditable='true'][aria-label*='Mensagem' i]",
    "div[contenteditable='true'][aria-label*='Message' i]",
    "footer div[contenteditable='true'][role='textbox']",
    "footer div[contenteditable='true']",
    "div[contenteditable='true'][data-tab='10']",
]
QR_SELECTOR = "canvas[aria-label*='QR' i], canvas[aria-label*='Scan' i], canvas[aria-label*='scan' i]"


# ── Helpers ───────────────────────────────────────────────────────────────

def _load_config(bot_name: str) -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("bots", {}).get(bot_name, {})
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"WARN  config load: {exc}", file=sys.stderr)
        return {}


def _http_get_json(path: str, params: dict | None = None) -> dict | list | None:
    """Best-effort GET helper. Returns parsed JSON or None on failure."""
    url = API_BASE + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    try:
        with request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except (error.URLError, error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"WARN  backend lookup failed ({path}): {exc}", file=sys.stderr)
        return None


def _validate_reply(sent: str, received: str | None) -> tuple[bool, str, dict]:
    """Reply is OK iff non-empty, different from sent, no tech error markers,
    and mentions Modal/inverno/2026/campanha (graph-relevant terms)."""
    out = {"has_reply": False, "has_graph_keyword": False, "has_technical_error": False}
    if not received or not received.strip():
        return False, "resposta vazia", out
    out["has_reply"] = True
    received = received.strip()
    if received == sent.strip():
        return False, "resposta igual à enviada", out
    lower = received.lower()
    for marker in TECHNICAL_ERROR_MARKERS:
        if marker in lower:
            out["has_technical_error"] = True
            return False, f"erro técnico: {marker}", out
    out["has_graph_keyword"] = any(k in lower for k in GRAPH_KEYWORDS)
    if not out["has_graph_keyword"]:
        return False, "resposta sem termos do grafo (modal/inverno/2026/...)", out
    return True, "ok", out


def _validate_chat_context(ctx: dict | None) -> tuple[bool, str, dict]:
    out = {
        "has_entities": False, "has_modal_entity": False,
        "has_campaign_entity": False, "has_asset": False,
        "intent": None,
    }
    if not isinstance(ctx, dict):
        return False, "chat-context vazio", out
    out["intent"] = ctx.get("intent")
    entities = ctx.get("entities") or []
    out["has_entities"] = bool(entities)
    slugs = {e.get("slug") for e in entities}
    out["has_modal_entity"] = "modal" in slugs
    out["has_campaign_entity"] = "inverno-2026" in slugs
    out["has_asset"] = bool(ctx.get("assets") or [])
    if not (out["has_modal_entity"] and out["has_campaign_entity"]):
        return False, "chat-context não retornou Modal+Inverno-2026", out
    if not out["has_asset"]:
        return False, "chat-context não retornou assets", out
    return True, "ok", out


def _save_evidence(payload: dict, before_png: bytes | None, after_png: bytes | None, conversation: str) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / "result.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if before_png:
        (ARTIFACTS_DIR / "screenshot-before.png").write_bytes(before_png)
    if after_png:
        (ARTIFACTS_DIR / "screenshot-after.png").write_bytes(after_png)
    if conversation:
        (ARTIFACTS_DIR / "conversation.txt").write_text(conversation, encoding="utf-8")


def _print_pass(bot: str, contact: str, latency_ms: int) -> None:
    print(f"E2E GRAPH PASS bot={bot} contact={contact} latency={latency_ms}ms")


def _print_fail(bot: str, contact: str, reason: str) -> None:
    safe = reason.encode("ascii", "replace").decode("ascii")
    print(f'E2E GRAPH FAIL bot={bot} contact={contact} reason="{safe}"')


def _find_first_visible(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                return loc
        except Exception:
            continue
    return None


# ── Run ───────────────────────────────────────────────────────────────────

def run(bot_name: str, contact_name: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "SKIP  playwright não instalado. "
            "Execute: pip install playwright && python -m playwright install chromium"
        )
        return True

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    sent_message = DEFAULT_TEST_MESSAGE.format(ts=int(time.time()))

    payload_skel: dict = {
        "ok": False,
        "bot_name": bot_name,
        "whatsapp_contact_name": contact_name,
        "mode": "whatsapp_web_e2e_graph_modal",
        "sent_message": sent_message,
        "received_reply": None,
        "latency_ms": 0,
        "validation": {},
        "chat_context": None,
        "messages_lookup": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with sync_playwright() as p:
        try:
            ctx_browser = p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            payload_skel["error"] = f"launch failed: {e}"
            _save_evidence(payload_skel, None, None, "")
            _print_fail(bot_name, contact_name, f"launch failed: {str(e)[:80]}")
            return False

        page = ctx_browser.pages[0] if ctx_browser.pages else ctx_browser.new_page()
        before_png: bytes | None = None
        after_png: bytes | None = None
        conversation = ""

        try:
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60000)
            print(f"Aguardando login no WhatsApp Web... (até {QR_TIMEOUT_SECONDS}s se QR)")
            try:
                page.wait_for_selector(QR_SELECTOR + ", " + ", ".join(SEARCH_SELECTORS), timeout=30000)
            except Exception:
                pass

            qr_visible = False
            try:
                qr_visible = page.locator(QR_SELECTOR).first.is_visible(timeout=2000)
            except Exception:
                pass

            if qr_visible:
                print("QR Code necessário. Escaneie para continuar.")
                page.wait_for_function(
                    """() => { const c = document.querySelector("canvas[aria-label*='QR' i], canvas[aria-label*='Scan' i], canvas[aria-label*='scan' i]"); return !c; }""",
                    timeout=QR_TIMEOUT_SECONDS * 1000,
                )

            page.wait_for_selector(APP_SHELL_SELECTOR, timeout=60000)
            print("Login OK.")
            time.sleep(2)
            before_png = page.screenshot()

            clicked = False
            try:
                direct = page.locator(f"#pane-side span[title='{contact_name}']").first
                if direct.is_visible(timeout=3000):
                    direct.click()
                    clicked = True
                    print(f"Contato '{contact_name}' clicado direto.")
            except Exception:
                pass

            if not clicked:
                print(f"Buscando '{contact_name}'...")
                search_box = _find_first_visible(page, SEARCH_SELECTORS)
                if not search_box:
                    raise RuntimeError("caixa de busca não encontrada")
                search_box.click()
                try:
                    search_box.fill("")
                except Exception:
                    pass
                search_box.type(contact_name, delay=50)
                time.sleep(2)
                contact_locator = page.locator(f"span[title='{contact_name}']").first
                contact_locator.click(timeout=8000)

            time.sleep(2)
            msg_input = _find_first_visible(page, INPUT_SELECTORS)
            if not msg_input:
                raise RuntimeError(f"input não apareceu para '{contact_name}'")

            incoming_selector = (
                "div.message-in span.selectable-text, "
                "div.message-in span._ao3e, "
                "div[data-id^='false_'] span.selectable-text, "
                "div[data-id^='false_'] span.copyable-text"
            )

            def _read_incoming():
                try:
                    return [t.strip() for t in page.locator(incoming_selector).all_text_contents() if t.strip()]
                except Exception:
                    return []

            baseline = _read_incoming()
            baseline_count = len(baseline)
            baseline_last = baseline[-1] if baseline else ""

            msg_input.click()
            msg_input.type(sent_message, delay=15)
            page.keyboard.press("Enter")

            t_send = time.monotonic()
            received: str | None = None
            while (time.monotonic() - t_send) < WAIT_REPLY_SECONDS:
                current = _read_incoming()
                if len(current) > baseline_count or (current and current[-1] != baseline_last):
                    candidate = current[-1]
                    if candidate and candidate != sent_message.strip():
                        received = candidate
                        break
                time.sleep(1)

            after_png = page.screenshot()
            latency_ms = int((time.monotonic() - t_send) * 1000)

            try:
                msgs = page.locator(
                    "div.message-in span.selectable-text, div.message-out span.selectable-text"
                ).all_text_contents()
                conversation = "\n".join(m.strip() for m in msgs if m.strip())
            except Exception:
                conversation = ""

            ok_reply, reply_reason, reply_validation = _validate_reply(sent_message, received)

            # Backend-side validation: messages list + chat-context
            recent = _http_get_json("/messages/conversations", params={"hours": 1})
            payload_skel["messages_lookup"] = {
                "found_in_recent": bool(
                    recent and any(("modal" in (c.get("last_message") or "").lower())
                                   for c in (recent or []))
                ),
                "count": len(recent or []),
            }

            ctx_response = _http_get_json("/knowledge/chat-context",
                                          params={"q": "Modal Inverno 2026", "limit": 12})
            payload_skel["chat_context"] = ctx_response
            ok_ctx, ctx_reason, ctx_validation = _validate_chat_context(ctx_response)

            payload_skel.update({
                "ok": bool(ok_reply and ok_ctx),
                "received_reply": received,
                "latency_ms": latency_ms,
                "validation": {
                    "reply": reply_validation,
                    "chat_context": ctx_validation,
                },
                "fail_reason": None if (ok_reply and ok_ctx) else (
                    reply_reason if not ok_reply else ctx_reason
                ),
            })
            _save_evidence(payload_skel, before_png, after_png, conversation)

            try:
                ctx_browser.close()
            except Exception:
                pass

            if payload_skel["ok"]:
                _print_pass(bot_name, contact_name, latency_ms)
                return True
            _print_fail(bot_name, contact_name, payload_skel["fail_reason"])
            return False

        except Exception as e:
            try:
                err_png = page.screenshot()
            except Exception:
                err_png = None
            payload_skel["error"] = str(e)
            _save_evidence(payload_skel, before_png, err_png, conversation)
            try:
                ctx_browser.close()
            except Exception:
                pass
            _print_fail(bot_name, contact_name, f"exception: {str(e)[:80]}")
            return False


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E WhatsApp Web — Knowledge Graph (Modal)")
    parser.add_argument("--bot", default=os.environ.get("BOT_NAME", DEFAULT_BOT))
    parser.add_argument("--contact", default=os.environ.get("WA_TEST_CHAT_NAME"))
    args = parser.parse_args()

    bot = args.bot
    cfg = _load_config(bot)
    contact = args.contact or cfg.get("whatsapp_contact_name") or bot

    ok = run(bot, contact)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

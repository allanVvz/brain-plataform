#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E WhatsApp — fluxo "FAQ com link de catálogo" (parametrizável).

Cobre o caminho completo:

  1. Setup: cria a FAQ via /knowledge/upload/text + /knowledge/queue/{id}/approve
     (idempotente; dispara knowledge_graph.bootstrap_from_item).
  2. WhatsApp Web: abre, busca o contato do bot, envia a pergunta.
  3. Lê a resposta do bot (scraping).
  4. Valida o trio "mensagem ↔ lead ↔ conhecimento":
       - reply contém o catalog_url (a própria URL injetada).
       - /messages/conversations expõe a conversa recente; dela tira o lead_ref.
       - /messages/by-ref/{lead_ref} contém a outbound com o catalog_url.
       - /knowledge/chat-context?lead_ref=...&q=... devolve product/faq nodes
         pelo slug parametrizado, kb_entry com o catalog_url no body.
       - Imprime a URL do dashboard `/messages` pra inspeção visual da
         sidebar de conhecimento (Produtos, FAQs, Campanhas, etc.).

Nada hardcoded de cliente/produto: tudo vem de CLI args ou env. Defaults rodam
o cenário Modal/Tock Fatal pra preservar o teste atual; basta passar
`--product-slug`/`--catalog-url`/`--question` pra rodar com outro produto.

Uso:
    python tests/e2e_faq_whatsapp_modal_catalog.py
    python tests/e2e_faq_whatsapp_modal_catalog.py \\
        --product-slug tricot --product-title "Tricot Premium" \\
        --catalog-url https://acme.com/catalogo-tricot \\
        --question "Onde acho o catálogo de tricot?" \\
        --bot Sofia --persona-slug tock-fatal
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
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
PROFILE_DIR = Path(os.environ.get(
    "WA_PROFILE_DIR",
    str(ROOT / ".test-browser-profile" / "whatsapp-faq-catalogo"),
))
ARTIFACTS_DIR = ROOT / "test-artifacts" / "wa-faq-catalogo"
API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_BASE = os.environ.get("DASHBOARD_BASE", "http://localhost:3000").rstrip("/")
PW_CHANNEL = os.environ.get("PW_CHANNEL", "").strip() or None

DEFAULT_BOT = "Sofia"
WAIT_REPLY_SECONDS = 90
QR_TIMEOUT_SECONDS = 300
APP_READY_TIMEOUT_SECONDS = 180
WHATSAPP_URL = "https://web.whatsapp.com"

TECHNICAL_ERROR_MARKERS = [
    "undefined", "null", "traceback", "parser failed", "exception",
    "erro técnico", "internal server error", "stacktrace",
]

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


# ── Scenario (parametrizável) ────────────────────────────────────────────

@dataclass
class Scenario:
    """Tudo que define o cenário do teste vive aqui — zero hardcode na
    lógica de validação. Defaults reproduzem o teste Modal/Tock Fatal."""
    bot_name: str = DEFAULT_BOT
    persona_slug: str = "tock-fatal"
    product_slug: str = "modal"
    product_title: str = "Modal"
    catalog_url: str = "https://tockfatal.com/pages/catalogo-modal"
    faq_title: str = "Catalogo de Modais de Inverno"
    question: str = "Qual o catalogo do produto modal?"
    contact_name: str | None = None  # resolved from bot_contact_map.json if None

    @property
    def faq_content(self) -> str:
        return (
            f"Pergunta: {self.question}\n"
            f"Resposta: Este é o link! {self.catalog_url}\n\n"
            f"Link: {self.catalog_url}"
        )


# ── HTTP helpers ──────────────────────────────────────────────────────────

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
    with request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw


def _http_safe(method: str, path: str, **kw):
    try:
        return _http(method, path, **kw)
    except (error.URLError, error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"WARN  {method} {path}: {exc}", file=sys.stderr)
        return None


def _load_bot_contact(bot_name: str) -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return (json.load(f).get("bots", {}) or {}).get(bot_name, {})
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"WARN  config load: {exc}", file=sys.stderr)
        return {}


# ── Setup: ensure FAQ exists ──────────────────────────────────────────────

def setup_faq(s: Scenario) -> dict:
    print(f"→ Setup: garantindo FAQ no banco (persona={s.persona_slug}, product={s.product_slug})")
    persona = _http_safe("GET", f"/personas/{s.persona_slug}")
    if not isinstance(persona, dict) or not persona.get("id"):
        print(f"  WARN persona {s.persona_slug} não encontrada — pulando setup.")
        return {"ok": False, "skipped": True, "reason": "persona missing"}
    persona_id = persona["id"]

    item = _http_safe("POST", "/knowledge/upload/text", body={
        "title": s.faq_title,
        "content": s.faq_content,
        "persona_id": persona_id,
        "content_type": "faq",
        "metadata": {
            "source": "e2e_faq_test",
            "link": s.catalog_url,
            "product": s.product_slug,
            "product_title": s.product_title,
            "graph": {"relates_to": [f"product:{s.product_slug}"]},
            "tags": [f"product:{s.product_slug}", "faq"],
        },
    })
    if not isinstance(item, dict) or not item.get("id"):
        return {"ok": False, "reason": "upload/text failed"}
    item_id = item["id"]
    print(f"  ok knowledge_item criado: {item_id}")

    approved = _http_safe("POST", f"/knowledge/queue/{item_id}/approve",
                          body={"promote_to_kb": True,
                                "agent_visibility": ["SDR", "Closer", "Classifier"]})
    if not isinstance(approved, dict):
        return {"ok": False, "item_id": item_id, "reason": "approve failed"}
    print(f"  ok approved+promoted; status={approved.get('status')}")
    return {"ok": True, "item_id": item_id, "approved_status": approved.get("status")}


# ── Validations ──────────────────────────────────────────────────────────

def validate_reply(s: Scenario, sent: str, received: str | None) -> tuple[bool, str, dict]:
    """Reply válida: não vazia, ≠ enviada, sem traceback, contém catalog_url."""
    out = {
        "has_reply": False,
        "contains_catalog_url": False,
        "has_technical_error": False,
    }
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

    # A URL injetada deve aparecer literal — é a única referência segura
    # (sem hardcode de "modal"/"catálogo"/etc).
    if s.catalog_url in received:
        out["contains_catalog_url"] = True
    if not out["contains_catalog_url"]:
        return False, "resposta não contém o catalog_url injetado", out
    return True, "ok", out


def validate_chat_context(s: Scenario, ctx: dict | None) -> tuple[bool, str, dict]:
    """Chat-context retorna o produto e o FAQ pelo slug parametrizado, e o
    kb_entry traz o catalog_url no body."""
    out = {
        "has_product_node": False,
        "has_faq_node": False,
        "kb_entry_with_url": False,
        "node_types": [],
    }
    if not isinstance(ctx, dict):
        return False, "chat-context vazio", out

    nodes = ctx.get("nodes") or []
    out["node_types"] = sorted({n.get("node_type") for n in nodes if n.get("node_type")})

    out["has_product_node"] = any(
        n.get("node_type") == "product" and n.get("slug") == s.product_slug
        for n in nodes
    )

    out["has_faq_node"] = any(n.get("node_type") == "faq" for n in nodes) or any(
        (e.get("node_type") or e.get("tipo") or "").lower() == "faq"
        for e in ctx.get("kb_entries") or []
    )

    out["kb_entry_with_url"] = any(
        s.catalog_url in (e.get("conteudo") or "")
        for e in ctx.get("kb_entries") or []
    )

    if not out["has_product_node"]:
        return False, f"nenhum product node com slug={s.product_slug}", out
    if not out["has_faq_node"]:
        return False, "nenhum nó FAQ retornado", out
    if not out["kb_entry_with_url"]:
        return False, "nenhum kb_entry contém o catalog_url", out
    return True, "ok", out


def find_lead_for_conversation(s: Scenario, hours: int = 1) -> dict | None:
    """Localiza a conversa recente que carrega o catalog_url injetado.

    Critério: last_message contém o catalog_url. Sem fallback por substring
    de produto pra evitar matches falsos."""
    convos = _http_safe("GET", "/messages/conversations", params={"hours": hours})
    if not isinstance(convos, list):
        return None
    # Match estrito: a URL injetada precisa estar na última mensagem da convo.
    for c in convos:
        last = c.get("last_message") or ""
        if s.catalog_url in last:
            ref = c.get("lead_ref")
            if ref is None:
                continue
            return {"lead_ref": ref, "nome": c.get("nome"), "last_message": last}
    return None


def validate_lead_link(s: Scenario, lead_ref: int) -> tuple[bool, str, dict]:
    """Confirma que o lead tem outbound com o catalog_url e que a sidebar
    de conhecimento (via chat-context vinculado ao lead_ref) traz o produto."""
    out: dict = {
        "messages_count": 0,
        "has_outbound_with_url": False,
        "lead_ctx": {},
        "lead_ctx_ok": False,
        "dashboard_url": f"{DASHBOARD_BASE}/messages",
    }
    msgs = _http_safe("GET", f"/messages/by-ref/{lead_ref}", params={"limit": 50})
    if not isinstance(msgs, list):
        return False, "messages/by-ref retornou vazio", out
    out["messages_count"] = len(msgs)

    for m in msgs:
        texto = (m.get("texto") or "").strip()
        sender = (m.get("sender_type") or "").lower()
        is_outbound = sender in ("assistant", "agent", "ai", "bot") or (
            (m.get("direction") or "").lower() in ("outbounding", "outbound")
        )
        if is_outbound and s.catalog_url in texto:
            out["has_outbound_with_url"] = True
            break

    ctx = _http_safe("GET", "/knowledge/chat-context",
                     params={"lead_ref": lead_ref, "q": s.question, "limit": 20})
    out["lead_ctx"] = ctx if isinstance(ctx, dict) else {}
    ok_ctx, reason, _details = validate_chat_context(s, ctx)
    out["lead_ctx_ok"] = ok_ctx
    out["lead_ctx_reason"] = reason

    if not out["has_outbound_with_url"]:
        return False, "lead não tem mensagem outbound com o catalog_url", out
    if not out["lead_ctx_ok"]:
        return False, f"chat-context(lead_ref) não casa: {reason}", out
    return True, "ok", out


# ── Evidence ─────────────────────────────────────────────────────────────

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


def _print_pass(s: Scenario, lead_ref: int | None, latency_ms: int) -> None:
    bot = s.bot_name; contact = s.contact_name or s.bot_name
    print(f"E2E FAQ PASS bot={bot} contact={contact} product={s.product_slug} "
          f"lead_ref={lead_ref} latency={latency_ms}ms")
    print(f"   dashboard → {DASHBOARD_BASE}/messages "
          f"(abra o lead {lead_ref} pra ver a sidebar de conhecimento)")


def _print_fail(s: Scenario, reason: str) -> None:
    safe = reason.encode("ascii", "replace").decode("ascii")
    contact = s.contact_name or s.bot_name
    print(f'E2E FAQ FAIL bot={s.bot_name} contact={contact} product={s.product_slug} reason="{safe}"')


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

def run(s: Scenario) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP  playwright não instalado. Execute: pip install playwright && python -m playwright install chromium")
        return True

    setup = setup_faq(s)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    contact_name = s.contact_name or _load_bot_contact(s.bot_name).get("whatsapp_contact_name") or s.bot_name
    s.contact_name = contact_name

    payload: dict = {
        "ok": False,
        "scenario": asdict(s),
        "mode": "whatsapp_web_e2e_faq_catalogo",
        "setup": setup,
        "sent_message": s.question,
        "expected_link": s.catalog_url,
        "received_reply": None,
        "latency_ms": 0,
        "validation": {},
        "lead_lookup": None,
        "chat_context_q": None,
        "lead_link_validation": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with sync_playwright() as p:
        try:
            launch_kwargs = {}
            if PW_CHANNEL:
                launch_kwargs["channel"] = PW_CHANNEL
            ctx_browser = p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                args=["--disable-blink-features=AutomationControlled"],
                **launch_kwargs,
            )
        except Exception as e:
            payload["error"] = f"launch failed: {e}"
            _save_evidence(payload, None, None, "")
            _print_fail(s, f"launch failed: {str(e)[:80]}")
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

            page.wait_for_selector(APP_SHELL_SELECTOR, timeout=APP_READY_TIMEOUT_SECONDS * 1000)
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
            msg_input.type(s.question, delay=15)
            page.keyboard.press("Enter")

            t_send = time.monotonic()
            received: str | None = None
            while (time.monotonic() - t_send) < WAIT_REPLY_SECONDS:
                current = _read_incoming()
                if len(current) > baseline_count or (current and current[-1] != baseline_last):
                    candidate = current[-1]
                    if candidate and candidate != s.question.strip():
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

            ok_reply, reply_reason, reply_validation = validate_reply(s, s.question, received)

            # Aguarda persistência no backend antes de buscar a conversa.
            time.sleep(2)
            lead_info = find_lead_for_conversation(s)
            payload["lead_lookup"] = lead_info

            ok_lead = False
            lead_reason = "lead_ref não encontrado em /messages/conversations"
            lead_validation: dict = {}
            lead_ref = lead_info.get("lead_ref") if lead_info else None
            if lead_ref is not None:
                ok_lead, lead_reason, lead_validation = validate_lead_link(s, lead_ref)
            payload["lead_link_validation"] = {
                "ok": ok_lead, "reason": lead_reason, **lead_validation,
            }

            # Q-only chat-context (independente do lead) — espelha o que a
            # sidebar mostraria pra essa pergunta.
            ctx_q = _http_safe("GET", "/knowledge/chat-context",
                               params={"q": s.question, "limit": 20})
            payload["chat_context_q"] = ctx_q
            ok_ctx_q, ctx_q_reason, ctx_q_validation = validate_chat_context(s, ctx_q)

            ok_all = bool(ok_reply and ok_ctx_q and ok_lead)
            fail_reason = None
            if not ok_reply:        fail_reason = reply_reason
            elif not ok_ctx_q:      fail_reason = f"chat-context(q): {ctx_q_reason}"
            elif not ok_lead:       fail_reason = f"lead-link: {lead_reason}"

            payload.update({
                "ok": ok_all,
                "received_reply": received,
                "latency_ms": latency_ms,
                "validation": {
                    "reply": reply_validation,
                    "chat_context_q": ctx_q_validation,
                    "lead_link": lead_validation,
                },
                "fail_reason": fail_reason,
            })
            _save_evidence(payload, before_png, after_png, conversation)

            try:
                ctx_browser.close()
            except Exception:
                pass

            if ok_all:
                _print_pass(s, lead_ref, latency_ms)
                return True
            _print_fail(s, fail_reason or "unknown")
            return False

        except Exception as e:
            try:
                err_png = page.screenshot()
            except Exception:
                err_png = None
            payload["error"] = str(e)
            _save_evidence(payload, before_png, err_png, conversation)
            try:
                ctx_browser.close()
            except Exception:
                pass
            _print_fail(s, f"exception: {str(e)[:80]}")
            return False


# ── CLI ───────────────────────────────────────────────────────────────────

def _scenario_from_args() -> Scenario:
    parser = argparse.ArgumentParser(description="E2E WhatsApp Web — FAQ + catálogo (parametrizável)")
    parser.add_argument("--bot", default=os.environ.get("BOT_NAME", DEFAULT_BOT))
    parser.add_argument("--persona-slug", default=os.environ.get("PERSONA_SLUG", "tock-fatal"))
    parser.add_argument("--product-slug", default=os.environ.get("PRODUCT_SLUG", "modal"))
    parser.add_argument("--product-title", default=os.environ.get("PRODUCT_TITLE", "Modal"))
    parser.add_argument("--catalog-url",
                        default=os.environ.get("CATALOG_URL", "https://tockfatal.com/pages/catalogo-modal"))
    parser.add_argument("--faq-title",
                        default=os.environ.get("FAQ_TITLE", "Catalogo de Modais de Inverno"))
    parser.add_argument("--question",
                        default=os.environ.get("QUESTION", "Qual o catalogo do produto modal?"))
    parser.add_argument("--contact", default=os.environ.get("WA_TEST_CHAT_NAME"))
    args = parser.parse_args()

    return Scenario(
        bot_name=args.bot,
        persona_slug=args.persona_slug,
        product_slug=args.product_slug,
        product_title=args.product_title,
        catalog_url=args.catalog_url,
        faq_title=args.faq_title,
        question=args.question,
        contact_name=args.contact,
    )


def main() -> int:
    s = _scenario_from_args()
    print(f"→ Scenario: {asdict(s)}")
    return 0 if run(s) else 1


if __name__ == "__main__":
    sys.exit(main())

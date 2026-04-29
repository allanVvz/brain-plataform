#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E test — WhatsApp Web + Sofia bot.

Diferença para o smoke interno (tests/smoke_wa_validator.py):
    smoke interno: chama /process direto, sem navegador, sem WhatsApp.
    E2E (este):    abre WhatsApp Web real, sessão persistente, procura o
                   contato Sofia, envia mensagem como cliente/validador,
                   aguarda resposta da Sofia, lê via scraping.

Visões da conversa:
    Aba de validação (este teste): cliente/validador falando com Sofia.
    Aba mensagens/leads/server:    visão interna do sistema.
    Não confundir.

Uso:
    python tests/e2e_whatsapp_web_sofia.py
    BOT_NAME=Sofia WA_TEST_CHAT_NAME=Sofia python tests/e2e_whatsapp_web_sofia.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Encoding fix p/ console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "bot_contact_map.json"
PROFILE_DIR = ROOT / ".test-browser-profile" / "whatsapp-sofia"
ARTIFACTS_DIR = ROOT / "test-artifacts" / "wa-e2e"

DEFAULT_BOT = "Sofia"
DEFAULT_TEST_MESSAGE = "teste e2e sofia {ts} - oi, queria ver produtos da loja"
WAIT_REPLY_SECONDS = 60
QR_TIMEOUT_SECONDS = 300
WHATSAPP_URL = "https://web.whatsapp.com"

TECHNICAL_ERROR_MARKERS = [
    "undefined",
    "null",
    "traceback",
    "parser failed",
    "exception",
    "erro técnico",
    "internal server error",
    "stacktrace",
]
COMMERCIAL_KEYWORDS = [
    "catálogo", "catalogo", "produto", "loja", "atacado", "varejo",
    "cidade", "cep", "quer ver", "posso te mostrar", "qual peça",
    "qual peca", "tamanho", "modelo", "kit", "preço", "preco",
    "frete", "estoque", "promoção", "promocao",
]

# Indicador de "logado" — chat list lateral. Mais estável que a search box.
APP_SHELL_SELECTOR = "div#pane-side, div[id='pane-side'], div[data-list-scroll-container='true']"

# Search box (lista de conversas). data-tab='3' foi removido em 2024+;
# usa aria-label e role="textbox" como fallback. Cobre PT/EN.
SEARCH_SELECTORS = [
    "div[contenteditable='true'][aria-label*='Pesquisar' i]",
    "div[contenteditable='true'][aria-label*='Search' i]",
    "div[role='textbox'][contenteditable='true'][aria-label*='Pesquisar' i]",
    "div[role='textbox'][contenteditable='true'][aria-label*='Search' i]",
    "div[contenteditable='true'][data-tab='3']",
]
# Message input (rodapé). data-tab='10' também removido.
INPUT_SELECTORS = [
    "div[contenteditable='true'][aria-label*='Mensagem' i]",
    "div[contenteditable='true'][aria-label*='Message' i]",
    "footer div[contenteditable='true'][role='textbox']",
    "footer div[contenteditable='true']",
    "div[contenteditable='true'][data-tab='10']",
]
QR_SELECTOR = "canvas[aria-label*='QR' i], canvas[aria-label*='Scan' i], canvas[aria-label*='scan' i]"


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


def _validate(sent: str, received: str | None) -> tuple[bool, str, dict]:
    if not received or not received.strip():
        return False, "resposta vazia", {
            "has_reply": False,
            "has_commercial_next_action": False,
            "has_technical_error": False,
        }
    received = received.strip()
    if received == sent.strip():
        return False, "resposta igual à enviada", {
            "has_reply": True,
            "has_commercial_next_action": False,
            "has_technical_error": False,
        }
    lower = received.lower()
    for marker in TECHNICAL_ERROR_MARKERS:
        if marker in lower:
            return False, f"erro técnico: {marker}", {
                "has_reply": True,
                "has_commercial_next_action": False,
                "has_technical_error": True,
            }
    has_commercial = any(kw in lower for kw in COMMERCIAL_KEYWORDS)
    if not has_commercial:
        return False, "sem próxima ação comercial", {
            "has_reply": True,
            "has_commercial_next_action": False,
            "has_technical_error": False,
        }
    return True, "ok", {
        "has_reply": True,
        "has_commercial_next_action": True,
        "has_technical_error": False,
    }


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
    print(f"E2E WA PASS bot={bot} contact={contact} latency={latency_ms}ms")


def _print_fail(bot: str, contact: str, reason: str) -> None:
    safe = reason.encode("ascii", "replace").decode("ascii")
    print(f'E2E WA FAIL bot={bot} contact={contact} reason="{safe}"')


def _find_first_visible(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                return loc
        except Exception:
            continue
    return None


def run(bot_name: str, contact_name: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "SKIP  playwright não instalado. "
            "Execute: pip install playwright && python -m playwright install chromium"
        )
        return True  # skip non-fatal

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    sent_message = DEFAULT_TEST_MESSAGE.format(ts=int(time.time()))

    payload_skel = {
        "ok": False,
        "bot_name": bot_name,
        "whatsapp_contact_name": contact_name,
        "mode": "whatsapp_web_e2e",
        "sent_message": sent_message,
        "received_reply": None,
        "latency_ms": 0,
        "validation": {
            "has_reply": False,
            "has_commercial_next_action": False,
            "has_technical_error": False,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
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

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        before_png: bytes | None = None
        after_png: bytes | None = None
        conversation = ""

        try:
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60000)

            # Detect login state (QR vs already logged in)
            print(f"Aguardando login no WhatsApp Web... (até {QR_TIMEOUT_SECONDS}s se QR)")
            try:
                page.wait_for_selector(
                    QR_SELECTOR + ", " + ", ".join(SEARCH_SELECTORS),
                    timeout=30000,
                )
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

            # Wait for app shell (chat list pane) — indicador estável de logado
            page.wait_for_selector(APP_SHELL_SELECTOR, timeout=60000)
            print("Login OK. Continuando...")
            time.sleep(2)  # deixa o DOM estabilizar

            before_png = page.screenshot()

            # Estratégia 1: clicar direto no contato se já visível na lista
            # (mais confiável que busca — evita selectors voláteis da search box)
            clicked = False
            try:
                direct = page.locator(f"#pane-side span[title='{contact_name}']").first
                if direct.is_visible(timeout=3000):
                    direct.click()
                    clicked = True
                    print(f"Contato '{contact_name}' clicado direto da lista.")
            except Exception:
                pass

            # Estratégia 2: usar busca
            if not clicked:
                print(f"Buscando '{contact_name}' via search box...")
                search_box = _find_first_visible(page, SEARCH_SELECTORS)
                if not search_box:
                    raise RuntimeError("caixa de busca não encontrada (selectors atualizados?)")

                search_box.click()
                try:
                    search_box.fill("")
                except Exception:
                    pass
                search_box.type(contact_name, delay=50)
                time.sleep(2)

                contact_locator = page.locator(f"span[title='{contact_name}']").first
                try:
                    contact_locator.click(timeout=8000)
                    clicked = True
                except Exception:
                    fallback = page.locator("div[role='listitem']").first
                    fallback.click(timeout=5000)
                    clicked = True

            time.sleep(2)

            # Validação: input de mensagem precisa ficar visível (= chat aberto).
            # WhatsApp Web mudou bastante o markup do header, então confiar
            # apenas no clique direto do contato (que veio com title='X')
            # + presença do input é mais robusto.
            msg_input = _find_first_visible(page, INPUT_SELECTORS)
            if not msg_input:
                raise RuntimeError(
                    f"caixa de mensagem não apareceu após clicar em '{contact_name}' (chat não abriu?)"
                )

            # Confirmação extra: pelo menos UMA referência ao nome no chat aberto.
            # Procura em qualquer lugar da página principal (header/drawer/etc).
            name_present = False
            try:
                name_present = page.locator(f"span[title='{contact_name}']").count() > 0
            except Exception:
                pass
            if not name_present:
                # Não é fatal: clicamos no item certo, só log.
                print(f"WARN  nome '{contact_name}' não encontrado em spans — DOM mudou, mas seguindo.")

            # CRÍTICO: capturar baseline ANTES de enviar.
            # WhatsApp Web mantém histórico — sem baseline, leríamos a
            # última mensagem antiga da Sofia e marcaríamos PASS instantâneo.
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

            # Aguardar mensagem incoming NOVA (count cresceu OU último texto mudou)
            t_send = time.monotonic()
            received = None
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

            # Capture conversation snapshot
            try:
                msgs = page.locator(
                    "div.message-in span.selectable-text, div.message-out span.selectable-text"
                ).all_text_contents()
                conversation = "\n".join(m.strip() for m in msgs if m.strip())
            except Exception:
                conversation = ""

            ok, reason, validation = _validate(sent_message, received)
            payload_skel.update({
                "ok": ok,
                "received_reply": received,
                "latency_ms": latency_ms,
                "validation": validation,
                "fail_reason": None if ok else reason,
            })
            _save_evidence(payload_skel, before_png, after_png, conversation)

            try:
                ctx.close()
            except Exception:
                pass

            if ok:
                _print_pass(bot_name, contact_name, latency_ms)
                return True
            _print_fail(bot_name, contact_name, reason)
            return False

        except Exception as e:
            try:
                err_png = page.screenshot()
            except Exception:
                err_png = None
            payload_skel["error"] = str(e)
            _save_evidence(payload_skel, before_png, err_png, conversation)
            try:
                ctx.close()
            except Exception:
                pass
            _print_fail(bot_name, contact_name, f"exception: {str(e)[:80]}")
            return False


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E WhatsApp Web — bot validation")
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

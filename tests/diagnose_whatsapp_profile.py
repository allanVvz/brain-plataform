#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose WhatsApp Web readiness for a Playwright persistent profile.

This does not send messages. It only opens web.whatsapp.com, waits for one of
the known states, writes a screenshot, and prints the detected state.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "wa-profile-diagnostics"
WHATSAPP_URL = "https://web.whatsapp.com"

APP_SHELL_SELECTOR = "div#pane-side, div[id='pane-side'], div[data-list-scroll-container='true']"
QR_SELECTOR = "canvas[aria-label*='QR' i], canvas[aria-label*='Scan' i], canvas[aria-label*='scan' i]"
SEARCH_SELECTOR = (
    "div[contenteditable='true'][aria-label*='Pesquisar' i], "
    "div[contenteditable='true'][aria-label*='Search' i], "
    "div[role='textbox'][contenteditable='true']"
)


def visible(page, selector: str) -> bool:
    try:
        return page.locator(selector).first.is_visible(timeout=500)
    except Exception:
        return False


def diagnose(profile: Path, channel: str | None, wait_seconds: int) -> dict:
    from playwright.sync_api import sync_playwright

    profile.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "profile": str(profile),
        "channel": channel or "playwright-chromium",
        "state": "unknown",
        "url": None,
        "title": None,
        "error": None,
        "screenshot": None,
    }

    with sync_playwright() as p:
        launch_kwargs = {}
        if channel:
            launch_kwargs["channel"] = channel
        ctx = p.chromium.launch_persistent_context(
            str(profile),
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
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60000)
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                if page.is_closed():
                    result["state"] = "page_closed"
                    break
                if visible(page, APP_SHELL_SELECTOR):
                    result["state"] = "ready_chat_list"
                    break
                if visible(page, QR_SELECTOR):
                    result["state"] = "qr_required"
                    break
                if visible(page, SEARCH_SELECTOR):
                    result["state"] = "ready_search_box"
                    break
                time.sleep(1)
            else:
                result["state"] = "loading_timeout"

            if not page.is_closed():
                result["url"] = page.url
                result["title"] = page.title()
                shot = ARTIFACTS_DIR / f"{profile.name}-{channel or 'chromium'}.png"
                page.screenshot(path=str(shot))
                result["screenshot"] = str(shot)
        except Exception as exc:
            result["state"] = "exception"
            result["error"] = str(exc)
            try:
                shot = ARTIFACTS_DIR / f"{profile.name}-{channel or 'chromium'}-error.png"
                page.screenshot(path=str(shot))
                result["screenshot"] = str(shot)
            except Exception:
                pass
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--channel", default=os.environ.get("PW_CHANNEL", ""))
    parser.add_argument("--wait", type=int, default=75)
    args = parser.parse_args()

    result = diagnose(Path(args.profile).resolve(), args.channel.strip() or None, args.wait)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["state"] in {"ready_chat_list", "ready_search_box", "qr_required", "loading_timeout"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

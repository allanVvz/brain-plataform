#!/usr/bin/env python3
"""Crop the PersonaCatalogCard on /persona to a focused PNG.

Run after screenshot_persona_dashboard.py logged in successfully — this one
opens a fresh browser, restores the session cookie and crops just the
'Catalogo publico' card.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-artifacts" / "e2e-vz-lupas-full"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://brain-plataform-qa.vercel.app")
    parser.add_argument("--email", default=os.environ.get("QA_DASHBOARD_EMAIL", "allan@brain-ai.qa"))
    parser.add_argument("--password", default=os.environ.get("QA_DASHBOARD_PASSWORD", "QaBrain2026!"))
    parser.add_argument("--persona-slug", default="vz-lupas")
    args = parser.parse_args()

    out = ARTIFACTS / f"screenshot-persona-catalog-card-{args.persona_slug}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--ignore-certificate-errors"])
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1800})
        page = ctx.new_page()
        page.goto(f"{args.base}/login", wait_until="networkidle", timeout=45000)
        page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
        page.fill('input[autocomplete="username"]', args.email)
        page.fill('input[autocomplete="current-password"]', args.password)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
        page.evaluate(f'window.localStorage.setItem("ai-brain-persona-slug", "{args.persona_slug}")')
        page.goto(f"{args.base}/persona", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(7000)
        # Anchor on the heading text inside the card. Walk up to .panel container.
        locator = page.locator('p:has-text("Catalogo publico")').first
        locator.wait_for(state="visible", timeout=15000)
        card = locator.locator('xpath=ancestor::div[contains(@class, "panel")][1]')
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        card.screenshot(path=str(out))
        browser.close()
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

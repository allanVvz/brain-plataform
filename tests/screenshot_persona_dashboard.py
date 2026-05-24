#!/usr/bin/env python3
"""Login to the QA dashboard and screenshot the Persona page for VZ Lupas.

Proof of the new catalog_url editable card. Reads credentials from CLI/env.
"""
from __future__ import annotations

import argparse
import os
import sys
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

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / f"screenshot-persona-{args.persona_slug}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--ignore-certificate-errors"])
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 2400})
        page = ctx.new_page()
        page.goto(f"{args.base}/login", wait_until="networkidle", timeout=45000)
        page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
        page.fill('input[autocomplete="username"]', args.email)
        page.fill('input[autocomplete="current-password"]', args.password)
        page.keyboard.press("Enter")
        # Wait until session cookie is set and the SPA navigates away from /login.
        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
        # Set the persona before navigating so PersonaPage adopts it immediately.
        page.evaluate(f'window.localStorage.setItem("ai-brain-persona-slug", "{args.persona_slug}")')
        page.goto(f"{args.base}/persona", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(6000)
        page.screenshot(path=str(out), full_page=True)
        browser.close()
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

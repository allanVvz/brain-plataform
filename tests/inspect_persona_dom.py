#!/usr/bin/env python3
"""Quick DOM inspector — login and dump body text + html size so we can see
whether PersonaCatalogCard rendered."""
from __future__ import annotations
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-artifacts" / "e2e-vz-lupas-full"

BASE = os.environ.get("QA_BASE", "https://brain-plataform-qa.vercel.app")
EMAIL = os.environ.get("QA_DASHBOARD_EMAIL", "allan@brain-ai.qa")
PW = os.environ.get("QA_DASHBOARD_PASSWORD", "QaBrain2026!")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--ignore-certificate-errors"])
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1800})
        page = ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle", timeout=45000)
        page.fill('input[autocomplete="username"]', EMAIL)
        page.fill('input[autocomplete="current-password"]', PW)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
        page.evaluate('window.localStorage.setItem("ai-brain-persona-slug", "vz-lupas")')
        page.goto(f"{BASE}/persona", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(7000)
        body = page.evaluate("() => document.body.innerText")
        (ARTIFACTS / "persona-body-text.txt").write_text(body, encoding="utf-8")
        print("=== body text excerpt ===")
        for kw in ("Catalogo", "Cardapio", "catalog_url", "URL persistida", "Abrir catalogo", "Salvar"):
            idx = body.find(kw)
            print(f"  '{kw}' -> idx={idx}")
        # Bundle hash inspection
        scripts = page.evaluate("() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src).slice(0, 5)")
        print("=== first 5 script src ===")
        for s in scripts:
            print(" ", s)
        browser.close()


if __name__ == "__main__":
    main()

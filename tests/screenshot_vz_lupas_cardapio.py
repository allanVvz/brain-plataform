#!/usr/bin/env python3
"""Screenshot helper for the VZ Lupas catalog at baita-cardapio-qa.

Uses Playwright with the Vercel SSO share token so the QA preview deployment
(which is protected by Vercel Authentication) renders for headless capture.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-artifacts" / "e2e-vz-lupas-full"
SHOT_PATH = ARTIFACTS / "screenshot-cardapio-vz-lupas.png"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default=str(SHOT_PATH))
    parser.add_argument("--wait", type=int, default=8000)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--ignore-certificate-errors"])  # SChannel workaround
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 2200})
        page = ctx.new_page()
        page.goto(args.url, wait_until="networkidle", timeout=45000)
        # Cardapio uses React Query w/ 15s polling. Give the menu fetch room.
        page.wait_for_timeout(args.wait)
        page.screenshot(path=args.out, full_page=True)
        browser.close()
    print(f"saved screenshot -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

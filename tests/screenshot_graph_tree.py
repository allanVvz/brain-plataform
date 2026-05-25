#!/usr/bin/env python3
"""Login as allan, navigate to /grafos for a chosen persona, force the
semantic_tree mode and screenshot the top-down hierarchy."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-artifacts" / "e2e-tock-fatal-topdown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://brain-plataform-qa.vercel.app")
    parser.add_argument("--email", default=os.environ.get("QA_DASHBOARD_EMAIL", "allan@brain-ai.qa"))
    parser.add_argument("--password", default=os.environ.get("QA_DASHBOARD_PASSWORD", "QaBrain2026!"))
    parser.add_argument("--persona-slug", default="tock-fatal")
    parser.add_argument("--out-suffix", default="")
    args = parser.parse_args()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    suffix = args.out_suffix or f"-{args.persona_slug}"
    out = ARTIFACTS / f"screenshot-grafo-tree{suffix}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--ignore-certificate-errors"])
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1600, "height": 1200})
        page = ctx.new_page()
        page.goto(f"{args.base}/login", wait_until="networkidle", timeout=45000)
        page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
        page.fill('input[autocomplete="username"]', args.email)
        page.fill('input[autocomplete="current-password"]', args.password)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
        # Force the persona in localStorage before navigating to /grafos so
        # the React Flow viewport renders with the right scope on mount.
        # Wipe any saved graph viewport so the initial fitView (padding 0.2 for
        # semantic_tree) takes effect on this fresh session.
        page.evaluate(
            """(slug) => {
              window.localStorage.setItem('ai-brain-persona-slug', slug);
              const keys = [];
              for (let i = 0; i < window.localStorage.length; i++) keys.push(window.localStorage.key(i));
              for (const k of keys) {
                if (k && (k.includes('graph-viewport') || k.includes('reactflow') || k.startsWith('rf:') || k.includes('viewport'))) {
                  window.localStorage.removeItem(k);
                }
              }
            }""",
            args.persona_slug,
        )
        page.goto(f"{args.base}/knowledge/graph", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        # The page exposes a "Tree" / "Arvore" toggle button — try common labels.
        for label in ("Tree", "Arvore", "Árvore", "Semantic tree", "semantic_tree"):
            btn = page.get_by_role("button", name=label, exact=False)
            try:
                if btn.count() > 0:
                    btn.first.click(timeout=4000)
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue
        page.wait_for_timeout(5000)  # let layout settle
        canvas = page.locator(".react-flow")
        if canvas.count() > 0:
            box = canvas.first.bounding_box()
            if box:
                # Center the mouse over the tree (which renders bottom-center)
                # then Ctrl+wheel up to zoom in 6 steps so the tree fills the
                # frame. Pyppeteer/Playwright deltaY < 0 = zoom in when Ctrl held.
                tree_x = box["x"] + box["width"] / 2
                tree_y = box["y"] + box["height"] * 0.72
                page.mouse.move(tree_x, tree_y)
                page.keyboard.down("Control")
                for _ in range(8):
                    page.mouse.wheel(0, -120)
                    page.wait_for_timeout(120)
                page.keyboard.up("Control")
        page.wait_for_timeout(1500)
        if canvas.count() > 0:
            box = canvas.first.bounding_box()
            if box:
                page.screenshot(path=str(out), clip=box, full_page=False)
            else:
                page.screenshot(path=str(out), full_page=False)
        else:
            page.screenshot(path=str(out), full_page=False)
        browser.close()
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

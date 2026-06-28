"""Re-run just the screenshots step (login + visual validation)."""
from __future__ import annotations
import sys, json
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

DASH = "http://127.0.0.1:3000"
PERSONA_SLUG = "vz-lupas"
PERSONA_ID = "46872921-6390-4d49-ae13-6eeb75bf4d21"
LOGIN_EMAIL = "admin@local.dev"
LOGIN_PASS = "Brain2026!"
OUT = Path(__file__).parent

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    page.goto(f"{DASH}/login", wait_until="domcontentloaded")
    page.wait_for_selector('input[placeholder="operador@empresa.com"]', timeout=10000)
    page.wait_for_selector('input[placeholder="Digite sua senha"]', timeout=10000)
    page.locator('input[placeholder="operador@empresa.com"]').fill(LOGIN_EMAIL)
    page.locator('input[placeholder="Digite sua senha"]').fill(LOGIN_PASS)
    em = page.locator('input[placeholder="operador@empresa.com"]').input_value()
    pw = page.locator('input[placeholder="Digite sua senha"]').input_value()
    log(f"  pre-submit email='{em}' pwd_len={len(pw)}")
    page.locator('button[type="submit"]').click()
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    except Exception as exc:
        log(f"  redirect timeout: {exc}")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "ss_01_after_login.png"), full_page=True)
    log(f"  after_login_url: {page.url}")

    # set persona
    page.evaluate(
        """({slug, pid}) => {
            localStorage.setItem('ai-brain-persona-slug', slug);
            localStorage.setItem('ai-brain-persona-id', pid);
            window.dispatchEvent(new CustomEvent('ai-brain-persona-change', {detail:{slug, id:pid}}));
        }""",
        {"slug": PERSONA_SLUG, "pid": PERSONA_ID},
    )
    page.wait_for_timeout(500)

    def shot(name, url, wait_ms=3000):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(wait_ms)
        except Exception as exc:
            log(f"  goto {url} warn: {exc}")
        page.screenshot(path=str(OUT / name), full_page=True)
        log(f"  shot {name}  url={page.url}")

    shot("ss_02_capture.png", f"{DASH}/knowledge/capture", 3500)
    shot("ss_03_graph.png",   f"{DASH}/knowledge/graph",   6000)
    shot("ss_04_assets.png",  f"{DASH}/knowledge/assets",  4500)
    shot("ss_05_logs.png",    f"{DASH}/logs",              3500)
    browser.close()
log("DONE")

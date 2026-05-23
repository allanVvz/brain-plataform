"""Retry only the /knowledge/assets screenshot with longer wait."""
from pathlib import Path
from playwright.sync_api import sync_playwright

DASH = "http://127.0.0.1:3000"
LOGIN_EMAIL = "admin@local.dev"
LOGIN_PASS = "Brain2026!"
PERSONA_SLUG = "vz-lupas"
PERSONA_ID = "46872921-6390-4d49-ae13-6eeb75bf4d21"
OUT = Path(__file__).parent

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(f"{DASH}/login", wait_until="domcontentloaded")
    page.wait_for_selector('input[placeholder="operador@empresa.com"]')
    page.locator('input[placeholder="operador@empresa.com"]').fill(LOGIN_EMAIL)
    page.locator('input[placeholder="Digite sua senha"]').fill(LOGIN_PASS)
    page.locator('button[type="submit"]').click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    page.wait_for_timeout(2000)
    page.evaluate(
        """({slug,pid}) => {
            localStorage.setItem('ai-brain-persona-slug', slug);
            localStorage.setItem('ai-brain-persona-id', pid);
            window.dispatchEvent(new CustomEvent('ai-brain-persona-change', {detail:{slug,id:pid}}));
        }""",
        {"slug": PERSONA_SLUG, "pid": PERSONA_ID},
    )
    page.wait_for_timeout(500)
    page.goto(f"{DASH}/knowledge/assets", wait_until="domcontentloaded")
    # Wait until "Carregando..." disappears OR up to 25s
    try:
        page.wait_for_function(
            "() => !document.body.innerText.includes('Carregando')",
            timeout=25000,
        )
    except Exception as e:
        print(f"  wait warn: {e}")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "ss_04_assets.png"), full_page=True)
    print(f"  saved ss_04_assets.png url={page.url}")
    browser.close()

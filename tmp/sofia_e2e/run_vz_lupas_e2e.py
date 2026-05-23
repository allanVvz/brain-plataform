"""VZ Lupas E2E — criacao de cards/edges/assets + validacao frontend + relatorio.

Flow:
  T1: 1 node brand "VZ Lupas" via /knowledge/intake/plan
  T2: espinha completa (brand+briefing+campaign+audience+product_group+1 product)
  T3: grafo (3 product_groups x 3 oculos = 9 products) + 3 imagens em /assets/upload

Validacoes (Playwright):
  /login (smoke), /knowledge/capture, /knowledge/graph, /knowledge/assets, /logs

A criacao usa as mesmas rotas que o modal Sofia em /knowledge/capture chama
quando o operador salva o plano: /knowledge/intake/plan e /assets/upload.
"""
from __future__ import annotations
import json
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

# ─── Config ─────────────────────────────────────────────────────
BASE = "http://127.0.0.1:8001"
DASH = "http://127.0.0.1:3000"
PERSONA_SLUG = "vz-lupas"
PERSONA_ID = "46872921-6390-4d49-ae13-6eeb75bf4d21"
ADMIN_TOKEN = "qa-baita-admin-c3f2c9f6c87842d3a59b9e1c0a8b5d77"
HEADERS_JSON = {"x-ai-brain-admin-token": ADMIN_TOKEN, "Content-Type": "application/json"}
HEADERS_AUTH = {"x-ai-brain-admin-token": ADMIN_TOKEN}
LOGIN_EMAIL = "admin@local.dev"
LOGIN_PASS = "Brain2026!"

OUT = Path(__file__).parent
OUT.mkdir(exist_ok=True)
TS = int(time.time())


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ─── Geracao de imagens ─────────────────────────────────────────
def gen_oculos(label: str, hex_color: str, path: Path) -> None:
    """Gera 1 PNG 600x400 com forma de oculos + label."""
    img = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(img)
    color = hex_color
    # left lens
    d.ellipse((80, 140, 240, 300), outline=color, width=10)
    # right lens
    d.ellipse((360, 140, 520, 300), outline=color, width=10)
    # bridge
    d.line((240, 220, 360, 220), fill=color, width=10)
    # temples
    d.line((80, 220, 30, 200), fill=color, width=10)
    d.line((520, 220, 570, 200), fill=color, width=10)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    d.text((130, 340), label, fill=color, font=font)
    img.save(path, "PNG")


# ─── Posts ─────────────────────────────────────────────────────
def post_plan(name: str, plan: dict) -> dict:
    log(f"POST /knowledge/intake/plan ({name}) entries={len(plan.get('entries', []))} links={len(plan.get('links', []))}")
    r = requests.post(f"{BASE}/knowledge/intake/plan", headers=HEADERS_JSON, json=plan, timeout=180)
    body = r.text
    try:
        data = r.json()
    except Exception:
        data = {"raw": body[:500]}
    if r.status_code >= 300:
        log(f"  HTTP {r.status_code}: {body[:400]}")
    else:
        log(f"  HTTP {r.status_code} entries_created={data.get('entries_created')} nodes={data.get('nodes_created')} edges={data.get('main_edges')}")
    (OUT / f"{name}_response.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": r.status_code, "data": data}


def upload_asset(image_path: Path, branch_hint: str) -> dict:
    log(f"POST /assets/upload file={image_path.name} branch_hint={branch_hint}")
    with image_path.open("rb") as fh:
        files = {"file": (image_path.name, fh, "image/png")}
        data = {
            "persona_id": PERSONA_ID,
            "persona_slug": PERSONA_SLUG,
            "branch_hint": branch_hint,
            "asset_function": "gallery",
        }
        r = requests.post(f"{BASE}/assets/upload", headers=HEADERS_AUTH, files=files, data=data, timeout=120)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:400]}
    log(f"  HTTP {r.status_code} asset_id={(body or {}).get('asset_id') or (body or {}).get('id')}")
    (OUT / f"upload_{branch_hint}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": r.status_code, "data": body}


# ─── T1 ─────────────────────────────────────────────────────────
def t1() -> dict:
    log("=== T1: 1 node brand 'VZ Lupas' ===")
    plan = {
        "persona_slug": PERSONA_SLUG,
        "entries": [{
            "title": "VZ Lupas",
            "content_type": "brand",
            "slug": f"vz-lupas-brand-t1-{TS}",
            "content": (
                "VZ Lupas e uma marca de oculos de alta qualidade. Especializada em "
                "lentes premium e armacoes exclusivas para clientes que valorizam estilo "
                "e qualidade optica."
            ),
            "tags": ["brand", "vz-lupas", "oculos", "e2e"],
            "metadata": {
                "e2e_test": "T1",
                "test_tag": "vz_lupas_e2e",
                "test_run_ts": TS,
            },
        }],
        "links": [],
        "source": "e2e_test",
        "source_ref": f"e2e-t1-{TS}",
        "validate": True,
    }
    return post_plan("t1", plan)


# ─── T2 ─────────────────────────────────────────────────────────
def t2() -> dict:
    log("=== T2: espinha brand->briefing->campaign->audience->product_group+1 product ===")
    sb = f"vz-brand-t2-{TS}"
    sbf = f"vz-briefing-t2-{TS}"
    sc = f"vz-campaign-t2-{TS}"
    sa = f"vz-audience-t2-{TS}"
    spg = f"vz-pg-t2-{TS}"
    sp = f"vz-prod-t2-{TS}"
    plan = {
        "persona_slug": PERSONA_SLUG,
        "entries": [
            {"title": "VZ Lupas Brand T2", "content_type": "brand", "slug": sb,
             "content": "Brand de teste T2: espinha completa.",
             "tags": ["e2e", "vz-lupas", "oculos"], "metadata": {"e2e_test": "T2", "test_tag": "vz_lupas_e2e"}},
            {"title": "Briefing Colecao Lentes 2026", "content_type": "briefing", "slug": sbf,
             "content": "Briefing da campanha de oculos premium VZ.",
             "tags": ["e2e", "oculos"], "metadata": {"e2e_test": "T2", "test_tag": "vz_lupas_e2e", "parent_slug": sb}},
            {"title": "Campanha Lentes Premium VZ", "content_type": "campaign", "slug": sc,
             "content": "Campanha de lancamento das lentes premium VZ Lupas.",
             "tags": ["e2e", "oculos"], "metadata": {"e2e_test": "T2", "test_tag": "vz_lupas_e2e", "parent_slug": sbf}},
            {"title": "Cliente VZ Premium", "content_type": "audience", "slug": sa,
             "content": "Cliente que valoriza qualidade optica, design exclusivo e estilo.",
             "tags": ["e2e", "premium"], "metadata": {"e2e_test": "T2", "test_tag": "vz_lupas_e2e", "parent_slug": sc}},
            {"title": "Oculos Premium VZ", "content_type": "product_group", "slug": spg,
             "content": "Grupo Oculos Premium VZ Lupas.",
             "tags": ["e2e", "oculos", "premium"],
             "metadata": {"e2e_test": "T2", "test_tag": "vz_lupas_e2e", "parent_slug": sa}},
            {"title": "Lupa VZ Aviador Black", "content_type": "product", "slug": sp,
             "content": "Oculos aviador preto VZ Lupas, lente polarizada UV400.",
             "tags": ["oculos", "aviador", "e2e"],
             "metadata": {
                 "e2e_test": "T2", "test_tag": "vz_lupas_e2e", "parent_slug": spg,
                 "display_price": 499, "original_price": 499,
             }},
        ],
        "links": [
            {"source_slug": sb,  "target_slug": sbf, "relation_type": "brand_has_briefing"},
            {"source_slug": sbf, "target_slug": sc,  "relation_type": "briefing_has_campaign"},
            {"source_slug": sc,  "target_slug": sa,  "relation_type": "campaign_has_audience"},
            {"source_slug": sa,  "target_slug": spg, "relation_type": "audience_has_product_group"},
            {"source_slug": spg, "target_slug": sp,  "relation_type": "product_group_has_product"},
        ],
        "source": "e2e_test",
        "source_ref": f"e2e-t2-{TS}",
        "validate": True,
    }
    return post_plan("t2", plan)


# ─── T3 ─────────────────────────────────────────────────────────
def t3() -> dict:
    log("=== T3: 3 product_groups x 3 oculos + 3 imagens ===")
    # gerar 3 imagens dummy
    images = [
        (f"vz-pg-sol-t3-{TS}",    "Sol",     "#1e293b", OUT / "img_sol.png",    "VZ Lupas Sol"),
        (f"vz-pg-grau-t3-{TS}",   "Grau",    "#7c3aed", OUT / "img_grau.png",   "VZ Lupas Grau"),
        (f"vz-pg-clipon-t3-{TS}", "Clip-on", "#0891b2", OUT / "img_clipon.png", "VZ Lupas ClipOn"),
    ]
    for _, _, color, path, label in images:
        gen_oculos(label, color, path)
        log(f"  imagem gerada: {path.name}")

    pgs = [
        (f"vz-pg-sol-t3-{TS}",    "Oculos de Sol VZ",     "Grupo Oculos de Sol VZ Lupas - linha de protecao UV."),
        (f"vz-pg-grau-t3-{TS}",   "Armacoes de Grau VZ",  "Grupo Armacoes de Grau VZ Lupas - armacoes para lentes corretivas."),
        (f"vz-pg-clipon-t3-{TS}", "Clip-on VZ",           "Grupo Clip-on VZ Lupas - clip solar para armacoes de grau."),
    ]
    # 3 products por PG
    products = {
        pgs[0][0]: [
            (f"vz-sol-aviador-t3-{TS}",   "Lupa Sol Aviador",   399),
            (f"vz-sol-quadrado-t3-{TS}",  "Lupa Sol Quadrado",  449),
            (f"vz-sol-redondo-t3-{TS}",   "Lupa Sol Redondo",   379),
        ],
        pgs[1][0]: [
            (f"vz-grau-metal-t3-{TS}",    "Armacao Grau Metal",    299),
            (f"vz-grau-acetato-t3-{TS}",  "Armacao Grau Acetato",  349),
            (f"vz-grau-titanio-t3-{TS}",  "Armacao Grau Titanio",  599),
        ],
        pgs[2][0]: [
            (f"vz-clipon-aviator-t3-{TS}", "Clip-on Aviator",  199),
            (f"vz-clipon-classic-t3-{TS}", "Clip-on Classic",  179),
            (f"vz-clipon-sport-t3-{TS}",   "Clip-on Sport",    229),
        ],
    }
    entries = []
    links = []
    for pg_slug, pg_title, pg_content in pgs:
        entries.append({
            "title": pg_title, "content_type": "product_group", "slug": pg_slug,
            "content": pg_content,
            "tags": ["oculos", "e2e", "vz-lupas"],
            "metadata": {"e2e_test": "T3", "test_tag": "vz_lupas_e2e", "test_run_ts": TS},
        })
        for prod_slug, prod_title, price in products[pg_slug]:
            entries.append({
                "title": prod_title, "content_type": "product", "slug": prod_slug,
                "content": f"{prod_title} - oculos VZ Lupas, R$ {price}.",
                "tags": ["oculos", "e2e", "vz-lupas"],
                "metadata": {
                    "e2e_test": "T3", "test_tag": "vz_lupas_e2e", "test_run_ts": TS,
                    "parent_slug": pg_slug,
                    "display_price": price, "original_price": price,
                },
            })
            links.append({
                "source_slug": pg_slug, "target_slug": prod_slug,
                "relation_type": "product_group_has_product",
            })
    plan = {
        "persona_slug": PERSONA_SLUG,
        "entries": entries,
        "links": links,
        "source": "e2e_test",
        "source_ref": f"e2e-t3-{TS}",
        "validate": True,
    }
    plan_result = post_plan("t3", plan)

    log("--- Upload 3 imagens ---")
    uploads = []
    for pg_slug, _, _, path, _ in images:
        u = upload_asset(path, pg_slug)
        uploads.append(u)
    return {"plan": plan_result, "uploads": uploads}


# ─── Playwright screenshots ─────────────────────────────────────
def screenshots() -> dict:
    log("=== Playwright: login + screenshots ===")
    out: dict[str, Any] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # 1) Login
        page.goto(f"{DASH}/login", wait_until="domcontentloaded")
        page.wait_for_selector('input[placeholder="operador@empresa.com"]', timeout=10000)
        page.wait_for_selector('input[placeholder="Digite sua senha"]', timeout=10000)
        page.locator('input[placeholder="operador@empresa.com"]').fill(LOGIN_EMAIL)
        page.locator('input[placeholder="Digite sua senha"]').fill(LOGIN_PASS)
        # Verify both are filled before clicking
        em = page.locator('input[placeholder="operador@empresa.com"]').input_value()
        pw = page.locator('input[placeholder="Digite sua senha"]').input_value()
        log(f"  pre-submit email_len={len(em)} pwd_len={len(pw)}")
        page.locator('button[type="submit"]').click()
        # Wait for URL to leave /login (router.replace("/"))
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        except Exception as exc:
            log(f"  login redirect timeout: {exc}")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "ss_01_after_login.png"), full_page=True)
        out["after_login_url"] = page.url
        log(f"  after_login_url: {page.url}")

        # Force-select vz-lupas persona in localStorage and dispatch event so
        # the AppShell + each page picks it up. Then navigate.
        page.evaluate(
            """({slug, pid}) => {
                localStorage.setItem('ai-brain-persona-slug', slug);
                localStorage.setItem('ai-brain-persona-id', pid);
                window.dispatchEvent(new CustomEvent('ai-brain-persona-change', {detail:{slug, id:pid}}));
            }""",
            {"slug": PERSONA_SLUG, "pid": PERSONA_ID},
        )
        page.wait_for_timeout(500)

        def shot(name: str, url: str, wait_ms: int = 3000) -> None:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(wait_ms)
            except Exception as exc:
                log(f"  goto {url} warn: {exc}")
            page.screenshot(path=str(OUT / name), full_page=True)

        shot("ss_02_capture.png", f"{DASH}/knowledge/capture", 3000)
        shot("ss_03_graph.png",   f"{DASH}/knowledge/graph",   5000)
        shot("ss_04_assets.png",  f"{DASH}/knowledge/assets",  4000)
        shot("ss_05_logs.png",    f"{DASH}/logs",              3000)

        browser.close()
    log("screenshots saved")
    return out


# ─── Main ──────────────────────────────────────────────────────
def main() -> int:
    summary: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "ts": TS,
        "persona": {"slug": PERSONA_SLUG, "id": PERSONA_ID},
    }
    summary["t1"] = t1()
    summary["t2"] = t2()
    summary["t3"] = t3()
    try:
        summary["screenshots"] = screenshots()
    except Exception as exc:
        log(f"screenshots ERROR: {exc}")
        summary["screenshots"] = {"error": str(exc)}
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

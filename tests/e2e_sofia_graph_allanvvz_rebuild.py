#!/usr/bin/env python3
"""BLOCKED/EXPERIMENTAL BRA-91 gate: Sofia Graph rebuilds AllanVvz / VZ Lupas from real crawler data.

This test intentionally drives the Graph UI chat. It must not rebuild the graph
through direct API shortcuts, because the acceptance target is Sofia autonomy.

Paused for BRA-91 safe validation: do not extend this Python UI/browser E2E.
It remains blocked unless Playwright Node is adopted for dashboard E2E and the
caller explicitly passes --allow-destructive.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


AI_BRAIN_ROOT = Path(__file__).resolve().parent.parent
PAPERCLIP_ROOT = Path(os.environ.get("PAPERCLIP_ROOT") or AI_BRAIN_ROOT.parent / "paperclip")
ARTIFACTS_DIR = PAPERCLIP_ROOT / "test-artifacts" / "e2e"
RULES_PATH = Path(os.environ.get("GRAPH_RULES_PATH") or AI_BRAIN_ROOT / "ai_brain_regras_negocio_grafo.txt")

API_BASE = os.environ.get("AI_BRAIN_BASE_URL") or os.environ.get("API_BASE") or "http://127.0.0.1:8001"
DASHBOARD_URL = os.environ.get("GRAPH_URL") or "http://192.168.0.182:3000/knowledge/graph?mode=semantic_tree"
TOKEN = os.environ.get("AI_BRAIN_ADMIN_TEST_TOKEN") or "qa-baita-admin-c3f2c9f6c87842d3a59b9e1c0a8b5d77"
QA_EMAIL = os.environ.get("QA_DASHBOARD_EMAIL") or "allan@brain-ai.qa"
QA_PASSWORD = os.environ.get("QA_DASHBOARD_PASSWORD") or "QaBrain2026!"
PERSONA_SLUG = "allanvvz"
BRAND_NAME = "VZ Lupas"
CATALOG_URL = "https://vzlupas.com"
GROUPS = ["plantaris", "radar", "juliet"]
LOCAL_BROWSER_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

COMMANDS = [
    "limpa completamente o grafo da allanvvz e reconstroi a vz lupas do zero",
    "usa o crawler do site vzlupas.com e pega produtos reais de plantaris, radar e juliet",
    "organiza tudo top down",
    "valida e publica",
]


class GateFailure(Exception):
    pass


def utc_token() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z").replace(":", "-").replace(".", "-")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_json(method: str, route: str, *, body: dict | None = None, params: dict | None = None, timeout: float = 90.0) -> dict:
    url = API_BASE.rstrip("/") + route
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    headers = {
        "Accept": "application/json",
        "X-AI-BRAIN-ADMIN-TOKEN": TOKEN,
        "Authorization": f"Bearer {TOKEN}",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise GateFailure(f"{method} {route} -> HTTP {exc.code}: {detail[:1000]}") from exc
    except error.URLError as exc:
        raise GateFailure(f"{method} {route} -> connection failed: {exc}") from exc


def node_type(node: dict) -> str:
    data = node.get("data") or {}
    return str(data.get("node_type") or data.get("content_type") or node.get("node_type") or node.get("type") or "").lower()


def node_title(node: dict) -> str:
    data = node.get("data") or {}
    return str(data.get("title") or data.get("label") or node.get("title") or node.get("label") or "")


def node_slug(node: dict) -> str:
    data = node.get("data") or {}
    return str(data.get("slug") or node.get("slug") or "").lower()


def node_url(node: dict) -> str:
    data = node.get("data") or {}
    meta = data.get("metadata") or node.get("metadata") or {}
    for key in ("url", "source_url", "product_url", "canonical_url", "source_ref"):
        value = data.get(key) or meta.get(key)
        if value:
            return str(value)
    return ""


def graph_data() -> dict:
    return http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": PERSONA_SLUG, "include_embedded": "true", "mode": "semantic_tree", "max_depth": "6"},
        timeout=120,
    )


def crawl_products(session_id: str) -> dict:
    return http_json(
        "POST",
        "/kb-intake/crawl-preview",
        body={"url": CATALOG_URL, "session_id": session_id},
        timeout=180,
    )


def candidate_url(product: dict) -> str:
    url = str(product.get("url") or product.get("source_url") or product.get("product_url") or "")
    if url:
        return url
    handle = str(product.get("handle") or "").strip("/")
    if handle:
        return f"{CATALOG_URL}/products/{handle}"
    return CATALOG_URL


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def select_group_products(crawler: dict) -> dict[str, list[dict]]:
    raw = crawler.get("product_candidates") or crawler.get("products") or crawler.get("candidates") or []
    selected: dict[str, list[dict]] = {group: [] for group in GROUPS}
    for product in raw:
        haystack = normalize(" ".join(str(product.get(k) or "") for k in ("title", "handle", "description", "url")))
        for group in GROUPS:
            if group in haystack and len(selected[group]) < 3:
                selected[group].append(
                    {
                        "title": str(product.get("title") or product.get("handle") or "").strip(),
                        "url": candidate_url(product),
                        "handle": product.get("handle"),
                        "source": product.get("source"),
                    }
                )
    return selected


def expect(report: dict, condition: bool, message: str, details: Any = None) -> None:
    row = {"pass": bool(condition), "message": message}
    if details is not None:
        row["details"] = details
    report.setdefault("checks", []).append(row)
    print(("  ok  " if condition else "  FAIL ") + message)
    if not condition:
        raise GateFailure(message)


def chain_validations(report: dict, graph: dict, expected_products: dict[str, list[dict]], before: dict) -> dict:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    by_id = {node.get("id"): node for node in nodes}
    outgoing: dict[str, list[dict]] = {}
    incoming: dict[str, list[dict]] = {}
    for edge in edges:
        outgoing.setdefault(edge.get("source"), []).append(edge)
        incoming.setdefault(edge.get("target"), []).append(edge)

    def find(kind: str, needle: str) -> list[dict]:
        n = normalize(needle)
        return [node for node in nodes if node_type(node) == kind and n in normalize(node_title(node) + " " + node_slug(node))]

    persona = find("persona", "allanvvz")
    brand = find("brand", "vz lupas")
    briefing = find("briefing", "vz lupas")
    campaign = find("campaign", "catalogo vz lupas") or find("campaign", "catálogo vz lupas")
    audience = find("audience", "padrao vz lupas") or find("audience", "padrão vz lupas")
    expect(report, bool(persona), "final graph contains Persona AllanVvz")
    expect(report, bool(brand), "final graph contains Brand VZ Lupas")
    expect(report, bool(briefing), "final graph contains Briefing VZ Lupas")
    expect(report, bool(campaign), "final graph contains Campaign Catalogo VZ Lupas")
    expect(report, bool(audience), "final graph contains Audience Padrao VZ Lupas")

    def has_edge(src: dict, dst: dict) -> bool:
        return any(edge.get("target") == dst.get("id") for edge in outgoing.get(src.get("id"), []))

    expect(report, has_edge(persona[0], brand[0]), "Brand is linked below Persona")
    expect(report, has_edge(brand[0], briefing[0]), "Briefing is linked below Brand")
    expect(report, has_edge(briefing[0], campaign[0]), "Campaign is linked below Briefing")
    expect(report, has_edge(campaign[0], audience[0]), "Audience is linked below Campaign")

    old_non_persona = {node.get("id") for node in before.get("nodes") or [] if node_type(node) != "persona"}
    after_ids = {node.get("id") for node in nodes}
    reused = sorted(old_non_persona & after_ids)
    expect(report, not reused, "old AllanVvz non-persona nodes were hard-deleted before rebuild", reused[:20])

    old_edge_ids = {edge.get("id") for edge in before.get("edges") or [] if edge.get("id")}
    after_edge_ids = {edge.get("id") for edge in edges if edge.get("id")}
    reused_edges = sorted(old_edge_ids & after_edge_ids)
    expect(report, not reused_edges, "old AllanVvz edges were hard-deleted before rebuild", reused_edges[:20])

    levels = {"persona": 0, "brand": 1, "briefing": 2, "campaign": 3, "audience": 4, "product_group": 5, "product": 6, "faq": 7, "embed": 8, "embedded": 8}
    direction_errors = []
    forbidden = []
    for edge in edges:
        src = by_id.get(edge.get("source")) or {}
        dst = by_id.get(edge.get("target")) or {}
        src_type = node_type(src)
        dst_type = node_type(dst)
        if levels.get(dst_type, 999) <= levels.get(src_type, -1):
            direction_errors.append({"edge": edge.get("id"), "source_type": src_type, "target_type": dst_type})
        if src_type == "product" and dst_type == "product_group":
            forbidden.append({"edge": edge.get("id"), "error": "product above product_group"})
        if src_type == "persona" and dst_type in {"embed", "embedded"}:
            forbidden.append({"edge": edge.get("id"), "error": "Persona -> Embedded visual"})
        if dst_type in {"embed", "embedded"} and src_type != "faq":
            forbidden.append({"edge": edge.get("id"), "error": "Embedded source is not FAQ"})
    expect(report, not direction_errors, "all final edges are top-down", direction_errors[:20])
    expect(report, not forbidden, "final graph has no forbidden product/embed edges", forbidden[:20])

    product_nodes = [node for node in nodes if node_type(node) == "product"]
    product_details = []
    for group, products in expected_products.items():
        group_nodes = find("product_group", group)
        expect(report, bool(group_nodes), f"final graph contains Product Group {group.title()}")
        group_node = group_nodes[0]
        children = [by_id.get(edge.get("target")) for edge in outgoing.get(group_node.get("id"), [])]
        products_under_group = [node for node in children if node and node_type(node) == "product"]
        expect(report, len(products_under_group) >= 3, f"{group.title()} has at least 3 products below Product Group", [node_title(n) for n in products_under_group])
        expected_titles = [normalize(item["title"]) for item in products]
        matched = []
        for product_node in products_under_group:
            title_norm = normalize(node_title(product_node))
            url = node_url(product_node)
            real_title = any(title_norm and (title_norm in expected or expected in title_norm) for expected in expected_titles)
            real_url = url.startswith(CATALOG_URL)
            matched.append({"title": node_title(product_node), "url": url, "real_title": real_title, "real_url": real_url})
        expect(report, sum(1 for item in matched if item["real_title"] and item["real_url"]) >= 3, f"{group.title()} products are real crawler products with vzlupas.com URLs", matched)
        product_details.extend(matched)

    orphans = [
        {"id": node.get("id"), "title": node_title(node), "type": node_type(node)}
        for node in nodes
        if node_type(node) != "persona" and not incoming.get(node.get("id"))
    ]
    expect(report, not orphans, "final graph has no orphan nodes", orphans[:20])
    expect(report, len(product_nodes) >= 9, "final graph has at least 9 products")
    return {"products": product_details}


def run_graph_chat(report: dict, screenshot_path: Path, *, headed: bool) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise GateFailure("playwright is required for BRA-91 E2E") from exc

    responses: list[dict] = []
    with sync_playwright() as p:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        if not executable:
            executable = next((str(path) for path in LOCAL_BROWSER_CANDIDATES if path.exists()), None)
        launch_args = {"headless": not headed}
        if executable:
            launch_args["executable_path"] = executable
            report["browser_executable"] = executable
        browser = p.chromium.launch(**launch_args)
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.add_init_script(
            """
            window.localStorage.setItem('ai-brain-persona-slug', 'allanvvz');
            window.localStorage.setItem('active_persona_slug', 'allanvvz');
            """
        )

        def on_response(resp: Any) -> None:
            if "/sofia/graph-command" not in resp.url:
                return
            try:
                body = resp.json()
            except Exception:
                body = {"unparsed": True, "status": resp.status}
            responses.append({"url": resp.url, "status": resp.status, "body": body})

        page.on("response", on_response)
        page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=120000)
        if page.locator("input[type='email'], input[name='email']").count():
            email = page.locator('input[autocomplete="username"], input[type="email"], input[name="email"]').first
            password = page.locator('input[autocomplete="current-password"], input[type="password"], input[name="password"]').first
            email.fill(QA_EMAIL)
            password.fill(QA_PASSWORD)
            submit = page.locator('button[type="submit"]').first
            if submit.count() == 0:
                submit = page.get_by_role("button", name=re.compile("Entrar|Login|Sign in")).first
            submit.click()
            page.wait_for_url(lambda url: "/login" not in url, timeout=45000)
            page.evaluate(
                """() => {
                window.localStorage.setItem('ai-brain-persona-slug', 'allanvvz');
                window.localStorage.setItem('active_persona_slug', 'allanvvz');
                }"""
            )
            page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=120000)
        page.get_by_title(re.compile("Abrir Sofia|Fechar Sofia")).click(timeout=30000)
        input_box = page.locator('input[name="message"]').first
        input_box.wait_for(state="visible", timeout=30000)

        for command in COMMANDS:
            before_count = len(responses)
            input_box.fill(command)
            input_box.press("Enter")
            deadline = time.time() + 90
            while len(responses) <= before_count and time.time() < deadline:
                page.wait_for_timeout(500)
            if len(responses) <= before_count:
                raise GateFailure(f"Sofia Graph did not call /sofia/graph-command for command: {command}")
            page.wait_for_timeout(1200)

        page.reload(wait_until="networkidle", timeout=120000)
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()
    report["sofia_graph_responses"] = responses
    return responses


def validate_sofia_used_crawler(report: dict, responses: list[dict]) -> None:
    text = json.dumps(responses, ensure_ascii=False).lower()
    has_crawler = any(term in text for term in ("crawler", "crawl_catalog", "crawl-preview", "catalog_crawler", "vzlupas.com"))
    persisted = any((resp.get("body") or {}).get("persisted") is True for resp in responses)
    expect(report, has_crawler, "Sofia Graph response/tool_calls show crawler/tool usage")
    expect(report, persisted, "Sofia Graph persisted at least one graph change")


def build_diff(before: dict, after: dict) -> dict:
    before_nodes = {node.get("id"): {"type": node_type(node), "title": node_title(node), "slug": node_slug(node)} for node in before.get("nodes") or []}
    after_nodes = {node.get("id"): {"type": node_type(node), "title": node_title(node), "slug": node_slug(node)} for node in after.get("nodes") or []}
    before_edges = {edge.get("id"): edge for edge in before.get("edges") or [] if edge.get("id")}
    after_edges = {edge.get("id"): edge for edge in after.get("edges") or [] if edge.get("id")}
    return {
        "nodes_before": len(before_nodes),
        "nodes_after": len(after_nodes),
        "edges_before": len(before_edges),
        "edges_after": len(after_edges),
        "node_ids_removed": sorted(set(before_nodes) - set(after_nodes)),
        "node_ids_added": sorted(set(after_nodes) - set(before_nodes)),
        "edge_ids_removed": sorted(set(before_edges) - set(after_edges)),
        "edge_ids_added": sorted(set(after_edges) - set(before_edges)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true", help="Required to send the human hard-delete rebuild command through Sofia Graph.")
    args = parser.parse_args()

    token = utc_token()
    before_path = ARTIFACTS_DIR / f"allanvvz-rebuild-before-{token}.json"
    crawler_path = ARTIFACTS_DIR / f"allanvvz-crawler-products-{token}.json"
    after_path = ARTIFACTS_DIR / f"allanvvz-rebuild-after-{token}.json"
    diff_path = ARTIFACTS_DIR / f"allanvvz-rebuild-diff-{token}.json"
    screenshot_path = ARTIFACTS_DIR / f"allanvvz-rebuild-graph-{token}.png"

    report = {
        "ok": False,
        "issue": "BRA-91",
        "timestamp": token,
        "api_base": API_BASE,
        "dashboard_url": DASHBOARD_URL,
        "persona_slug": PERSONA_SLUG,
        "brand": BRAND_NAME,
        "catalog_url": CATALOG_URL,
        "rules_path": str(RULES_PATH),
        "commands": COMMANDS,
        "checks": [],
        "artifacts": {
            "before": str(before_path),
            "crawler_products": str(crawler_path),
            "after": str(after_path),
            "diff": str(diff_path),
            "screenshot": str(screenshot_path),
        },
    }

    try:
        print("== BRA-91 Sofia Graph AllanVvz rebuild E2E ==")
        expect(report, RULES_PATH.exists(), "official graph business rules file exists", str(RULES_PATH))
        report["rules_excerpt"] = RULES_PATH.read_text(encoding="utf-8", errors="replace")[:4000]

        before = graph_data()
        write_json(before_path, before)
        expect(report, isinstance(before.get("nodes"), list), "before graph artifact captured")

        crawler = crawl_products(f"bra91-allanvvz-{token}")
        expected_products = select_group_products(crawler)
        crawler_artifact = {"raw": crawler, "selected_by_group": expected_products}
        write_json(crawler_path, crawler_artifact)
        for group in GROUPS:
            expect(report, len(expected_products[group]) >= 3, f"crawler found 3 real {group.title()} products", expected_products[group])

        if not args.allow_destructive:
            raise GateFailure("refusing to send hard-delete rebuild commands without --allow-destructive")

        responses = run_graph_chat(report, screenshot_path, headed=args.headed)
        validate_sofia_used_crawler(report, responses)

        after = graph_data()
        write_json(after_path, after)
        diff = build_diff(before, after)
        write_json(diff_path, diff)

        final_details = chain_validations(report, after, expected_products, before)
        refetched = graph_data()
        after_ids = {node.get("id") for node in after.get("nodes") or []}
        refetched_ids = {node.get("id") for node in refetched.get("nodes") or []}
        expect(report, after_ids == refetched_ids, "refresh/refetch keeps rebuilt graph node ids")
        report["final_details"] = final_details
        report["ok"] = True
        print(f"PASS BRA-91 E2E. Diff: {diff_path}")
        return 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        print(f"FAIL BRA-91 E2E: {exc}")
        if "before" not in locals():
            write_json(before_path, {"error": str(exc)})
        if "crawler" not in locals():
            write_json(crawler_path, {"error": str(exc)})
        if "after" not in locals():
            try:
                write_json(after_path, graph_data())
            except Exception as after_exc:
                write_json(after_path, {"error": str(after_exc)})
        try:
            write_json(diff_path, build_diff(json.loads(before_path.read_text(encoding="utf-8")), json.loads(after_path.read_text(encoding="utf-8"))))
        except Exception as diff_exc:
            write_json(diff_path, {"error": str(diff_exc)})
        return 1
    finally:
        report_path = ARTIFACTS_DIR / f"allanvvz-rebuild-report-{token}.json"
        write_json(report_path, report)
        print(f"Report: {report_path}")


if __name__ == "__main__":
    sys.exit(main())
